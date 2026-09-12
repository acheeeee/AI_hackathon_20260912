"""
資料模型 (Pydantic v2)
定義四類知識庫實體與系統輸出結構：
- AppealDecision  歷史訴願決定書
- StatuteArticle  法規（逐條）
- Interpretation  行政函釋
- CourtPrecedent  司法院釋字及行政判解
以及檢索/推薦/相似案例的輸出結構。
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ---------- 知識庫實體 ----------

class AppealDecision(BaseModel):
    """歷史訴願決定書：每份 PDF 一筆。"""
    doc_id: str = Field(..., description="唯一識別，通常用案號或檔名")
    source_file: str = Field(..., description="來源 PDF 路徑")

    # 由檔名解析的 metadata（黃金標註）
    year: Optional[int] = Field(None, description="民國年度，如 113")
    seq: Optional[int] = Field(None, description="該年度內編號")
    case_type: Optional[str] = Field(None, description="案件類型，如『違反廢棄物清理法事件』")
    procedural_basis: Optional[str] = Field(None, description="程序依據訴願法條，如『79I』『77(8)』")
    result: Optional[str] = Field(None, description="結果，如『駁回』『撤銷另處』『不受理』")

    # 由內文解析的欄位
    case_no: Optional[str] = Field(None, description="案號，如 1131071415")
    doc_no: Optional[str] = Field(None, description="發文字號")
    doc_date: Optional[str] = Field(None, description="發文日期（原文字串）")
    summary: Optional[str] = Field(None, description="要旨")
    appellant: Optional[str] = Field(None, description="訴願人")
    original_authority: Optional[str] = Field(None, description="原處分機關")
    related_statutes: list[str] = Field(default_factory=list, description="相關法條原文行，如『廢棄物清理法 第 50、12 條』")

    # 三段內文
    main_text: Optional[str] = Field(None, description="主文")
    facts: Optional[str] = Field(None, description="事實")
    reasons: Optional[str] = Field(None, description="理由")
    full_text: str = Field(..., description="全文純文字")


class StatuteArticle(BaseModel):
    """法規逐條：每條一筆。"""
    doc_id: str = Field(..., description="法規名+條號，如『行政罰法-第5條』")
    statute_name: str = Field(..., description="法規名稱")
    amend_date: Optional[str] = Field(None, description="修正日期原文，如『民國 111 年 06 月 15 日』")
    amend_date_roc: Optional[int] = Field(None, description="修正年度（民國），用於時效比對，如 111")
    chapter: Optional[str] = Field(None, description="所屬章節")
    article_no: str = Field(..., description="條號，如『第 5 條』")
    article_num: Optional[int] = Field(None, description="條號數字，如 5")
    content: str = Field(..., description="條文內容")
    source_file: str = Field(...)


class Interpretation(BaseModel):
    """行政函釋。"""
    doc_id: str = Field(...)
    issuing_authority: Optional[str] = Field(None, description="發文機關")
    doc_no: Optional[str] = Field(None, description="發文字號")
    doc_date: Optional[str] = Field(None, description="發文日期")
    summary: Optional[str] = Field(None, description="要旨")
    content: str = Field(..., description="全文（主旨+說明）")
    related_statutes: list[str] = Field(default_factory=list, description="關聯法規名（由檔名/內文推斷）")
    source_file: str = Field(...)


class CourtPrecedent(BaseModel):
    """司法院釋字及行政判解。"""
    doc_id: str = Field(...)
    court: Optional[str] = Field(None, description="法院/機關")
    case_no: Optional[str] = Field(None, description="案號")
    topic: Optional[str] = Field(None, description="爭點主題，由檔名推斷")
    content: str = Field(..., description="全文")
    related_statutes: list[str] = Field(default_factory=list)
    source_file: str = Field(...)


# ---------- 新進件（待處理訴願書） ----------

class IncomingAppeal(BaseModel):
    """新上傳、待處理的訴願書解析結果（階段一的產出，階段二三的輸入）。"""
    source_file: Optional[str] = None
    case_type: Optional[str] = Field(None, description="推斷案件類型")
    appellant: Optional[str] = None
    original_authority: Optional[str] = None
    disposition_no: Optional[str] = Field(None, description="原處分書文號")
    facts: Optional[str] = Field(None, description="事實/違規情節")
    claims: Optional[str] = Field(None, description="訴願人主張/爭點")
    behavior_date_roc: Optional[int] = Field(None, description="行為時（民國年），用於從新從輕比對")
    disposition_date_roc: Optional[int] = Field(None, description="處分時（民國年），用於從新從輕比對")
    full_text: str = Field(..., description="全文")


# ---------- 系統輸出 ----------

class StatuteRecommendation(BaseModel):
    """階段二：單條法規推薦結果。"""
    doc_id: str
    statute_name: str
    article_no: str
    content: str
    score: float = Field(..., description="混合檢索分數")
    source: str = Field("statute", description="來源類型：statute / interpretation / precedent")
    amend_date: Optional[str] = None


class TimelinessAlert(BaseModel):
    """階段二：從新從輕（行政罰法第5條）時效提示。"""
    triggered: bool = Field(..., description="是否偵測到需比較新舊法")
    message: str = Field(..., description="給承辦人的提示文字")
    behavior_date_roc: Optional[int] = None
    disposition_date_roc: Optional[int] = None
    changed_statutes: list[str] = Field(default_factory=list, description="行為時與處分時之間有修正的法規")


class SimilarCase(BaseModel):
    """階段三：相似案例。"""
    doc_id: str
    source_file: str
    case_type: Optional[str] = None
    result: Optional[str] = None
    year: Optional[int] = None
    summary: Optional[str] = None
    related_statutes: list[str] = Field(default_factory=list)
    shared_statutes: list[str] = Field(default_factory=list, description="與新案共同的實體法條")
    similarity: float = Field(..., description="綜合相似度 0~1")
    dimension_scores: dict[str, float] = Field(default_factory=dict, description="各維度分數明細")
