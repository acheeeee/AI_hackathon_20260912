"""
建立並快取混合索引（BM25 + Gemini 向量）。
索引集：
  statutes   法規逐條
  decisions  歷史決定書
  refs       函釋 + 判解（合併為「法律見解」檢索池）
執行：python -m src.build_index
向量快取存 data/index/，之後查詢不重算。
"""
from __future__ import annotations
import os
import json

from .retrieval import HybridIndex, INDEX_DIR

KB_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "kb")


def _load(name):
    with open(os.path.join(KB_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _statute_text(s: dict) -> str:
    return f"{s['statute_name']} {s['article_no']} {s['content']}"


def _decision_text(d: dict) -> str:
    # 用要旨+案件類型+相關法條+事實+理由摘要作為檢索文字
    parts = [
        d.get("case_type") or "",
        d.get("summary") or "",
        " ".join(d.get("related_statutes") or []),
        (d.get("facts") or "")[:800],
        (d.get("reasons") or "")[:800],
    ]
    return " ".join(p for p in parts if p)


def _ref_text(r: dict) -> str:
    return f"{r.get('issuing_authority') or r.get('court') or ''} {r.get('topic') or ''} {r.get('summary') or ''} {(r.get('content') or '')[:1200]}"


def build_all(use_vector: bool = True, only: list[str] | None = None,
              batch_size: int = 50, sleep_between: float = 3.0):
    os.makedirs(INDEX_DIR, exist_ok=True)

    def want(name: str) -> bool:
        return only is None or name in only

    # 讓 retrieval.build 使用指定的批次/節流
    import src.retrieval as R
    R._EMBED_BATCH = batch_size
    R._EMBED_SLEEP = sleep_between

    if want("decisions"):
        decisions = _load("decisions.json")
        HybridIndex("decisions").build(decisions, [_decision_text(d) for d in decisions], use_vector).save()
        print(f"  decisions: {len(decisions)} 筆 ✓")

    if want("refs"):
        interps = _load("interpretations.json")
        precs = _load("precedents.json")
        for it in interps:
            it["_kind"] = "interpretation"
        for pc in precs:
            pc["_kind"] = "precedent"
        refs = interps + precs
        HybridIndex("refs").build(refs, [_ref_text(r) for r in refs], use_vector).save()
        print(f"  refs(函釋+判解): {len(refs)} 筆 ✓")

    if want("statutes"):
        statutes = _load("statutes.json")
        HybridIndex("statutes").build(statutes, [_statute_text(s) for s in statutes], use_vector).save()
        print(f"  statutes: {len(statutes)} 筆 ✓")

    print("=== 索引建置完成 ===")
    print(f"  快取目錄: {os.path.abspath(INDEX_DIR)}")


if __name__ == "__main__":
    import sys
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    build_all(only=only)


if __name__ == "__main__":
    build_all()
