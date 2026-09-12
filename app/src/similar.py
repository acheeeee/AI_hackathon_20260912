"""
階段三：相似歷史案例比對（前 3-5 名）。

多維度相似度（非單一向量相似，提升專業度與可解釋性）：
  1. 語意相似 (semantic)：案情向量 cosine（額度不足時降級 BM25 分數）
  2. 案件類型 (case_type)：同類型案件加分
  3. 法條重疊 (statute_overlap)：引用法條的 Jaccard 相似度
  4. 母法一致：來自檢索池，隱含在語意/類型中

綜合相似度 = 加權平均，並回傳各維度明細供介面展示（可解釋）。
另提供 result_distribution：同類相似案件的結果統計，輔助承辦人判斷傾向。
"""
from __future__ import annotations
import re
from collections import Counter
from typing import Optional

from .retrieval import HybridIndex
from .models import IncomingAppeal, SimilarCase

_STATUTE_LINE = re.compile(r"(.+?法|.+?條例|.+?規則|.+?辦法)\s*第\s*([\d、,\s]+)\s*條")


def _statute_keys(related: list[str]) -> set[str]:
    """把 related_statutes 行拆成 {'廢棄物清理法-50', ...} 集合供重疊比對。"""
    keys = set()
    for line in related or []:
        m = _STATUTE_LINE.search(line)
        if not m:
            continue
        name = m.group(1).strip()
        for n in re.findall(r"\d+", m.group(2)):
            keys.add(f"{name}-{n}")
    return keys


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# 程序性法規：幾乎所有案件都會引用，比對時降權以免雜訊
_PROCEDURAL = ("訴願法", "行政程序法", "行政院及各級行政機關訴願審議委員會審議規則")


def _is_procedural(statute_key: str) -> bool:
    return any(statute_key.startswith(p + "-") for p in _PROCEDURAL)


def _weighted_statute_similarity(a: set, b: set,
                                 proc_weight: float = 0.2) -> tuple[float, set]:
    """
    以法條為主的加權相似度。
    - 實體法條（如廢清法、洗錢法）：權重 1.0（案件核心依據）
    - 程序法條（訴願法、行政程序法）：權重 proc_weight（幾乎每案都有，區辨力低）
    回傳 (相似度 0~1, 共同的實體法條集合供展示)。
    公式類似加權 Jaccard：sum(共同權重) / sum(聯集權重)。
    """
    if not a or not b:
        return 0.0, set()

    def w(k: str) -> float:
        return proc_weight if _is_procedural(k) else 1.0

    inter = a & b
    union = a | b
    inter_w = sum(w(k) for k in inter)
    union_w = sum(w(k) for k in union)
    sim = inter_w / union_w if union_w > 0 else 0.0
    shared_substantive = {k for k in inter if not _is_procedural(k)}
    return sim, shared_substantive


class Stage3SimilarCases:
    def __init__(self):
        self.decisions = HybridIndex("decisions")
        self.decisions.load()

    def find_similar(self, appeal: IncomingAppeal, top_k: int = 5,
                     w_statute: float = 0.6, w_type: float = 0.15,
                     w_sem: float = 0.25, candidate_pool: int = 40,
                     recommended_statutes: Optional[list] = None) -> list[SimilarCase]:
        """
        以「法條」為主的相似案例比對（符合法律實務：先看適用哪些法條）。
        召回：優先納入所有引用相同實體法條的歷史案件，再補語意候選。
        排序：法條重疊為主要權重(0.6)，案件類型(0.15)、事實語意(0.25)為輔。
        """
        query = " ".join(filter(None, [
            appeal.case_type, appeal.facts, appeal.claims, appeal.full_text[:500]
        ]))

        # 新案適用法條集合（優先用階段二推薦法條）
        appeal_statutes: set[str] = set()
        if recommended_statutes:
            for rec in recommended_statutes:
                num = re.search(r"\d+", getattr(rec, "article_no", "") or "")
                name = getattr(rec, "statute_name", "") or ""
                if name and num:
                    appeal_statutes.add(f"{name}-{num.group()}")
        if not appeal_statutes:
            appeal_statutes = _statute_keys([appeal.full_text])

        # 新案的實體法條（召回主依據）
        appeal_substantive = {k for k in appeal_statutes if not _is_procedural(k)}

        # ---------- 召回 ----------
        # (A) 法條召回：掃全部決定書，凡引用相同實體法條者納入候選
        docs = self.decisions.docs
        recalled_idx: set[int] = set()
        if appeal_substantive:
            for i, d in enumerate(docs):
                case_stat = _statute_keys(d.get("related_statutes", []))
                if appeal_substantive & {k for k in case_stat if not _is_procedural(k)}:
                    recalled_idx.add(i)
        # (B) 語意召回：補進事實相近但法條抽取可能遺漏的案件
        sem_scores: dict[int, float] = {}
        for r in self.decisions.search(query, top_k=candidate_pool, alpha=0.6):
            # 以 doc_id 對回索引
            for i, d in enumerate(docs):
                if str(d.get("doc_id")) == str(r.get("doc_id")):
                    sem_scores[i] = float(r.get("_score", 0.0))
                    recalled_idx.add(i)
                    break

        # ---------- 評分 ----------
        results: list[SimilarCase] = []
        for i in recalled_idx:
            d = docs[i]
            sem = sem_scores.get(i, 0.0)

            # 法條重疊（主維度，實體法加重、程序法降權）
            case_statutes = _statute_keys(d.get("related_statutes", []))
            statute_score, shared = _weighted_statute_similarity(appeal_statutes, case_statutes)

            # 案件類型
            type_score = 0.0
            if appeal.case_type and d.get("case_type"):
                if appeal.case_type == d["case_type"]:
                    type_score = 1.0
                elif _norm_type(appeal.case_type) == _norm_type(d["case_type"]):
                    type_score = 0.9
                elif _mother(appeal.case_type) and _mother(appeal.case_type) == _mother(d["case_type"]):
                    type_score = 0.6

            total = w_statute * statute_score + w_type * type_score + w_sem * sem
            results.append(SimilarCase(
                doc_id=str(d.get("doc_id")),
                source_file=d.get("source_file", ""),
                case_type=d.get("case_type"),
                result=d.get("result"),
                year=d.get("year"),
                summary=d.get("summary") or (d.get("facts") or "")[:120],
                related_statutes=d.get("related_statutes", []),
                shared_statutes=sorted(shared),
                similarity=round(float(total), 4),
                dimension_scores={
                    "法條重疊": round(statute_score, 3),
                    "案件類型": round(type_score, 3),
                    "事實語意": round(sem, 3),
                },
            ))

        results.sort(key=lambda s: -s.similarity)
        return results[:top_k]

    def result_distribution(self, similar: list[SimilarCase]) -> dict:
        """相似案件的結果分佈統計，輔助判斷傾向。"""
        c = Counter(s.result for s in similar if s.result)
        total = sum(c.values())
        dist = {k: {"count": v, "ratio": round(v / total, 2)} for k, v in c.most_common()} if total else {}
        return {"total": total, "distribution": dist}


# ---------- 案件類型正規化 ----------

def _norm_type(t: Optional[str]) -> str:
    if not t:
        return ""
    t = t.replace("違反", "").replace("事件", "")
    t = t.replace("空氣汙染", "空氣污染")
    return t.strip()


_MOTHER_KW = ["廢棄物清理法", "噪音管制法", "空氣污染防制法", "建築法", "洗錢防制法",
              "政府資訊", "公寓大廈", "道路交通"]


def _mother(t: Optional[str]) -> Optional[str]:
    if not t:
        return None
    t = t.replace("空氣汙染", "空氣污染")
    for kw in _MOTHER_KW:
        if kw in t:
            return kw
    return None
