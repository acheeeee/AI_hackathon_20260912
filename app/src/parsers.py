"""
PDF -> 結構化 JSON 解析器
四類文件：決定書、法規、函釋、判解。
所有 PDF 均為文字型（已驗證），使用 PyMuPDF 抽取。
"""
from __future__ import annotations
import re
import os
from typing import Optional

import fitz  # PyMuPDF

from .models import (
    AppealDecision, StatuteArticle, Interpretation, CourtPrecedent,
)

# 已知的實體法規名（供從檔名/內文推斷案件類型與關聯法規）
KNOWN_STATUTES = [
    "廢棄物清理法", "噪音管制法", "空氣污染防制法", "空氣汙染防制法", "建築法",
    "洗錢防制法", "行政罰法", "行政程序法", "行政執行法", "訴願法",
    "政府資訊公開法", "公寓大廈管理條例", "道路交通管理處罰條例", "民法",
    "都市更新", "停車場法", "毒品危害防制條例", "社會救助", "工廠登記",
]


def extract_text(pdf_path: str) -> tuple[str, int]:
    """抽取 PDF 全文與頁數。"""
    doc = fitz.open(pdf_path)
    text = "".join(page.get_text() for page in doc)
    n = doc.page_count
    doc.close()
    return text, n


def _clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.replace("\u3000", " ")  # 全形空白
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# ---------- 檔名解析（決定書 metadata 的黃金來源） ----------

def parse_decision_filename(filename: str) -> dict:
    """
    檔名格式範例：
    '17.113年-違反廢棄物清理法事件-79I-訴願無理由-駁回.pdf 的副本.pdf'
    '21.114年-違反建築法事件-77(8)&79I-部分不受理&部分駁回.pdf 的副本.pdf'
    以 '-' 切分：[序號.年度][案件類型][程序依據][(可選)描述...][結果]
    """
    name = os.path.basename(filename)
    name = re.sub(r"\.pdf( 的副本)?\.pdf$", "", name)  # 去副檔名與『的副本』
    name = re.sub(r"\.pdf$", "", name)

    out: dict = {}
    parts = name.split("-")

    # 第一段：序號.年度
    if parts:
        head = parts[0]
        m = re.match(r"(\d+)\.(\d+)年", head)
        if m:
            out["seq"] = int(m.group(1))
            out["year"] = int(m.group(2))

    if len(parts) >= 2:
        out["case_type"] = parts[1].strip()
    if len(parts) >= 3:
        out["procedural_basis"] = parts[2].strip()
    if len(parts) >= 2:
        out["result"] = parts[-1].strip()  # 最後一段為結果
    return out


# ---------- 決定書內文解析 ----------

def _field_after(text: str, label: str) -> Optional[str]:
    """抓『label：\n 值』或『label：值』的下一段（適用開頭 metadata 區）。"""
    pat = re.compile(re.escape(label) + r"[：:]\s*\n?\s*(.+?)(?:\n|$)")
    m = pat.search(text)
    return _clean(m.group(1)) if m else None


def _extract_related_statutes(text: str) -> list[str]:
    """抓開頭『相關法條：』區塊到『全 文：』之前的多行法條。"""
    m = re.search(r"相關法條[：:]\s*\n(.*?)\n\s*全\s*文", text, re.S)
    if not m:
        m = re.search(r"相關法條[：:]\s*\n(.*?)\n\s*全", text, re.S)
    if not m:
        return []
    block = m.group(1)
    lines = [_clean(x) for x in block.split("\n") if x.strip()]
    return [x for x in lines if x]


def _split_sections(text: str) -> dict:
    """
    切出 主文 / 事實 / 理由 三段。
    決定書內文分節標記為含全形空白的『主 文』『事 實』『理 由』。
    """
    # 正規化分節標題（去全形空白）便於定位
    def find(label_chars: str):
        # label_chars 例如 '主文'，允許中間有空白/全形空白
        pat = r"\n\s*" + r"\s*".join(list(label_chars)) + r"\s*\n"
        return re.search(pat, text)

    markers = {}
    for key, ch in [("main_text", "主文"), ("facts", "事實"), ("reasons", "理由")]:
        m = find(ch)
        if m:
            markers[key] = (m.start(), m.end())

    out = {"main_text": None, "facts": None, "reasons": None}
    order = sorted(markers.items(), key=lambda kv: kv[1][0])
    for i, (key, (s, e)) in enumerate(order):
        end = order[i + 1][1][0] if i + 1 < len(order) else len(text)
        out[key] = _clean(text[e:end])
    return out


def _first(pattern: str, text: str, group: int = 1) -> Optional[str]:
    m = re.search(pattern, text)
    return _clean(m.group(group)) if m else None


def parse_decision(pdf_path: str) -> AppealDecision:
    text, _ = extract_text(pdf_path)
    meta = parse_decision_filename(pdf_path)

    case_no = _field_after(text, "案　　號") or _first(r"案號[：:]\s*(\d+)", text)
    summary = _field_after(text, "要　　旨")
    doc_date = _field_after(text, "發文日期")
    doc_no = _field_after(text, "發文字號")
    related = _extract_related_statutes(text)

    appellant = _first(r"訴願人\s+([^\s，,\n]+)", text)
    authority = _first(r"原處分機關\s+([^\s，,\n]+)", text)

    sections = _split_sections(text)

    doc_id = case_no or meta.get("case_type", "") + f"-{meta.get('year','')}-{meta.get('seq','')}"

    return AppealDecision(
        doc_id=str(doc_id),
        source_file=pdf_path,
        year=meta.get("year"),
        seq=meta.get("seq"),
        case_type=meta.get("case_type"),
        procedural_basis=meta.get("procedural_basis"),
        result=meta.get("result"),
        case_no=case_no,
        doc_no=doc_no,
        doc_date=doc_date,
        summary=summary,
        appellant=appellant,
        original_authority=authority,
        related_statutes=related,
        main_text=sections["main_text"],
        facts=sections["facts"],
        reasons=sections["reasons"],
        full_text=text,
    )


# ---------- 法規逐條解析 ----------

_ROC_DATE = re.compile(r"民國\s*(\d+)\s*年")


def _roc_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    m = _ROC_DATE.search(date_str)
    return int(m.group(1)) if m else None


def parse_statute(pdf_path: str) -> list[StatuteArticle]:
    """
    法規格式：
      法規名稱：行政罰法
      修正日期：民國 111 年 06 月 15 日
      第 一 章 ...
      第 1 條
      <內容...>
      第 2 條
      ...
    逐條切分為多筆。
    """
    text, _ = extract_text(pdf_path)
    statute_name = _first(r"法規名稱[：:]\s*(.+)", text) or os.path.basename(pdf_path)
    # 清理標題行雜訊（PDF 標題常尾隨『EN』英文版字樣、頁碼等）
    statute_name = re.sub(r"\s*EN\s*$", "", statute_name).strip()
    statute_name = re.sub(r"\s+\d+$", "", statute_name).strip()
    amend_date = _first(r"修正日期[：:]\s*(.+)", text) or _first(r"公布日期[：:]\s*(.+)", text)
    amend_year = _roc_year(amend_date)

    # 以『第 N 條』為切點（條號可能含中文數字章節，需區分）
    # 條文標記：行首『第 <阿拉伯數字> 條』
    article_pat = re.compile(r"(?m)^第\s*(\d+)\s*條")
    matches = list(article_pat.finditer(text))

    # 章節標記，用於標注 chapter（可選）
    chapter_pat = re.compile(r"(?m)^\s*第\s*[一二三四五六七八九十百]+\s*章\s*(.+)")

    articles: list[StatuteArticle] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        num = int(m.group(1))
        body = text[m.end():end]
        content = _clean(body)

        # 找此條之前最近的章節
        chapter = None
        for cm in chapter_pat.finditer(text[:start]):
            chapter = _clean(cm.group(1))

        articles.append(StatuteArticle(
            doc_id=f"{statute_name}-第{num}條",
            statute_name=statute_name,
            amend_date=amend_date,
            amend_date_roc=amend_year,
            chapter=chapter,
            article_no=f"第 {num} 條",
            article_num=num,
            content=content or "",
            source_file=pdf_path,
        ))
    return articles


# ---------- 函釋解析 ----------

def _guess_related_statutes(s: str) -> list[str]:
    found = []
    for name in KNOWN_STATUTES:
        if name in s:
            found.append(name)
    # 去重、統一『空氣汙染/污染』
    norm = []
    for x in found:
        x = x.replace("空氣汙染防制法", "空氣污染防制法")
        if x not in norm:
            norm.append(x)
    return norm


def parse_interpretation(pdf_path: str) -> Interpretation:
    text, _ = extract_text(pdf_path)
    fname = os.path.basename(pdf_path)

    authority = _first(r"(法務部|內政部|行政院[^\s]*|[^\s]+部)", text)
    doc_no = _first(r"(法律字第\s*[\d]+\s*號|[\u4e00-\u9fff]*字第\s*[\d]+\s*號)", text)
    doc_date = _first(r"(民國\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)", text)
    summary = _first(r"要\s*旨[：:]?\s*\n?\s*(.+)", text)

    related = _guess_related_statutes(fname + " " + text)

    doc_id = re.sub(r"\.pdf( 的副本)?\.pdf$", "", fname)
    return Interpretation(
        doc_id=doc_id,
        issuing_authority=authority,
        doc_no=doc_no,
        doc_date=doc_date,
        summary=summary,
        content=_clean(text) or "",
        related_statutes=related,
        source_file=pdf_path,
    )


# ---------- 判解解析 ----------

def parse_precedent(pdf_path: str) -> CourtPrecedent:
    text, _ = extract_text(pdf_path)
    fname = os.path.basename(pdf_path)
    clean_name = re.sub(r"\.pdf( 的副本)?\.pdf$", "", fname)

    # 檔名格式：<法院/釋字><案號>-<爭點主題>
    court = _first(r"(最高行政法院|臺北高等行政法院|高雄高等行政法院|臺灣[^\s]+法院|司法院|釋字)", clean_name)
    topic = clean_name.split("-", 1)[1] if "-" in clean_name else None
    case_no = _first(r"(\d+\s*年度[^\-]*?號|第\s*\d+\s*號解釋)", clean_name)

    related = _guess_related_statutes(clean_name + " " + text)

    return CourtPrecedent(
        doc_id=clean_name,
        court=court,
        case_no=_clean(case_no),
        topic=_clean(topic),
        content=_clean(text) or "",
        related_statutes=related,
        source_file=pdf_path,
    )
