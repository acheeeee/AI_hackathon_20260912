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

from .common import STATUTE_ALIASES, normalize_article_key, parse_roc_date

# 目錄 -> document_type；只有這 4 類是 141 份基準語料，其餘（例如進件文件
# 「訴願書予行政處分函-1」）一律視為非語料，見 run.py 的 CORPUS_CATEGORIES。
CATEGORY_TYPE = {
    "歷史訴願決定書": "decision",
    "相關法規": "statute",
    "行政函釋": "interpretation",
    "司法院釋字及行政判解": "precedent",
}
CORPUS_CATEGORIES = set(CATEGORY_TYPE.keys())

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


def extract_decision_fields(lines: list[dict], document_id: str,
                            sections: list[dict] | None = None,
                            full_text: str = "") -> dict:
    """從正文抽案號/發文字號/日期/訴願人/原處分機關（附 source_span），
    並附上規則式的案件類型與主文結果（outcome_parts）。這些欄位是規則抽取，
    review_status 一律 unreviewed，不是覆核後的 gold（見規格 §5 步驟 F）。"""
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

    # 主文結果（規則式，從 decision_main_text section 取文字比對關鍵詞）
    main_quote = ""
    if sections:
        main_quote = "\n".join(
            s["quote_text"] for s in sections if s["section_type"] == "decision_main_text"
        )
    fields["outcome_parts"] = extract_outcome_parts(main_quote)

    # 粗粒度案件類型（供分流／評估分桶參考）
    fields["case_type"] = guess_case_type(full_text)

    return fields


# ---- 日期欄位（date_raw/calendar/date_iso/date_precision）----
# ROC 日期解析邏輯統一在 common.parse_roc_date；此處只包裝為 fact 結構。


def make_date_fact(raw: str, source_spans: list[dict]) -> dict:
    parsed = parse_roc_date(raw)
    return {
        "value": parsed,
        "source_spans": source_spans,
        "confidence": 0.8 if parsed["date_precision"] == "day" else 0.5,
        "extraction_method": "rule",
        "review_status": "unreviewed",
    }


# ---- 決定書主文結果與案件類型（規則式，尚未逐案人工覆核）----
# 依《資料前處理與切分交接規格》§5 步驟 F：101 件關鍵標籤仍須從正文核對；
# 這裡先建立可用的規則抽取，review_status 一律 unreviewed，不得當 gold。
_OUTCOME_PATTERNS = [
    ("dismissed", re.compile(r"訴願駁回")),
    ("rejected_inadmissible", re.compile(r"訴願不受理")),
    ("original_disposition_revoked", re.compile(r"原處分.{0,6}撤銷")),
    ("original_disposition_modified", re.compile(r"原處分.{0,6}變更")),
    ("remanded", re.compile(r"發回|另為適法之處分")),
    ("partially_upheld", re.compile(r"部分.{0,4}(?:駁回|撤銷|不受理)")),
]


def extract_outcome_parts(main_text_quote: str) -> dict:
    """從主文段文字比對結果關鍵詞；可能多款併存，回傳陣列。找不到任何關鍵詞
    時 value 為 []，missing_reason 說明原因（非等於「駁回以外」）。"""
    if not main_text_quote or not main_text_quote.strip():
        return fact(missing_reason="no_explicit_section")
    hits = [key for key, rx in _OUTCOME_PATTERNS if rx.search(main_text_quote)]
    if not hits:
        return fact(missing_reason="ambiguous")
    return fact(hits, confidence=0.5, method="rule")


_CASE_TYPE_HINTS = [
    ("環境保護", re.compile(r"廢棄物清理法|空氣污染防制法|空氣汙染防制法|噪音管制法")),
    ("金融監理", re.compile(r"洗錢防制法|金融監督管理委員會")),
    ("建築管理", re.compile(r"建築法|違章建築|建築物")),
    ("交通裁罰", re.compile(r"道路交通管理處罰條例")),
]


def guess_case_type(full_text: str) -> dict:
    """從全文比對粗粒度案件類型（供分流／評估分桶參考，非法律定性）。
    多類別可能同時命中，僅取第一個命中者；未命中則缺值待確認。"""
    for label, rx in _CASE_TYPE_HINTS:
        if rx.search(full_text):
            return fact(label, confidence=0.4, method="rule")
    return fact(missing_reason="ambiguous")


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


# ---- 引用解析（庫內對照）----

def build_statute_article_index(sections: list[dict]) -> dict:
    """由本 release 的 statute_article sections 建立 (statute_name, article_key)
    -> section_id 索引，供 resolve_citations 對照。同名同條號若重複（不同法規
    版本文件重疊，本次未發生）優先保留先出現、且 article_status 非 deleted 者。"""
    index: dict[tuple[str, str], str] = {}
    for s in sections:
        if s["section_type"] != "statute_article":
            continue
        meta = s["metadata"]
        name = meta.get("statute_name")
        name_norm = STATUTE_ALIASES.get(name, name) if name else None
        key = (name_norm, meta.get("article_key"))
        if key[0] is None or key[1] is None:
            continue
        if key not in index or meta.get("article_status") == "deleted":
            # 非刪除條文優先；若目前已是非刪除版本則不覆蓋
            existing = index.get(key)
            if existing is None:
                index[key] = s["section_id"]
            elif meta.get("article_status") != "deleted":
                index[key] = s["section_id"]
    return index


def resolve_citations(citations: list[dict], statute_index: dict,
                      corpus_statute_names: set,
                      unsectioned_statute_names: set | None = None) -> list[dict]:
    """依庫內法規條文索引解析引用 target_id。找不到時保留 unresolved 並附
    unresolved_reason，不編造目標（依規格 §5 步驟 F：庫內沒有時填 unresolved）。

    `unsectioned_statute_names` 是本 release 內存在但因跳頁小工具改採章節
    退場機制、完全沒有 statute_article 可對照的法規名稱（見
    segment._segment_statute_unreliable_titles）。這些法規『在庫內』，只是
    這個 release 沒有逐條索引，不該和『根本不在 11 部法規庫內』的
    statute_not_in_corpus 混為一談，否則會誤導成庫外來源。"""
    unsectioned_statute_names = unsectioned_statute_names or set()
    out = []
    for c in citations:
        c = dict(c)
        if c["statute_name"] not in corpus_statute_names:
            c["resolved"] = "unresolved"
            c["unresolved_reason"] = "statute_not_in_corpus"
        elif c["statute_name"] in unsectioned_statute_names:
            c["resolved"] = "unresolved"
            c["unresolved_reason"] = "statute_unsectioned_in_this_release"
        elif c["article_key"] is None:
            c["resolved"] = "unresolved"
            c["unresolved_reason"] = "article_key_unparsed"
        else:
            target = statute_index.get((c["statute_name"], c["article_key"]))
            if target:
                c["target_id"] = target
                c["resolved"] = "resolved"
            else:
                c["resolved"] = "unresolved"
                c["unresolved_reason"] = "article_not_found_in_corpus_snapshot"
        out.append(c)
    return out


# ---- 法規版面日期（法規名稱／修正日期標籤行）----
_LAW_NAME_LINE = re.compile(r"^法規名稱[：:]\s*(.+)$")
_LAW_DATE_LINE = re.compile(r"^(制定日期|修正日期)[：:]\s*(.+)$")


def find_law_header(lines: list[dict]) -> dict:
    """在條文標題出現前的版頭找『法規名稱：』與『制定/修正日期：』標籤行。
    回傳 {name_idx, name, date_label_idx, date_label, date_raw}；找不到的鍵為 None。
    供 segment.segment_statute 取得 law 名稱與公布／修正日期；假條號標題的
    排除改用結構特徵（見 segment._filter_toc_widget_titles），不依賴此處
    的版頭位置。"""
    out = {"name_idx": None, "name": None, "date_label_idx": None,
           "date_label": None, "date_raw": None}
    for i, ln in enumerate(lines):
        text = ln["text"].strip()
        if out["name_idx"] is None:
            m = _LAW_NAME_LINE.match(text)
            if m:
                name = re.sub(r"\s*EN\s*$", "", m.group(1).strip())
                out["name_idx"] = i
                out["name"] = name
                continue
        if out["date_label_idx"] is None:
            m = _LAW_DATE_LINE.match(text)
            if m:
                out["date_label_idx"] = i
                out["date_label"] = m.group(1)
                out["date_raw"] = m.group(2).strip()
    return out
