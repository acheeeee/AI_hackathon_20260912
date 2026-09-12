"""
階段二：智能法規推薦 + 從新從輕時效提示。

法規推薦策略（三路信號融合，解決純 BM25 對法條排序不準的問題）：
  A. 相似案例引用法條：從 top 相似歷史決定書實際引用的法條聚合加權
     （歷史承辦人的專業判斷是最強信號）
  B. BM25 檢索：對案情文字做法規全文檢索
  C. 母法優先：案件類型字串命中的法規（如『違反廢棄物清理法事件』→廢棄物清理法）
最終分數 = wA*A + wB*B + wC*C，並保證引用來源可回溯（zero hallucination）。

時效提示（行政罰法第5條 從新從輕）：
  比對行為時 vs 處分時，若期間內推薦法規曾修正 → 觸發提示。
"""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Optional

from .retrieval import HybridIndex
from .models import IncomingAppeal, StatuteRecommendation, TimelinessAlert

# 案件類型 -> 母法名稱 對照（用於母法優先）
CASE_TYPE_TO_STATUTE = [
    ("廢棄物清理法", "廢棄物清理法"),
    ("噪音管制法", "噪音管制法"),
    ("空氣污染防制法", "空氣污染防制法"),
    ("空氣汙染", "空氣污染防制法"),
    ("建築法", "建築法"),
    ("違章建築", "建築法"),
    ("洗錢防制法", "洗錢防制法"),
    ("政府資訊", "政府資訊公開法"),
    ("公寓大廈", "公寓大廈管理條例"),
    ("道路交通", "道路交通管理處罰條例"),
]

# 程序性法規：幾乎每案都引用（區辨力低），推薦時降權以免壓過實體法
_PROCEDURAL_STATUTES = {
    "訴願法", "行政程序法", "行政執行法",
    "行政院及各級行政機關訴願審議委員會審議規則",
}

# 從『廢棄物清理法 第 50、12、27 條』這類字串解析出 (法規名, [條號])
_STATUTE_LINE = re.compile(r"^(.+?法|.+?條例|.+?規則|.+?辦法)\s*第\s*([\d、,\s]+)\s*條")


def _parse_statute_line(line: str) -> list[tuple[str, int]]:
    m = _STATUTE_LINE.search(line.strip())
    if not m:
        return []
    name = m.group(1).strip()
    nums = re.findall(r"\d+", m.group(2))
    return [(name, int(n)) for n in nums]


def _guess_mother_statute(case_type: Optional[str]) -> Optional[str]:
    if not case_type:
        return None
    for kw, statute in CASE_TYPE_TO_STATUTE:
        if kw in case_type:
            return statute
    return None


class Stage2Recommender:
    def __init__(self):
        self.statutes = HybridIndex("statutes"); self.statutes.load()
        self.decisions = HybridIndex("decisions"); self.decisions.load()
        self.refs = HybridIndex("refs"); self.refs.load()
        # 建立法規查表：(法規名, 條號) -> doc
        self._statute_map = {}
        for d in self.statutes.docs:
            self._statute_map[(d["statute_name"], d.get("article_num"))] = d

    # ---------- 法規推薦 ----------
    def recommend_statutes(self, appeal: IncomingAppeal, top_k: int = 6,
                           w_case: float = 0.5, w_bm25: float = 0.3,
                           w_mother: float = 0.2) -> list[StatuteRecommendation]:
        query = " ".join(filter(None, [appeal.case_type, appeal.facts, appeal.claims, appeal.full_text[:500]]))

        # A. 相似案例引用法條加權
        case_scores: dict[tuple[str, int], float] = defaultdict(float)
        sims = self.decisions.search(query, top_k=5, alpha=0.6)
        for rank, s in enumerate(sims):
            weight = 1.0 / (1 + rank)  # 名次越前權重越高
            for line in s.get("related_statutes", []):
                for (name, num) in _parse_statute_line(line):
                    case_scores[(name, num)] += weight

        # B. BM25 法規檢索
        bm25_scores: dict[tuple[str, int], float] = {}
        for r in self.statutes.search(query, top_k=15):
            bm25_scores[(r["statute_name"], r.get("article_num"))] = r["_score"]

        # C. 母法優先
        mother = _guess_mother_statute(appeal.case_type)

        # 正規化 A
        maxA = max(case_scores.values()) if case_scores else 1.0

        # 匯總候選
        candidates: dict[tuple[str, int], float] = defaultdict(float)
        for key, v in case_scores.items():
            candidates[key] += w_case * (v / maxA)
        for key, v in bm25_scores.items():
            candidates[key] += w_bm25 * v
        if mother:
            for key in list(candidates.keys()):
                if key[0] == mother:
                    candidates[key] += w_mother

        # 程序法降權：訴願法、行政程序法等幾乎每案都引用，區辨力低，
        # 避免其（尤其訴願法第77條）灌水到推薦前列，壓過真正的實體法條。
        for key in list(candidates.keys()):
            if key[0] in _PROCEDURAL_STATUTES:
                candidates[key] *= 0.15

        # 產生結果（保證可回溯到知識庫；程序法降權，實體法優先）
        ranked = sorted(candidates.items(), key=lambda kv: -kv[1])
        out: list[StatuteRecommendation] = []
        seen = set()
        for (name, num), score in ranked:
            doc = self._statute_map.get((name, num))
            if not doc:
                continue  # 找不到原文則捨棄（避免幻覺）
            if (name, num) in seen:
                continue
            seen.add((name, num))
            out.append(StatuteRecommendation(
                doc_id=doc["doc_id"], statute_name=name, article_no=doc["article_no"],
                content=doc["content"], score=round(float(score), 4),
                source="statute", amend_date=doc.get("amend_date"),
            ))
            if len(out) >= top_k:
                break
        return out

    # ---------- 相關函釋/判解 ----------
    def recommend_refs(self, appeal: IncomingAppeal, top_k: int = 3) -> list[StatuteRecommendation]:
        query = " ".join(filter(None, [appeal.case_type, appeal.facts, appeal.claims]))
        out = []
        for r in self.refs.search(query, top_k=top_k, alpha=0.6):
            kind = r.get("_kind", "interpretation")
            # 內容：優先要旨，否則取內文摘要；清理雜訊空白
            raw = r.get("summary") or r.get("content") or ""
            body = re.sub(r"[\xa0\u3000]+", " ", raw)
            body = re.sub(r"\n{2,}", "\n", body).strip()
            out.append(StatuteRecommendation(
                doc_id=r["doc_id"],
                statute_name=r.get("issuing_authority") or r.get("court") or "",
                article_no=r.get("doc_no") or r.get("case_no") or "",
                content=body[:600],
                score=round(float(r["_score"]), 4),
                source=kind,
            ))
        return out

    # ---------- 從新從輕時效提示 ----------
    def timeliness_alert(self, appeal: IncomingAppeal,
                         recommended: list[StatuteRecommendation]) -> TimelinessAlert:
        b = appeal.behavior_date_roc
        d = appeal.disposition_date_roc

        if not b or not d:
            return TimelinessAlert(
                triggered=False,
                message="未能取得行為時或處分時之年度，無法自動比對新舊法。建議承辦人手動確認法規版本。",
                behavior_date_roc=b, disposition_date_roc=d,
            )

        # 比對推薦法規中，修正年度是否落在 [行為時, 處分時] 之間
        changed = []
        lo, hi = min(b, d), max(b, d)
        seen_names = set()
        for rec in recommended:
            if rec.source != "statute":
                continue
            doc = self._statute_map.get((rec.statute_name, None))
            # 取該法規任一條的修正年度
            amend_roc = None
            for (nm, _num), sd in self._statute_map.items():
                if nm == rec.statute_name:
                    amend_roc = sd.get("amend_date_roc")
                    break
            if amend_roc and lo < amend_roc <= hi and rec.statute_name not in seen_names:
                changed.append(f"{rec.statute_name}（修正於民國{amend_roc}年）")
                seen_names.add(rec.statute_name)

        if b != d and changed:
            msg = (
                f"⚠️ 從新從輕提示（行政罰法第5條）：本案行為時為民國{b}年、處分時為民國{d}年，"
                f"期間下列法規曾修正，須比較新舊法擇最有利於受處罰者適用：{'；'.join(changed)}。"
            )
            return TimelinessAlert(triggered=True, message=msg,
                                   behavior_date_roc=b, disposition_date_roc=d,
                                   changed_statutes=changed)
        elif b != d:
            msg = (
                f"行為時（民國{b}年）與處分時（民國{d}年）不同，惟目前推薦法規於該期間內"
                f"未偵測到修正。仍建議承辦人依行政罰法第5條確認有無新舊法適用問題。"
            )
            return TimelinessAlert(triggered=False, message=msg,
                                   behavior_date_roc=b, disposition_date_roc=d)
        else:
            return TimelinessAlert(
                triggered=False,
                message=f"行為時與處分時同為民國{b}年，無新舊法變更之從新從輕適用問題。",
                behavior_date_roc=b, disposition_date_roc=d)
