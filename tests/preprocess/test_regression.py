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
    cn_to_int, normalize_article_key, normalize_search_text,
)
from scripts.preprocess.annotate import make_date_fact  # noqa: E402

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


def test_release_integrity():
    """release 產物存在且 quote 可由 span 100% 重建（抽查）。"""
    rel = os.path.join(REPO_ROOT, "data", "processed", "releases", "r1")
    if not os.path.isdir(rel):
        check("release 存在", False, "尚未產出 r1，先跑 process")
        return
    secs = [json.loads(l) for l in open(os.path.join(rel, "sections.jsonl"), encoding="utf-8")]
    pages = [json.loads(l) for l in open(os.path.join(rel, "pages.jsonl"), encoding="utf-8")]
    page_line = {}
    for p in pages:
        for ln in p["lines"]:
            page_line[(p["document_id"], p["page"], ln["line"])] = ln["text"]
    bad = 0
    for s in secs[:500]:
        rebuilt = []
        for sp in s["source_spans"]:
            t = page_line.get((sp["document_id"], sp["page"], sp["line"]))
            if t is None:
                bad += 1
                break
            rebuilt.append(t[sp["char_start"]:sp["char_end"]])
        else:
            if "\n".join(rebuilt) != s["quote_text"]:
                bad += 1
    check("抽查 500 段 quote 可重建", bad == 0, f"mismatch={bad}")

    # 附加條號獨立
    waste = [s for s in secs if s["section_type"] == "statute_article"
             and str(s["metadata"].get("article_key")) == "2-1"]
    check("第2-1條成獨立 section", len(waste) >= 1)


def main():
    print("== 前處理回歸測試 ==")
    test_article_key()
    test_cn_to_int()
    test_date_precision()
    test_normalize_preserves_law_terms()
    test_release_integrity()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}")
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
