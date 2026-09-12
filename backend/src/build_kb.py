"""
批次建庫：掃描官方資料夾所有 PDF -> 產出結構化 JSON 知識庫。
輸出：
  data/kb/decisions.json      歷史訴願決定書
  data/kb/statutes.json       法規（逐條）
  data/kb/interpretations.json 行政函釋
  data/kb/precedents.json     司法院釋字及行政判解
執行：python -m src.build_kb
"""
from __future__ import annotations
import os
import glob
import json
import sys

from . import parsers as P

# 官方資料根目錄（相對於 backend/ 的上一層）
DATA_ROOT = os.environ.get(
    "APPEALS_DATA_ROOT",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
)
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "kb")


def _pdfs(subdir: str) -> list[str]:
    root = os.path.join(DATA_ROOT, subdir)
    return sorted(glob.glob(os.path.join(root, "**", "*.pdf"), recursive=True))


def _dump(items, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = [it.model_dump() for it in items]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return len(data)


def build():
    os.makedirs(OUT_DIR, exist_ok=True)
    report = {}

    # 決定書
    decisions = []
    for p in _pdfs("歷史訴願決定書"):
        try:
            decisions.append(P.parse_decision(p))
        except Exception as e:
            print(f"[WARN] 決定書解析失敗 {os.path.basename(p)}: {e}", file=sys.stderr)
    report["decisions"] = _dump(decisions, os.path.join(OUT_DIR, "decisions.json"))

    # 法規（逐條）
    statutes = []
    for p in _pdfs("相關法規"):
        try:
            statutes.extend(P.parse_statute(p))
        except Exception as e:
            print(f"[WARN] 法規解析失敗 {os.path.basename(p)}: {e}", file=sys.stderr)
    report["statutes_articles"] = _dump(statutes, os.path.join(OUT_DIR, "statutes.json"))

    # 函釋
    interps = []
    for p in _pdfs("行政函釋"):
        try:
            interps.append(P.parse_interpretation(p))
        except Exception as e:
            print(f"[WARN] 函釋解析失敗 {os.path.basename(p)}: {e}", file=sys.stderr)
    report["interpretations"] = _dump(interps, os.path.join(OUT_DIR, "interpretations.json"))

    # 判解
    precs = []
    for p in _pdfs("司法院釋字及行政判解"):
        try:
            precs.append(P.parse_precedent(p))
        except Exception as e:
            print(f"[WARN] 判解解析失敗 {os.path.basename(p)}: {e}", file=sys.stderr)
    report["precedents"] = _dump(precs, os.path.join(OUT_DIR, "precedents.json"))

    print("=== 知識庫建置完成 ===")
    for k, v in report.items():
        print(f"  {k}: {v} 筆")
    print(f"  輸出目錄: {os.path.abspath(OUT_DIR)}")
    return report


if __name__ == "__main__":
    build()
