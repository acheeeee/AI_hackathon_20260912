"""
步驟 D/F：文件分類、檔名提示、欄位標註與引用抽取。

規則（依規格 §5 步驟 F、§6）：
- document_type 由官方分類目錄提供初值，再以正文檢查 subtype。
- 檔名值只作 filename_hint / 交叉檢查，不當黃金標籤。
- 每個抽取事實包裝 value/source_spans/confidence/extraction_method/review_status/missing_reason。
- 日期同時保存 date_raw / calendar / date_iso / date_precision；只知年度不補月日。
- 引用保存 citation_raw / 正規化 / resolved 狀態；無法可靠解析保留原文列待確認。
"""
from __future__ import annotations

import os
import re
from typing import Optional

from .common import STATUTE_ALIASES, normalize_article_key

# 目錄 -> document_type
CATEGORY_TYPE = {
    "歷史訴願決定書": "decision",
    "相關法規": "statute",
    "行政函釋": "interpretation",
    "司法院釋字及行政判解": "precedent",
}

KNOWN_STATUTES = [
    "廢棄物清理法", "噪音管制法", "空氣污染防制法", "空氣汙染防制法", "建築法",
    "洗錢防制法", "行政罰法", "行政程序法", "行政執行法", "訴願法", "民法",
    "政府資訊公開法", "公寓大廈管理條例", "道路交通管理處罰條例",
    "停車場法", "毒品危害防制條例",
]


def classify_subtype(document_type: str, filename: str, full_text: str) -> Optional[str]:
    """以檔名與正文判定 document_subtype（釋字 vs 行政判決同資料夾需區分）。"""
    name = os.path.basename(filename)
    if document_type == "precedent":
        if "釋字" in name or "解釋" in name[:20]:
            return "interpretation_constitutional"  # 釋字解釋
        if "裁定" in name:
            return "ruling"
        if "判決" in name:
            return "judgment"
        return None
    if document_type == "interpretation":
        return "administrative_letter"
    return None


def clean_filename(path: str) -> str:
    name = os.path.basename(path)
    name = re.sub(r"\.pdf( 的副本)?\.pdf$", "", name)
    name = re.sub(r"\.pdf$", "", name)
    return name


def decision_filename_hint(path: str) -> dict:
    """由檔名取提示值（僅 filename_hint，不當黃金標籤）。"""
    name = clean_filename(path)
    out: dict = {"raw": name}
    parts = name.split("-")
    if parts:
        m = re.match(r"(\d+)\.(\d+)年", parts[0])
        if m:
            out["seq"] = int(m.group(1))
            out["year_roc"] = int(m.group(2))
    if len(parts) >= 2:
        out["case_type"] = parts[1].strip()
    if len(parts) >= 3:
        out["procedural_basis"] = parts[2].strip()
    if len(parts) >= 2:
        out["result"] = parts[-1].strip()
    return out


# ---- 事實欄位包裝 ----

def fact(value=None, source_spans=None, confidence: float = 0.0,
         method: str = "rule", review: str = "unreviewed",
         missing_reason: Optional[str] = None) -> dict:
    """依規格 §5 步驟 F 的抽取事實結構。"""
    d = {
        "value": value,
        "source_spans": source_spans or [],
        "confidence": confidence,
        "extraction_method": method,
        "review_status": review,
    }
    if value is None and missing_reason is not None:
        d["missing_reason"] = missing_reason
    return d


# ---- 決定書正文欄位（從內文核對，附來源）----

def find_line(lines: list[dict], pattern: str):
    """回傳第一個符合 pattern 的 (idx, match, line)。"""
    rx = re.compile(pattern)
    for i, ln in enumerate(lines):
        m = rx.search(ln["text"])
        if m:
            return i, m, ln
    return None


def extract_decision_fields(lines: list[dict], document_id: str) -> dict:
    """從正文抽案號/發文字號/日期/訴願人/原處分機關（附 source_span）。"""
    from .extract import full_line_span
    fields: dict = {}

    def span_of(ln):
        return [full_line_span(document_id, ln["page"], ln)]

    # 案號
    hit = find_line(lines, r"案\s*號[：:]\s*(\S+)")
    if hit:
        i, m, ln = hit
        fields["case_no"] = fact(m.group(1), span_of(ln), 0.8)
    else:
        fields["case_no"] = fact(missing_reason="not_stated")

    # 發文字號
    hit = find_line(lines, r"發文字號[：:]\s*(\S+)")
    fields["doc_no"] = fact(hit[1].group(1), span_of(hit[2]), 0.8) if hit else fact(missing_reason="not_stated")

    # 發文日期（原文字串）
    hit = find_line(lines, r"發文日期[：:]\s*(.+)")
    if hit:
        raw = hit[1].group(1).strip()
        fields["decision_date"] = make_date_fact(raw, span_of(hit[2]))
    else:
        fields["decision_date"] = fact(missing_reason="not_stated")

    # 訴願人
    hit = find_line(lines, r"訴願人[：\s]+([^\s，,、]+)")
    fields["appellant"] = fact(hit[1].group(1), span_of(hit[2]), 0.6) if hit else fact(missing_reason="not_stated")

    # 原處分機關
    hit = find_line(lines, r"原處分機關[：\s]+([^\s，,、]+)")
    fields["original_authority"] = fact(hit[1].group(1), span_of(hit[2]), 0.6) if hit else fact(missing_reason="not_stated")

    return fields


# ---- 日期欄位（date_raw/calendar/date_iso/date_precision）----
_ROC_FULL = re.compile(r"民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日")
_ROC_YM = re.compile(r"民國\s*(\d+)\s*年\s*(\d+)\s*月")
_ROC_Y = re.compile(r"民國\s*(\d+)\s*年")


def make_date_fact(raw: str, source_spans: list[dict]) -> dict:
    calendar = "roc"
    date_iso = None
    precision = "unknown"
    year = month = day = None
    m = _ROC_FULL.search(raw)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        precision = "day"
        date_iso = f"{year + 1911:04d}-{month:02d}-{day:02d}"
    elif _ROC_YM.search(raw):
        m = _ROC_YM.search(raw)
        year, month = int(m.group(1)), int(m.group(2))
        precision = "month"  # 只知年月不補日
    elif _ROC_Y.search(raw):
        year = int(_ROC_Y.search(raw).group(1))
        precision = "year"  # 只知年度不補月日
    return {
        "value": {
            "date_raw": raw,
            "calendar": calendar,
            "date_iso": date_iso,
            "date_precision": precision,
            "roc_year": year,
        },
        "source_spans": source_spans,
        "confidence": 0.8 if precision == "day" else 0.5,
        "extraction_method": "rule",
        "review_status": "unreviewed",
    }


# ---- 引用抽取 ----
# 法名 + 條號（含附加條號 / 中文條號）
_CITATION = re.compile(
    r"(" + "|".join(map(re.escape, KNOWN_STATUTES)) + r")"
    r"(?:第\s*(?:\d+(?:-\d+)?|[一二三四五六七八九十百千零]+(?:之[一二三四五六七八九十百千零]+)?)\s*條)"
)
_ARTICLE_ONLY = re.compile(
    r"第\s*(\d+(?:-\d+)?|[一二三四五六七八九十百千零]+(?:之[一二三四五六七八九十百千零]+)?)\s*條"
)


def extract_citations(document_id: str, lines: list[dict]) -> list[dict]:
    """抽取文件中的法條引用關係。resolved 狀態預設 unresolved（庫內解析另做）。"""
    from .extract import full_line_span
    out: list[dict] = []
    for ln in lines:
        text = ln["text"]
        for m in _CITATION.finditer(text):
            statute = m.group(1)
            statute_norm = STATUTE_ALIASES.get(statute, statute)
            am = _ARTICLE_ONLY.search(m.group(0))
            art_key = normalize_article_key(am.group(0)) if am else None
            out.append({
                "source_document_id": document_id,
                "citation_raw": m.group(0),
                "statute_name": statute_norm,
                "article_key": art_key,
                "target_id": None,
                "resolved": "unresolved",
                "source_spans": [full_line_span(document_id, ln["page"], ln)],
            })
    return out


def guess_related_statutes(text: str) -> list[str]:
    found = []
    for name in KNOWN_STATUTES:
        if name in text:
            norm = STATUTE_ALIASES.get(name, name)
            if norm not in found:
                found.append(norm)
    return found
