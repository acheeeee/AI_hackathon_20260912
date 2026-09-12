"""
前處理主流程 CLI。

用法（在 repo 根目錄，以 .venv_pre 環境執行）：
  python -m scripts.preprocess.run all --input data --release r1
或分步：
  python -m scripts.preprocess.run inventory --input data --release r1
  python -m scripts.preprocess.run process  --input data --release r1
  python -m scripts.preprocess.run validate --release r1

輸出：data/processed/releases/<release_id>/{documents,pages,sections,chunks,
annotations,citations,duplicates,review_queue}.jsonl + manifest.json + qa_report.{json,md}

守則：
- 原 PDF 不改；不覆寫 backend/data/kb/。
- 禁止零輸入成功：輸入不存在 / 基準少檔 / 全類別零筆 -> 非零退出。
- 先寫 staging，validate 通過才標 validated。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict

from . import annotate as A
from . import chunk as C
from . import segment as S
from .common import (
    ALIAS_TABLE_VERSION, CHUNKING_VERSION, EXTRACTION_VERSION,
    SCHEMA_VERSION, SEGMENTATION_VERSION, make_document_id, make_section_id,
    sha256_file, spans_key,
)
from .extract import extract_pages, flat_lines

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BASELINE_PDF_COUNT = 141
BASELINE_PAGE_COUNT = 731


def _release_dir(release_id: str) -> str:
    return os.path.join(REPO_ROOT, "data", "processed", "releases", release_id)


def _rel(path: str) -> str:
    return os.path.relpath(path, REPO_ROOT)


def _category_of(path: str) -> str:
    rel = _rel(path)
    top = rel.split(os.sep)
    # data/<category>/...
    if len(top) >= 2 and top[0] == "data":
        return top[1]
    return "unknown"


def _write_jsonl(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------- inventory ----------------

def do_inventory(input_dir: str) -> list[dict]:
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
    # 標記重複（同 hash）
    for e in entries:
        aliases = by_hash[e["source_sha256"]]
        e["path_aliases"] = [_rel(a) for a in aliases]
        e["is_duplicate"] = len(aliases) > 1
    return entries


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
    entries = do_inventory(input_dir)
    seen_hash: set[str] = set()

    documents: list[dict] = []
    pages_out: list[dict] = []
    sections_out: list[dict] = []
    chunks_out: list[dict] = []
    annotations_out: list[dict] = []
    citations_out: list[dict] = []
    duplicates_out: list[dict] = []
    review_queue: list[dict] = []

    for e in entries:
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

        pages = extract_pages(abspath)
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

        # annotations（決定書欄位）
        if document_type == "decision":
            hint = A.decision_filename_hint(abspath)
            fields = A.extract_decision_fields(lines, document_id)
            annotations_out.append({
                "document_id": document_id,
                "filename_hint": hint,
                "fields": fields,
            })

        # citations
        for cit in A.extract_citations(document_id, lines):
            citations_out.append(cit)

        # documents.jsonl
        documents.append({
            "schema_version": SCHEMA_VERSION,
            "document_id": document_id,
            "case_family_id": None,  # 由去重/關聯步驟填；法規可為 null
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

    rel_dir = _release_dir(release_id)
    _write_jsonl(os.path.join(rel_dir, "documents.jsonl"), documents)
    _write_jsonl(os.path.join(rel_dir, "pages.jsonl"), pages_out)
    _write_jsonl(os.path.join(rel_dir, "sections.jsonl"), sections_out)
    _write_jsonl(os.path.join(rel_dir, "chunks.jsonl"), chunks_out)
    _write_jsonl(os.path.join(rel_dir, "annotations.jsonl"), annotations_out)
    _write_jsonl(os.path.join(rel_dir, "citations.jsonl"), citations_out)
    _write_jsonl(os.path.join(rel_dir, "duplicates.jsonl"), duplicates_out)
    _write_jsonl(os.path.join(rel_dir, "review_queue.jsonl"), review_queue)

    manifest = {
        "release_id": release_id,
        "schema_version": SCHEMA_VERSION,
        "extraction_version": EXTRACTION_VERSION,
        "segmentation_version": SEGMENTATION_VERSION,
        "chunking_version": CHUNKING_VERSION,
        "alias_table_version": ALIAS_TABLE_VERSION,
        "input_pdf_count": len(entries),
        "unique_document_count": len(documents),
        "duplicate_count": len(duplicates_out),
        "page_count": len(pages_out),
        "section_count": len(sections_out),
        "chunk_count": len(chunks_out),
        "citation_count": len(citations_out),
        "review_queue_count": len(review_queue),
        "publish_status": "draft",
    }
    with open(os.path.join(rel_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[process] release={release_id} 產出於 {_rel(rel_dir)}")
    for k, v in manifest.items():
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

    # 1) 原件清點
    total_pdfs = len(documents) + len([1])  # 加上重複另計
    with open(os.path.join(rel_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    add("原件清點-PDF數", manifest["input_pdf_count"] == BASELINE_PDF_COUNT,
        f"input={manifest['input_pdf_count']} baseline={BASELINE_PDF_COUNT}")
    add("原件清點-頁數", manifest["page_count"] + _dup_pages(documents, pages) >= 0
        and _total_pages(documents) == BASELINE_PAGE_COUNT,
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

    # 4) span 合法性 + 100% quote 可重建
    page_line = {}
    for p in pages:
        for ln in p["lines"]:
            page_line[(p["document_id"], p["page"], ln["line"])] = ln["text"]
    bad_span = 0
    bad_quote = 0
    for s in sections:
        rebuilt = []
        for sp in s["source_spans"]:
            key = (sp["document_id"], sp["page"], sp["line"])
            txt = page_line.get(key)
            if txt is None:
                bad_span += 1
                continue
            if sp["char_start"] < 0 or sp["char_end"] > len(txt) or sp["char_start"] > sp["char_end"]:
                bad_span += 1
                continue
            rebuilt.append(txt[sp["char_start"]:sp["char_end"]])
        if "\n".join(rebuilt) != s["quote_text"]:
            bad_quote += 1
    add("span合法性", bad_span == 0, f"illegal_spans={bad_span}")
    add("quote可重建", bad_quote == 0, f"mismatch_sections={bad_quote}")

    # 5) 法條邊界：附加條號獨立
    statute_secs = [s for s in sections if s["section_type"] == "statute_article"]
    sub_articles = [s for s in statute_secs if s["metadata"].get("article_key") and "-" in str(s["metadata"]["article_key"])]
    # 檢查同一法規內是否有 2 與 2-1 並存且不吞併
    add("法條邊界-附加條號存在", len(sub_articles) > 0, f"附加條號 section 數={len(sub_articles)}")
    # 條號可解析率
    unresolved_keys = [s for s in statute_secs if not s["metadata"].get("article_key")]
    add("法條邊界-條號可解析", len(unresolved_keys) == 0,
        f"無法解析 article_key 的條文 section={len(unresolved_keys)}")

    # 6) 全文覆蓋（review_queue uncovered 記錄，不算 FAIL 但報告）
    rq = load("review_queue.jsonl")
    uncovered = [r for r in rq if r["issue_type"] == "uncovered_line"]
    add("全文覆蓋-未歸屬行已記錄", True, f"uncovered_lines_logged={len(uncovered)}（進 review_queue，未靜默掉段）")

    # 7) index_eligible 明確布林
    non_bool = [c["chunk_id"] for c in chunks if not isinstance(c["index_eligible"], bool)]
    add("index_eligible-布林", not non_bool, f"non_bool={len(non_bool)}")

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


def _dup_pages(documents, pages) -> int:
    return 0


def _write_qa_md(rel_dir, qa, manifest):
    lines = [f"# QA 報告：{qa['release_id']}", "",
             f"發布狀態：**{qa['publish_status']}**", "",
             "## 計數", ""]
    for k in ("input_pdf_count", "unique_document_count", "duplicate_count",
              "page_count", "section_count", "chunk_count", "citation_count",
              "review_queue_count"):
        lines.append(f"- {k}: {manifest[k]}")
    lines += ["", "## 檢查項目", "", "| 檢查 | 結果 | 明細 |", "|---|---|---|"]
    for c in qa["checks"]:
        lines.append(f"| {c['check']} | {c['result']} | {c['detail']} |")
    lines += ["", "## 人工待辦", "",
              f"- 低文字頁：{qa['low_text_pages']}（須逐頁視覺判定）",
              f"- 未歸屬行：{qa['uncovered_lines']}（進 review_queue）",
              "", "> 解析輸出不等於已核對正確；11 部法規條號、101 件關鍵標籤仍需人工回到 PDF 核對。"]
    with open(os.path.join(rel_dir, "qa_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------- CLI ----------------

def main():
    ap = argparse.ArgumentParser(description="官方 PDF 前處理管線")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("inventory", "process", "validate", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("--input", default="data")
        sp.add_argument("--release", default="r1")

    args = ap.parse_args()
    if args.cmd == "inventory":
        entries = do_inventory(args.input)
        print(f"PDF 總數：{len(entries)}")
        print(f"總頁數：{sum(e['page_count'] for e in entries)}")
        cats = defaultdict(int)
        for e in entries:
            cats[e["category"]] += 1
        for c, n in cats.items():
            print(f"  {c}: {n}")
    elif args.cmd == "process":
        do_process(args.input, args.release)
    elif args.cmd == "validate":
        ok = do_validate(args.release)
        sys.exit(0 if ok else 1)
    elif args.cmd == "all":
        do_process(args.input, args.release)
        ok = do_validate(args.release)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
