"""
端到端檢索 Demo（命令列版）
模擬承辦人輸入一份新訴願書的核心情節，展示：
  1. 適用法規推薦（statutes, BM25）
  2. 相似歷史案例（decisions, BM25+向量）
  3. 相關函釋/判解（refs, BM25+向量）
執行：python -m src.demo_retrieval
"""
from __future__ import annotations
import sys
from src.retrieval import HybridIndex


DEMO_QUERY = (
    "訴願人駕駛車輛於路旁隨地棄置資源垃圾（保麗龍），未依規定時間及"
    "指定清運方式交付回收清除，經環保局依廢棄物清理法裁處罰鍰，"
    "訴願人主張照片無法證明垃圾為其所丟棄。"
)


def _line(c="-", n=70):
    print(c * n)


def main(query: str = DEMO_QUERY):
    _line("=")
    print("【新進訴願書 核心情節】")
    print(query)
    _line("=")

    # 1. 適用法規
    si = HybridIndex("statutes")
    if not si.load():
        print("statutes 索引未建立，請先執行 build_index"); return
    print("\n▎1. 適用法規推薦（前 5 條）")
    _line()
    for r in si.search(query, top_k=5):
        print(f"  [{r['_score']:.3f}] {r['statute_name']} {r['article_no']}")
        print(f"        {r['content'][:50].strip()}...")

    # 2. 相似案例
    di = HybridIndex("decisions")
    di.load()
    has_vec = "向量+BM25" if di.embeddings is not None else "純BM25"
    print(f"\n▎2. 相似歷史案例（前 5 名，{has_vec}）")
    _line()
    for i, r in enumerate(di.search(query, top_k=5, alpha=0.6), 1):
        print(f"  {i}. [{r['_score']:.3f}] {r.get('year')}年第{r.get('seq')}號 "
              f"| {r.get('case_type')} | 結果：{r.get('result')}")
        if r.get("related_statutes"):
            print(f"        引用法條：{'; '.join(r['related_statutes'][:3])}")

    # 3. 函釋/判解
    ri = HybridIndex("refs")
    ri.load()
    has_vec = "向量+BM25" if ri.embeddings is not None else "純BM25"
    print(f"\n▎3. 相關函釋 / 判解（前 3 名，{has_vec}）")
    _line()
    for i, r in enumerate(ri.search(query, top_k=3, alpha=0.6), 1):
        kind = "函釋" if r.get("_kind") == "interpretation" else "判解"
        print(f"  {i}. [{r['_score']:.3f}] [{kind}] {r.get('doc_id','')[:50]}")

    _line("=")
    print("Demo 完成。以上檢索全部本地執行（法規BM25 / 決定書+判解向量快取）。")


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else DEMO_QUERY
    main(q)
