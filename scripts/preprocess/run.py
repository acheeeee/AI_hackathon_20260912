"""
前處理主流程 CLI。

用法（在 repo 根目錄，以 .venv_pre 環境執行）：
  python -m scripts.preprocess.run all --input data --release <new-release-id>
或分步：
  python -m scripts.preprocess.run inventory --input data --release <new-release-id>
  python -m scripts.preprocess.run process  --input data --release <new-release-id>
  python -m scripts.preprocess.run validate --release <new-release-id>
  python -m scripts.preprocess.run splits   --release <new-release-id> --eval-version <id>

輸出：data/processed/releases/<release_id>/{documents,pages,sections,chunks,
annotations,citations,duplicates,review_queue,excluded_non_corpus}.jsonl +
manifest.json + qa_report.{json,md}；splits 另輸出
data/evaluation/<eval_version>/splits.json。

守則：
- 原 PDF 不改；不覆寫 backend/data/kb/；不覆寫既有 release（r1/r2/r3 保留原樣）。
- 禁止零輸入成功：輸入不存在 / 基準少檔 / 全類別零筆 -> 非零退出。
- 先寫 staging，validate 通過才標 validated。
- 只有 141 份官方四類語料算入 corpus；`訴願書予行政處分函-1` 等進件文件
  一律排除並記於 excluded_non_corpus.jsonl，不無差別當語料（見 data/README.md）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys
from collections import defaultdict

from . import annotate as A
from . import chunk as C
from . import segment as S
from .common import (
    ALIAS_TABLE_VERSION, CASE_FAMILY_VERSION, CHUNKING_VERSION,
    EVAL_SPLIT_VERSION, EXTRACTION_VERSION, SCHEMA_VERSION,
    SEGMENTATION_VERSION, make_case_family_id, make_document_id,
    make_section_id, normalize_case_no, sha256_file, sha256_text, spans_key,
)
from .extract import extract_pages, flat_lines

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BASELINE_PDF_COUNT = 141
BASELINE_PAGE_COUNT = 731
EVAL_SEED = 42
EVAL_DEV_RATIO = 0.8


def _release_dir(release_id: str) -> str:
    return os.path.join(REPO_ROOT, "data", "processed", "releases", release_id)


def _rel(path: str) -> str:
    return os.path.relpath(path, REPO_ROOT)


def _category_of(path: str) -> str:
    """由相對路徑推斷官方分類目錄名稱。

    支援目前 `data/raw/<分類>/...` 布局，也保留舊 `data/<分類>/...` 相容。
    早期版本只取 `data` 之後的第一段，在 `data/raw/...` 下永遠得到 `raw`，
    造成全部文件落入 unknown、無法重跑（見 sysdoc 3.3 節缺口）。
    """
    rel = _rel(path)
    parts = rel.split(os.sep)
    if len(parts) >= 3 and parts[0] == "data" and parts[1] == "raw":
        return parts[2]
    if len(parts) >= 2 and parts[0] == "data":
        return parts[1]
    return "unknown"


def _write_jsonl(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------- inventory ----------------

def do_inventory(input_dir: str) -> tuple[list[dict], list[dict]]:
    """回傳 (corpus_entries, excluded_entries)。corpus_entries 僅含官方四類
    （見 annotate.CORPUS_CATEGORIES）；其餘一律歸入 excluded_entries，附排除
    原因，不進入後續抽取／切段流程。"""
    root = os.path.join(REPO_ROOT, input_dir) if not os.path.isabs(input_dir) else input_dir
    if not os.path.isdir(root):
        print(f"[FATAL] 輸入目錄不存在：{root}", file=sys.stderr)
        sys.exit(2)
    pdfs = sorted(glob.glob(os.path.join(root, "**", "*.pdf"), recursive=True))
    if not pdfs:
        print(f"[FATAL] 找不到任何 PDF：{root}", file=sys.stderr)
        sys.exit(2)

    by_hash: dict[str, list[str]] = defaultdict(list)
    entries: list[dict] = []
    import fitz
    for p in pdfs:
        sha = sha256_file(p)
        by_hash[sha].append(p)
        d = fitz.open(p)
        pc = d.page_count
        d.close()
        entries.append({
            "source_file": _rel(p),
            "source_sha256": sha,
            "page_count": pc,
            "category": _category_of(p),
        })
    for e in entries:
        aliases = by_hash[e["source_sha256"]]
        e["path_aliases"] = [_rel(a) for a in aliases]
        e["is_duplicate"] = len(aliases) > 1

    corpus = [e for e in entries if e["category"] in A.CORPUS_CATEGORIES]
    excluded = [e for e in entries if e["category"] not in A.CORPUS_CATEGORIES]
    return corpus, excluded


# ---------------- process (extract+segment+chunk+annotate) ----------------

def _segment_dispatch(document_type: str, document_id: str, lines: list[dict],
                      statute_name: str) -> list[dict]:
    if document_type == "statute":
        return S.segment_statute(document_id, lines, statute_name)
    if document_type == "decision":
        return S.segment_decision(document_id, lines)
    if document_type == "interpretation":
        return S.segment_interpretation(document_id, lines)
    if document_type == "precedent":
        return S.segment_precedent(document_id, lines)
    return []


def _statute_name_from_pages(pages: list[dict], fallback: str) -> str:
    import re
    for p in pages[:1]:
        m = re.search(r"法規名稱[：:]\s*(.+)", p["raw_text"])
        if m:
            name = m.group(1).strip()
            name = re.sub(r"\s*EN\s*$", "", name)
            return name
    return fallback


def do_process(input_dir: str, release_id: str):
    corpus_entries, excluded_entries = do_inventory(input_dir)
    if not corpus_entries:
        print("[FATAL] 官方四類語料（見 annotate.CORPUS_CATEGORIES）掃描結果為零，"
              "拒絕產出空 release。", file=sys.stderr)
        sys.exit(2)
    seen_hash: set[str] = set()

    documents: list[dict] = []
    pages_out: list[dict] = []
    sections_out: list[dict] = []
    chunks_out: list[dict] = []
    annotations_out: list[dict] = []
    citations_out: list[dict] = []
    duplicates_out: list[dict] = []
    review_queue: list[dict] = []

    for e in corpus_entries:
        abspath = os.path.join(REPO_ROOT, e["source_file"])
        category = e["category"]
        document_type = A.CATEGORY_TYPE.get(category, "unknown")
        document_id = make_document_id(e["source_sha256"])

        # 同 hash 只抽一次，其餘記為 duplicate 別名
        if e["source_sha256"] in seen_hash:
            duplicates_out.append({
                "document_id": document_id,
                "duplicate_of_sha256": e["source_sha256"],
                "path": e["source_file"],
                "relation": "identical_hash",
                "resolution": "aliased_not_reextracted",
            })
            continue
        seen_hash.add(e["source_sha256"])

        reading_order = "visual" if document_type == "statute" else "source"
        pages = extract_pages(abspath, reading_order=reading_order)
        lines = flat_lines(pages)
        full_text = "\n".join(p["raw_text"] for p in pages)

        # pages.jsonl
        for p in pages:
            pages_out.append({
                "document_id": document_id,
                "extraction_version": EXTRACTION_VERSION,
                "page": p["page"],
                "width": p["width"],
                "height": p["height"],
                "rotation": p["rotation"],
                "raw_text": p["raw_text"],
                "lines": p["lines"],
                "extraction_method": p["extraction_method"],
                "review_status": "needs_review" if p["low_text"] else "unreviewed",
            })
            if p["low_text"]:
                review_queue.append({
                    "item_id": f"{document_id}-p{p['page']}-lowtext",
                    "document_id": document_id,
                    "source_spans": [{
                        "document_id": document_id,
                        "extraction_version": EXTRACTION_VERSION,
                        "page": p["page"], "line": 0,
                        "char_start": 0, "char_end": 0,
                    }],
                    "issue_type": "low_text_page",
                    "severity": "high" if p["nonspace_chars"] == 0 else "medium",
                    "status": "open",
                    "resolution": None,
                    "reviewer": None,
                    "reviewed_at": None,
                    "note": f"非空白字元={p['nonspace_chars']}，須人工視覺判定是否影像頁/需 OCR",
                })

        # document subtype + statute name
        subtype = A.classify_subtype(document_type, abspath, full_text)
        statute_name = _statute_name_from_pages(pages, A.clean_filename(abspath)) if document_type == "statute" else None

        # segment
        segs = _segment_dispatch(document_type, document_id, lines, statute_name or "")
        section_ids: list[str] = []
        covered = set()
        doc_wide_reasons_logged: set[str] = set()
        for seg in segs:
            sid = make_section_id(document_id, seg["ordinal"])
            seg["section_id"] = sid
            section_ids.append(sid)
            for k in range(seg["line_start_idx"], seg["line_end_idx"]):
                covered.add(k)
            sections_out.append({
                "section_id": sid,
                "document_id": document_id,
                "segmentation_version": SEGMENTATION_VERSION,
                "section_type": seg["section_type"],
                "ordinal": seg["ordinal"],
                "source_spans": seg["source_spans"],
                "quote_text": seg["quote_text"],
                "metadata": seg["metadata"],
                "review_status": "unreviewed",
            })
            note = seg["metadata"].get("unsegmented_article_note")
            doc_wide_reason = seg["metadata"].get("unsegmented_reason")
            # 整份文件標題皆不可信（doc_wide_reason 有值）時，同一原因在每個
            # 章節 section 都會重複出現；同一份文件只記一次，避免灌水成幾十筆
            # 一模一樣的 review_queue 項目。個別條號被局部吞併（doc_wide_reason
            # 為 None，只有該 section 自己的 unsegmented_article_keys）則各自記錄，
            # 因為那是每個 section 各自不同的實際缺口。
            if note and (doc_wide_reason is None or doc_wide_reason not in doc_wide_reasons_logged):
                if doc_wide_reason:
                    doc_wide_reasons_logged.add(doc_wide_reason)
                review_queue.append({
                    "item_id": f"{sid}-unsegmented-articles",
                    "document_id": document_id,
                    "source_spans": seg["source_spans"][:1],
                    "issue_type": "toc_widget_merged_articles",
                    "severity": "high",
                    "status": "open",
                    "resolution": None,
                    "reviewer": None,
                    "reviewed_at": None,
                    "note": note,
                })

        # 全文覆蓋檢查：未歸屬的非空白行進 review_queue（不靜默掉段）
        for k, ln in enumerate(lines):
            if k not in covered and ln["text"].strip():
                review_queue.append({
                    "item_id": f"{document_id}-line-{k}-uncovered",
                    "document_id": document_id,
                    "source_spans": [{
                        "document_id": document_id,
                        "extraction_version": EXTRACTION_VERSION,
                        "page": ln["page"], "line": ln["line"],
                        "char_start": ln["char_start"], "char_end": ln["char_end"],
                    }],
                    "issue_type": "uncovered_line",
                    "severity": "medium",
                    "status": "open", "resolution": None,
                    "reviewer": None, "reviewed_at": None,
                    "note": ln["text"][:60],
                })

        # chunks（隔離判定：目前全部 official_batch，index_eligible=True；
        # 決定書歷史主文段預設不進一般檢索文字，標 index_eligible=False）
        for seg in segs:
            seg_index_eligible = True
            flags: list[str] = []
            if seg["section_type"] in ("decision_main_text",):
                seg_index_eligible = False
                flags.append("historical_outcome_excluded")
            for ck in C.make_chunks(seg, document_id, seg_index_eligible, flags):
                chunks_out.append(ck)

        # annotations（決定書欄位；outcome/case_type 為規則式，unreviewed）
        case_family_id = None
        if document_type == "decision":
            hint = A.decision_filename_hint(abspath)
            fields = A.extract_decision_fields(lines, document_id, sections=segs, full_text=full_text)
            annotations_out.append({
                "document_id": document_id,
                "filename_hint": hint,
                "fields": fields,
            })
            case_no_val = fields.get("case_no", {}).get("value")
            norm = normalize_case_no(case_no_val)
            if norm:
                case_family_id = make_case_family_id(norm)

        # citations（此時 target_id 尚未解析；全庫掃完後統一解析，見下方 resolve_citations）
        for cit in A.extract_citations(document_id, lines):
            citations_out.append(cit)

        # documents.jsonl
        documents.append({
            "schema_version": SCHEMA_VERSION,
            "document_id": document_id,
            "case_family_id": case_family_id,
            "document_type": document_type,
            "document_subtype": subtype,
            "source_file": e["source_file"],
            "source_sha256": e["source_sha256"],
            "source_origin": "official_batch",
            "page_count": e["page_count"],
            "extraction_version": EXTRACTION_VERSION,
            "review_status": "unreviewed",
            "section_ids": section_ids,
            "path_aliases": e["path_aliases"],
        })

    # ---- 全庫掃完後的解析：引用 target_id ----
    statute_index = A.build_statute_article_index(sections_out)
    # corpus 內「有 statute_name 的法規」＝這份 release 實際擁有的 11 部法規；
    # 「有 statute_article 的法規」＝其中能逐條索引的子集。兩者不同，見
    # annotate.resolve_citations 的 statute_unsectioned_in_this_release。
    all_statute_names = {
        A.STATUTE_ALIASES.get(s["metadata"]["statute_name"], s["metadata"]["statute_name"])
        for s in sections_out if s["metadata"].get("statute_name")
    }
    sectioned_statute_names = {
        A.STATUTE_ALIASES.get(s["metadata"]["statute_name"], s["metadata"]["statute_name"])
        for s in sections_out if s["section_type"] == "statute_article"
    }
    unsectioned_statute_names = all_statute_names - sectioned_statute_names
    citations_out = A.resolve_citations(
        citations_out, statute_index, all_statute_names, unsectioned_statute_names,
    )

    rel_dir = _release_dir(release_id)
    if os.path.isdir(rel_dir):
        print(f"[FATAL] release 目錄已存在，拒絕覆寫：{_rel(rel_dir)}", file=sys.stderr)
        sys.exit(2)

    artifact_files = {
        "documents.jsonl": documents,
        "pages.jsonl": pages_out,
        "sections.jsonl": sections_out,
        "chunks.jsonl": chunks_out,
        "annotations.jsonl": annotations_out,
        "citations.jsonl": citations_out,
        "duplicates.jsonl": duplicates_out,
        "review_queue.jsonl": review_queue,
        "excluded_non_corpus.jsonl": excluded_entries,
    }
    artifact_hashes: dict[str, str] = {}
    for name, rows in artifact_files.items():
        path = os.path.join(rel_dir, name)
        _write_jsonl(path, rows)
        artifact_hashes[name] = sha256_file(path)

    resolved_citations = len([c for c in citations_out if c["resolved"] == "resolved"])
    families = {d["case_family_id"] for d in documents if d["case_family_id"]}
    non_index_eligible = len([c for c in chunks_out if not c["index_eligible"]])

    config = {
        "schema_version": SCHEMA_VERSION,
        "extraction_version": EXTRACTION_VERSION,
        "segmentation_version": SEGMENTATION_VERSION,
        "chunking_version": CHUNKING_VERSION,
        "alias_table_version": ALIAS_TABLE_VERSION,
        "case_family_version": CASE_FAMILY_VERSION,
        "corpus_categories": sorted(A.CORPUS_CATEGORIES),
        "known_statutes": sorted(A.KNOWN_STATUTES),
        "chunk_target_min": C.TARGET_MIN,
        "chunk_target_max": C.TARGET_MAX,
        "chunk_soft_cap": C.SOFT_CAP,
    }
    manifest = {
        "release_id": release_id,
        "schema_version": SCHEMA_VERSION,
        "extraction_version": EXTRACTION_VERSION,
        "segmentation_version": SEGMENTATION_VERSION,
        "chunking_version": CHUNKING_VERSION,
        "alias_table_version": ALIAS_TABLE_VERSION,
        "case_family_version": CASE_FAMILY_VERSION,
        "config_hash": "cfg_" + sha256_text(json.dumps(config, sort_keys=True, ensure_ascii=False))[:16],
        "input_pdf_count": len(corpus_entries),
        "excluded_non_corpus_count": len(excluded_entries),
        "unique_document_count": len(documents),
        "duplicate_count": len(duplicates_out),
        "page_count": len(pages_out),
        "section_count": len(sections_out),
        "chunk_count": len(chunks_out),
        "index_eligible_chunk_count": len(chunks_out) - non_index_eligible,
        "non_index_eligible_chunk_count": non_index_eligible,
        "citation_count": len(citations_out),
        "citation_resolved_count": resolved_citations,
        "case_family_count": len(families),
        "review_queue_count": len(review_queue),
        "artifact_sha256": artifact_hashes,
        "publish_status": "draft",
    }
    with open(os.path.join(rel_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[process] release={release_id} 產出於 {_rel(rel_dir)}")
    for k, v in manifest.items():
        if k != "artifact_sha256":
            print(f"  {k}: {v}")
    return manifest


# ---------------- validate ----------------

def do_validate(release_id: str):
    rel_dir = _release_dir(release_id)

    def load(name):
        path = os.path.join(rel_dir, name)
        rows = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    documents = load("documents.jsonl")
    pages = load("pages.jsonl")
    sections = load("sections.jsonl")
    chunks = load("chunks.jsonl")

    checks: list[dict] = []

    def add(name, passed, detail):
        checks.append({"check": name, "result": "PASS" if passed else "FAIL", "detail": detail})

    with open(os.path.join(rel_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    # 1) 原件清點（僅算入官方四類語料；進件文件另計於 excluded_non_corpus）
    add("原件清點-PDF數", manifest["input_pdf_count"] == BASELINE_PDF_COUNT,
        f"input={manifest['input_pdf_count']} baseline={BASELINE_PDF_COUNT}")
    add("原件清點-頁數", _total_pages(documents) == BASELINE_PAGE_COUNT,
        f"unique_pages={manifest['page_count']} baseline={BASELINE_PAGE_COUNT}（含重複別名頁見備註）")

    # 2) 主鍵唯一
    doc_ids = [d["document_id"] for d in documents]
    add("主鍵唯一-document_id", len(doc_ids) == len(set(doc_ids)), f"n={len(doc_ids)}")
    sec_ids = [s["section_id"] for s in sections]
    add("主鍵唯一-section_id", len(sec_ids) == len(set(sec_ids)), f"n={len(sec_ids)}")
    chk_ids = [c["chunk_id"] for c in chunks]
    add("主鍵唯一-chunk_id", len(chk_ids) == len(set(chk_ids)), f"n={len(chk_ids)}")

    # 3) 外鍵完整
    sec_set = set(sec_ids)
    doc_set = set(doc_ids)
    dangling = [c["chunk_id"] for c in chunks if c["section_id"] not in sec_set]
    add("外鍵-chunk.section_id", not dangling, f"dangling={len(dangling)}")
    dangling_s = [s["section_id"] for s in sections if s["document_id"] not in doc_set]
    add("外鍵-section.document_id", not dangling_s, f"dangling={len(dangling_s)}")

    # 4) span 合法性 + 100% quote 可重建（sections 與 chunks 全量檢查，非抽查）
    page_line = {}
    for p in pages:
        for ln in p["lines"]:
            page_line[(p["document_id"], p["page"], ln["line"])] = ln["text"]

    def _rebuild(spans, quote_text) -> bool:
        rebuilt = []
        for sp in spans:
            key = (sp["document_id"], sp["page"], sp["line"])
            txt = page_line.get(key)
            if txt is None:
                return False
            if sp["char_start"] < 0 or sp["char_end"] > len(txt) or sp["char_start"] > sp["char_end"]:
                return False
            rebuilt.append(txt[sp["char_start"]:sp["char_end"]])
        return "\n".join(rebuilt) == quote_text

    bad_span = 0
    bad_quote = 0
    for s in sections:
        if not _rebuild(s["source_spans"], s["quote_text"]):
            bad_quote += 1
    add("span合法性/quote可重建-sections", bad_quote == 0, f"mismatch_sections={bad_quote}")

    bad_chunk_quote = 0
    for c in chunks:
        if not _rebuild(c["source_spans"], c["quote_text"]):
            bad_chunk_quote += 1
    add("span合法性/quote可重建-chunks（全量）", bad_chunk_quote == 0,
        f"mismatch_chunks={bad_chunk_quote}/{len(chunks)}")

    # 5) 法條邊界：附加條號獨立、條號可解析、無空內容條文
    statute_secs = [s for s in sections if s["section_type"] == "statute_article"]
    sub_articles = [s for s in statute_secs if s["metadata"].get("article_key") and "-" in str(s["metadata"]["article_key"])]
    add("法條邊界-附加條號存在", len(sub_articles) > 0, f"附加條號 section 數={len(sub_articles)}")
    unresolved_keys = [s for s in statute_secs if not s["metadata"].get("article_key")]
    add("法條邊界-條號可解析", len(unresolved_keys) == 0,
        f"無法解析 article_key 的條文 section={len(unresolved_keys)}")
    empty_articles = [s for s in statute_secs if len(s["quote_text"].strip()) < 3]
    add("法條邊界-無空內容條文", len(empty_articles) == 0,
        f"空內容 statute_article={len(empty_articles)}（曾因分頁小工具假標題產生，見 segment.segment_statute）")

    # 6) 全文覆蓋（review_queue uncovered 記錄，不算 FAIL 但報告）
    rq = load("review_queue.jsonl")
    uncovered = [r for r in rq if r["issue_type"] == "uncovered_line"]
    add("全文覆蓋-未歸屬行已記錄", True, f"uncovered_lines_logged={len(uncovered)}（進 review_queue，未靜默掉段）")

    # 7) index_eligible 明確布林 + chunking_version 齊全
    non_bool = [c["chunk_id"] for c in chunks if not isinstance(c["index_eligible"], bool)]
    add("index_eligible-布林", not non_bool, f"non_bool={len(non_bool)}")
    missing_cv = [c["chunk_id"] for c in chunks if not c.get("chunking_version")]
    add("chunk契約-chunking_version齊全", not missing_cv, f"missing={len(missing_cv)}/{len(chunks)}")

    passed = all(c["result"] == "PASS" for c in checks)
    manifest["publish_status"] = "validated" if passed else "partial"
    with open(os.path.join(rel_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # qa_report
    qa = {
        "release_id": release_id,
        "publish_status": manifest["publish_status"],
        "checks": checks,
        "low_text_pages": len([r for r in rq if r["issue_type"] == "low_text_page"]),
        "uncovered_lines": len(uncovered),
        "unsegmented_article_reports": len([r for r in rq if r["issue_type"] == "toc_widget_merged_articles"]),
        "citation_resolved_count": manifest.get("citation_resolved_count"),
        "citation_count": manifest.get("citation_count"),
        "case_family_count": manifest.get("case_family_count"),
    }
    with open(os.path.join(rel_dir, "qa_report.json"), "w", encoding="utf-8") as f:
        json.dump(qa, f, ensure_ascii=False, indent=2)
    _write_qa_md(rel_dir, qa, manifest)

    print(f"[validate] release={release_id} status={manifest['publish_status']}")
    for c in checks:
        print(f"  [{c['result']}] {c['check']}: {c['detail']}")
    return passed


def _total_pages(documents) -> int:
    return sum(d["page_count"] for d in documents)


def _write_qa_md(rel_dir, qa, manifest):
    lines = [f"# QA 報告：{qa['release_id']}", "",
             f"發布狀態：**{qa['publish_status']}**", "",
             "## 計數", ""]
    for k in ("input_pdf_count", "excluded_non_corpus_count", "unique_document_count",
              "duplicate_count", "page_count", "section_count", "chunk_count",
              "index_eligible_chunk_count", "non_index_eligible_chunk_count",
              "citation_count", "citation_resolved_count", "case_family_count",
              "review_queue_count"):
        lines.append(f"- {k}: {manifest[k]}")
    lines += ["", "## 檢查項目", "", "| 檢查 | 結果 | 明細 |", "|---|---|---|"]
    for c in qa["checks"]:
        lines.append(f"| {c['check']} | {c['result']} | {c['detail']} |")
    lines += ["", "## 人工待辦", "",
              f"- 低文字頁：{qa['low_text_pages']}（須逐頁視覺判定）",
              f"- 未歸屬行：{qa['uncovered_lines']}（進 review_queue）",
              f"- 分頁小工具造成無法逐條切分：{qa['unsegmented_article_reports']} 部法規（見 review_queue "
              "issue_type=toc_widget_merged_articles，內容未遺失但條號粒度不足）",
              "",
              "> 解析輸出不等於已核對正確；11 部法規條號、101 件關鍵標籤（案件類型／主文結果為規則式，"
              "review_status=unreviewed）仍需人工回到 PDF 核對，才能作為 gold 或硬過濾條件。",
              "> 引用解析僅對照本 release 內的法規條文；庫外來源、判解／函釋間引用一律 unresolved，"
              "不代表資料錯誤。"]
    with open(os.path.join(rel_dir, "qa_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------- splits（評估分組，§7.1）----------------

def do_splits(release_id: str, eval_version: str):
    """依 case_family_id 分 dev／holdout（seed 42，約 80/20，盡量按 case_type
    分層）。只產出 splits.json；dev/holdout 的 synthetic inputs/gold 需要人工
    逐案確認說話者與可知性（§7.2），本次未產生，明列於 splits.json 與報告，
    不假裝已完成。"""
    rel_dir = _release_dir(release_id)

    def load(name):
        path = os.path.join(rel_dir, name)
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    documents = load("documents.jsonl")
    annotations = {a["document_id"]: a for a in load("annotations.jsonl")}

    decisions = [d for d in documents if d["document_type"] == "decision"]
    with_family = [d for d in decisions if d["case_family_id"]]
    without_family = [d for d in decisions if not d["case_family_id"]]

    family_to_docs: dict[str, list[str]] = defaultdict(list)
    family_case_type: dict[str, str] = {}
    for d in with_family:
        fam = d["case_family_id"]
        family_to_docs[fam].append(d["document_id"])
        ann = annotations.get(d["document_id"])
        ct = None
        if ann:
            ct = ann["fields"].get("case_type", {}).get("value")
        family_case_type.setdefault(fam, ct or "unknown")

    strata: dict[str, list[str]] = defaultdict(list)
    for fam, ct in family_case_type.items():
        strata[ct].append(fam)

    dev_families: list[str] = []
    holdout_families: list[str] = []
    per_stratum_report = {}
    for ct, fams in strata.items():
        fams_sorted = sorted(fams)
        rng = random.Random(EVAL_SEED)
        rng.shuffle(fams_sorted)
        n_dev = round(len(fams_sorted) * EVAL_DEV_RATIO)
        dev = sorted(fams_sorted[:n_dev])
        holdout = sorted(fams_sorted[n_dev:])
        dev_families.extend(dev)
        holdout_families.extend(holdout)
        per_stratum_report[ct] = {"n_families": len(fams_sorted), "dev": len(dev), "holdout": len(holdout)}

    splits = {
        "eval_split_version": EVAL_SPLIT_VERSION,
        "case_family_version": CASE_FAMILY_VERSION,
        "source_release_id": release_id,
        "seed": EVAL_SEED,
        "dev_ratio_target": EVAL_DEV_RATIO,
        "algorithm": (
            "以 case_family_id 為分組單位；按 annotations.fields.case_type（規則式、"
            "unreviewed）分層，各層用固定 seed 42 洗牌後取前 ~80% 為 dev、其餘 holdout；"
            "以家族數為分母，四捨五入到整數家族。"
        ),
        "rationale": (
            "case_type 目前是規則式粗分類，尚未人工核對；分層只為避免單一類型集中在"
            "同一邊，不代表法律定性正確。無 case_family_id 的決定書（case_no 抽取失敗）"
            "排除於分組之外，另列 excluded。"
        ),
        "dev_family_ids": dev_families,
        "holdout_family_ids": holdout_families,
        "per_stratum": per_stratum_report,
        "excluded_no_family_document_ids": [d["document_id"] for d in without_family],
        "excluded_no_family_reason": "case_no 未能從正文抽取，無法安全分組，避免誤併家族",
        "regression_case_ids": [],
        "regression_note": "尚未有下游規則／模型引擎可指認『已用於設計規則』的案例，本次未指定 regression 案例。",
        "synthetic_inputs_status": "not_generated",
        "synthetic_inputs_note": (
            "依規格 §7.2，合成輸入需人工逐段確認申請人主張／原處分內容的說話者與"
            "決定前可知性；本次僅完成家族分組與洩漏隔離基礎，未生成 dev/holdout 的"
            "inputs.jsonl／gold.jsonl，不得視為已完成評估包。"
        ),
    }

    eval_dir = os.path.join(REPO_ROOT, "data", "evaluation", eval_version)
    os.makedirs(eval_dir, exist_ok=True)
    out_path = os.path.join(eval_dir, "splits.json")
    if os.path.exists(out_path):
        print(f"[FATAL] splits.json 已存在，拒絕覆寫：{_rel(out_path)}", file=sys.stderr)
        sys.exit(2)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(splits, f, ensure_ascii=False, indent=2)
    splits_hash = sha256_file(out_path)

    print(f"[splits] eval_version={eval_version} 產出於 {_rel(out_path)}")
    print(f"  dev_families={len(dev_families)} holdout_families={len(holdout_families)} "
          f"excluded_no_family={len(without_family)}")
    for ct, rep in per_stratum_report.items():
        print(f"  case_type={ct}: {rep}")
    print(f"  splits.json sha256={splits_hash}")
    return splits


# ---------------- CLI ----------------

def main():
    ap = argparse.ArgumentParser(description="官方 PDF 前處理管線")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("inventory", "process", "validate", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("--input", default="data")
        sp.add_argument("--release", default="r1")
    sp = sub.add_parser("splits")
    sp.add_argument("--release", default="r1")
    sp.add_argument("--eval-version", default="v1")

    args = ap.parse_args()
    if args.cmd == "inventory":
        corpus, excluded = do_inventory(args.input)
        print(f"corpus PDF 總數：{len(corpus)}")
        print(f"總頁數：{sum(e['page_count'] for e in corpus)}")
        cats = defaultdict(int)
        for e in corpus:
            cats[e["category"]] += 1
        for c, n in cats.items():
            print(f"  {c}: {n}")
        if excluded:
            print(f"排除（非官方四類語料，見 annotate.CORPUS_CATEGORIES）：{len(excluded)}")
            ex_cats = defaultdict(int)
            for e in excluded:
                ex_cats[e["category"]] += 1
            for c, n in ex_cats.items():
                print(f"  排除-{c}: {n}")
    elif args.cmd == "process":
        do_process(args.input, args.release)
    elif args.cmd == "validate":
        ok = do_validate(args.release)
        sys.exit(0 if ok else 1)
    elif args.cmd == "all":
        do_process(args.input, args.release)
        ok = do_validate(args.release)
        sys.exit(0 if ok else 1)
    elif args.cmd == "splits":
        do_splits(args.release, args.eval_version)


if __name__ == "__main__":
    main()
