"""
新進訴願書 解析 + 分類（階段一輕量版，供 UI 頁籤1）。
把上傳的 PDF/文字 轉為 IncomingAppeal：
  - 案件類型分類（規則比對已知法規名，穩定不幻覺）
  - 關鍵欄位擷取（訴願人、原處分機關、處分書文號、行為時/處分時年度）
  - 有 Gemini 時可用 LLM 補強爭點摘要；無則用規則抽取
"""
from __future__ import annotations
import re
from typing import Optional

from .models import IncomingAppeal
from .parsers import extract_text, KNOWN_STATUTES, _clean
from .providers import get_provider

# 案件類型分類（規則）：命中法規名 -> 類型字串
_TYPE_RULES = [
    ("廢棄物清理法", "違反廢棄物清理法事件"),
    ("噪音管制法", "違反噪音管制法事件"),
    ("空氣污染防制法", "違反空氣污染防制法事件"),
    ("空氣汙染", "違反空氣污染防制法事件"),
    ("建築法", "違反建築法事件"),
    ("違章建築", "違章建築事件"),
    ("洗錢防制法", "違反洗錢防制法事件"),
    ("政府資訊", "申請提供政府資訊事件"),
    ("公寓大廈", "公寓大廈管理條例事件"),
    ("道路交通", "道路交通管理處罰條例事件"),
]


def classify(text: str) -> Optional[str]:
    for kw, label in _TYPE_RULES:
        if kw in text:
            return label
    return None


def _roc_years(text: str) -> list[int]:
    """抓所有『民國 NNN 年』或『NNN 年 M 月』的年度數字。"""
    ys = re.findall(r"(?:民國\s*)?(\d{2,3})\s*年", text)
    out = []
    for y in ys:
        n = int(y)
        if 90 <= n <= 130:  # 合理的民國年範圍
            out.append(n)
    return out


def parse_incoming(text: str, source_file: Optional[str] = None,
                   use_llm: bool = True) -> IncomingAppeal:
    text = text or ""
    case_type = classify(text)

    appellant = None
    m = re.search(r"訴願人[\s：:]*([^\s，,。\n（(]{1,10})", text)
    if m:
        appellant = _clean(m.group(1))

    authority = None
    m = re.search(r"(原處分機關|處分機關)[\s：:]*([^\s，,。\n（(]{1,20})", text)
    if m:
        authority = _clean(m.group(2))
    else:
        m = re.search(r"(新北市政府[^\s，,。\n]{0,10}局)", text)
        if m:
            authority = _clean(m.group(1))

    disp_no = None
    m = re.search(r"([\u4e00-\u9fff]*字第\s*[\d\-]+\s*號(?:裁處書|處分書)?)", text)
    if m:
        disp_no = _clean(m.group(1))

    # 行為時 / 處分時：取文中最早與最晚的合理年度作為近似
    years = _roc_years(text)
    behavior_roc = min(years) if years else None
    disposition_roc = max(years) if years else None

    claims = None
    facts = None
    # 規則抽取：事實段、訴願意旨
    m = re.search(r"事\s*實(.{20,600}?)(?:理\s*由|$)", text, re.S)
    if m:
        facts = _clean(m.group(1))[:400]
    m = re.search(r"訴願(?:意旨|理由)略?謂[：:]?(.{10,300})", text, re.S)
    if m:
        claims = _clean(m.group(1))[:300]

    # LLM 補強（可選）：擷取更精準的爭點；失敗則保留規則結果
    if use_llm:
        prov = get_provider()
        if prov.available and text.strip():
            try:
                prompt = (
                    "你是行政訴願承辦助理。以下是一份訴願書全文，請用繁體中文萃取：\n"
                    "1) 訴願人主張的核心爭點（一句話）\n"
                    "2) 違規事實摘要（一句話）\n"
                    "僅輸出 JSON：{\"爭點\":\"...\",\"事實\":\"...\"}，不要多餘文字。\n\n"
                    f"訴願書全文：\n{text[:3000]}"
                )
                resp = prov.generate(prompt, temperature=0.1, max_tokens=512)
                mj = re.search(r"\{.*\}", resp, re.S)
                if mj:
                    import json
                    data = json.loads(mj.group())
                    claims = data.get("爭點") or claims
                    facts = data.get("事實") or facts
            except Exception as e:
                print(f"[intake] LLM 補強失敗，保留規則結果：{str(e)[:60]}")

    return IncomingAppeal(
        source_file=source_file,
        case_type=case_type,
        appellant=appellant,
        original_authority=authority,
        disposition_no=disp_no,
        facts=facts,
        claims=claims,
        behavior_date_roc=behavior_roc,
        disposition_date_roc=disposition_roc,
        full_text=text,
    )


def parse_incoming_pdf(pdf_path: str, use_llm: bool = True) -> IncomingAppeal:
    text, _ = extract_text(pdf_path)
    return parse_incoming(text, source_file=pdf_path, use_llm=use_llm)
