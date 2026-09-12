"""
前處理回歸測試（依規格 §8「必須隨工具交付的回歸測試」）。

執行：. .venv_pre/bin/activate && python -m tests.preprocess.test_regression
不依賴 pytest，可在乾淨環境（無 API key、斷網）執行。
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.preprocess.common import (  # noqa: E402
    cn_to_int, normalize_article_key, normalize_case_no, normalize_search_text,
)
from scripts.preprocess.annotate import make_date_fact  # noqa: E402

RELEASE_ID = "r2"

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES.append(f"{name}: {detail}")
    print(f"  [{status}] {name} {detail if not cond else ''}")


def test_article_key():
    check("阿拉伯條號", normalize_article_key("第 15 條") == "15")
    check("附加條號-半形", normalize_article_key("第 15-2 條") == "15-2")
    check("附加條號-第2-1條", normalize_article_key("第 2-1 條") == "2-1")
    check("中文條號", normalize_article_key("第十五條") == "15")
    check("中文附加條號", normalize_article_key("第十五條之二") == "15-2")
    check("內文非標題不誤判為 None-可接受", normalize_article_key("foo") is None)


def test_cn_to_int():
    for s, v in [("一", 1), ("十", 10), ("十五", 15), ("二十一", 21),
                 ("一百零八", 108), ("二百", 200)]:
        check(f"中文數字 {s}->{v}", cn_to_int(s) == v, f"got {cn_to_int(s)}")


def test_date_precision():
    d = make_date_fact("民國 114 年 3 月 17 日", [])["value"]
    check("日期-day 精度", d["date_precision"] == "day" and d["date_iso"] == "2025-03-17",
          f"got {d}")
    d2 = make_date_fact("民國 114 年", [])["value"]
    check("日期-只知年度不補月日", d2["date_precision"] == "year" and d2["date_iso"] is None,
          f"got {d2}")


def test_normalize_preserves_law_terms():
    # search_text 別名只在檢索層；否定詞/但書/金額/條號不得改動
    src = "但書不適用；罰鍰新臺幣１０萬元；第 15-2 條"
    out = normalize_search_text(src)
    check("正規化保留但書", "但書" in out)
    check("正規化保留條號", "第 15-2 條" in out)
    # 空氣汙染->污染 別名（檢索層）
    check("檢索層別名", normalize_search_text("空氣汙染防制法") == "空氣污染防制法")


def _load_release(rel):
    def load(name):
        with open(os.path.join(rel, name), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    return {
        "documents": load("documents.jsonl"),
        "pages": load("pages.jsonl"),
        "sections": load("sections.jsonl"),
        "chunks": load("chunks.jsonl"),
        "annotations": load("annotations.jsonl"),
        "citations": load("citations.jsonl"),
        "review_queue": load("review_queue.jsonl"),
        "excluded_non_corpus": load("excluded_non_corpus.jsonl"),
    }


def _rebuild(page_line, spans, quote_text) -> bool:
    parts = []
    for sp in spans:
        t = page_line.get((sp["document_id"], sp["page"], sp["line"]))
        if t is None:
            return False
        if sp["char_start"] < 0 or sp["char_end"] > len(t) or sp["char_start"] > sp["char_end"]:
            return False
        parts.append(t[sp["char_start"]:sp["char_end"]])
    return "\n".join(parts) == quote_text


def test_release_integrity():
    """release 產物存在，sections／chunks 的 quote 100% 可由 span 重建（全量，非抽查）。"""
    rel = os.path.join(REPO_ROOT, "data", "processed", "releases", RELEASE_ID)
    if not os.path.isdir(rel):
        check(f"release {RELEASE_ID} 存在", False, f"尚未產出 {RELEASE_ID}，先跑 process")
        return
    r = _load_release(rel)
    page_line = {}
    for p in r["pages"]:
        for ln in p["lines"]:
            page_line[(p["document_id"], p["page"], ln["line"])] = ln["text"]

    bad_secs = sum(1 for s in r["sections"] if not _rebuild(page_line, s["source_spans"], s["quote_text"]))
    check("sections quote 100% 可重建（全量）", bad_secs == 0, f"mismatch={bad_secs}/{len(r['sections'])}")

    bad_chunks = sum(1 for c in r["chunks"] if not _rebuild(page_line, c["source_spans"], c["quote_text"]))
    check("chunks quote 100% 可重建（全量）", bad_chunks == 0, f"mismatch={bad_chunks}/{len(r['chunks'])}")

    missing_cv = sum(1 for c in r["chunks"] if not c.get("chunking_version"))
    check("chunks 皆含 chunking_version", missing_cv == 0, f"missing={missing_cv}/{len(r['chunks'])}")

    # 附加條號獨立（第2-1條、第2條、第3條互不吞併）
    statute_secs = [s for s in r["sections"] if s["section_type"] == "statute_article"]
    keys_by_law = {}
    for s in statute_secs:
        keys_by_law.setdefault(s["metadata"].get("statute_name"), set()).add(s["metadata"].get("article_key"))
    waste_law_keys = keys_by_law.get("廢棄物清理法", set())
    check("第2-1條成獨立 section", "2-1" in waste_law_keys)
    check("第2-1條不吞併第2/3條", {"2", "2-1", "3"}.issubset(waste_law_keys),
          f"got={sorted(k for k in waste_law_keys if k in ('2','2-1','3'))}")

    return r


def test_no_empty_statute_articles(r):
    """迴歸：全國法規資料庫跳頁小工具假標題曾在 r1 造成大量空內容 statute_article
    （訴願法、行政程序法等），修正後不得再出現。"""
    empty = [s for s in r["sections"] if s["section_type"] == "statute_article"
             and len(s["quote_text"].strip()) < 3]
    check("無空內容 statute_article（跳頁小工具迴歸）", len(empty) == 0,
          f"empty={len(empty)} ids={[s['section_id'] for s in empty[:5]]}")


def test_non_corpus_exclusion(r):
    """12 份進件文件（訴願書予行政處分函-1）不得混入 141 份基準語料。"""
    check("進件文件已排除、不進 documents", len(r["excluded_non_corpus"]) == 12,
          f"excluded={len(r['excluded_non_corpus'])}")
    corpus_paths = {d["source_file"] for d in r["documents"]}
    leaked = [e for e in r["excluded_non_corpus"] if e["source_file"] in corpus_paths]
    check("排除清單與語料互斥", len(leaked) == 0, f"leaked={len(leaked)}")


def test_case_family_isolation(r):
    """101 件決定書應各自取得 case_family_id，且不同案號不共用家族（避免評估
    洩漏時把不同案件誤併，也避免同案因抽取失敗而拆成兩個家族）。"""
    decisions = [d for d in r["documents"] if d["document_type"] == "decision"]
    families = [d["case_family_id"] for d in decisions]
    check("決定書皆有 case_family_id", all(f is not None for f in families),
          f"missing={sum(1 for f in families if f is None)}/{len(families)}")
    check("101 件決定書對應 101 個相異家族", len(set(families)) == len(decisions) == 101,
          f"families={len(set(families))} decisions={len(decisions)}")

    ann_by_doc = {a["document_id"]: a for a in r["annotations"]}
    case_no_a = ann_by_doc[decisions[0]["document_id"]]["fields"]["case_no"]["value"]
    check("案號正規化非空（樣本）", normalize_case_no(case_no_a) is not None if case_no_a else True)


def test_citation_resolution(r):
    """庫內法規引用應能解析到實際 section_id；庫外或未在庫內的條號保留
    unresolved 並附理由，不編造 target。"""
    resolved = [c for c in r["citations"] if c["resolved"] == "resolved"]
    check("至少部分庫內引用已解析", len(resolved) > 0, f"resolved={len(resolved)}/{len(r['citations'])}")
    sec_ids = {s["section_id"] for s in r["sections"]}
    bad_targets = [c for c in resolved if c["target_id"] not in sec_ids]
    check("已解析引用的 target_id 皆存在於 sections", len(bad_targets) == 0, f"bad={len(bad_targets)}")
    unresolved = [c for c in r["citations"] if c["resolved"] != "resolved"]
    no_reason = [c for c in unresolved if not c.get("unresolved_reason")]
    check("unresolved 引用皆附理由", len(no_reason) == 0, f"missing_reason={len(no_reason)}")


def test_toc_widget_review_queue(r):
    """全國法規資料庫跳頁小工具造成的未切分條號要進 review_queue 明示，
    不能悄悄漏記；同一份文件同一原因只記一次，不灌水成幾十筆重複項目。"""
    items = [x for x in r["review_queue"] if x["issue_type"] == "toc_widget_merged_articles"]
    check("跳頁小工具缺口已進 review_queue", len(items) >= 1, f"n={len(items)}")
    by_doc = {}
    for x in items:
        by_doc.setdefault(x["document_id"], 0)
        by_doc[x["document_id"]] += 1
    check("同份文件的整體性缺口不灌水重複", all(n <= 2 for n in by_doc.values()), f"per_doc={by_doc}")


def test_unreliable_titles_fallback(r):
    """條號標題整體不可信（見 segment._segment_statute_unreliable_titles）時，
    改用章／節切分仍要保留全文、非空內容，不能因退場機制而遺失資料。"""
    fallback_secs = [s for s in r["sections"] if s["section_type"] == "statute_unsectioned"]
    check("退場章節切分有產出", len(fallback_secs) >= 1, f"n={len(fallback_secs)}")
    empty = [s for s in fallback_secs if len(s["quote_text"].strip()) < 3]
    check("退場章節切分內容非空", len(empty) == 0, f"empty={len(empty)}")


def main():
    print("== 前處理回歸測試 ==")
    test_article_key()
    test_cn_to_int()
    test_date_precision()
    test_normalize_preserves_law_terms()
    r = test_release_integrity()
    if r is not None:
        test_no_empty_statute_articles(r)
        test_non_corpus_exclusion(r)
        test_case_family_isolation(r)
        test_citation_resolution(r)
        test_toc_widget_review_queue(r)
        test_unreliable_titles_fallback(r)
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}")
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
