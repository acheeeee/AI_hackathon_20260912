"""
步驟 D/E：結構辨識與依文件種類切段。

核心原則（依規格 §5 步驟 D/E）：
- 以行序列為基礎；每個 section 涵蓋一段連續行，quote_text 由原行逐字以 \n 重建。
- 每個非空白行都要歸到一個 section（含 preamble/excluded），不得默默遺失。
- 法規：以實際條文標題行為切點，支援『第 15 條』『第 15-2 條』『第十五條之二』；
  內文提及『依第 15 條』不切段。附加條號獨立成條，不吞併。
- 決定書：主文/事實/理由依獨立標題行切；無事實標題不補假段。
- 函釋/判解：依主旨/說明/理由等語意單元切。
"""
from __future__ import annotations

import re
from typing import Optional

from .common import normalize_article_key
from .extract import full_line_span

# 條文標題行：整行僅為『第 N 條』或『第 N-M 條』或中文『第X條之Y』
_ARTICLE_TITLE = re.compile(
    r"^第\s*(?:\d+(?:\s*-\s*\d+)?|[一二三四五六七八九十百千零]+(?:\s*之\s*[一二三四五六七八九十百千零]+)?)\s*條(?:\s*之\s*[一二三四五六七八九十百千零]+)?\s*$"
)
# 章節標題行
_CHAPTER_TITLE = re.compile(r"^\s*第\s*[一二三四五六七八九十百]+\s*[章節編款]\s*.*$")
# 目錄/附件/沿革標題（分開標記，不當條文）
_NON_ARTICLE = re.compile(r"^\s*(目\s*錄|附\s*件|附\s*表|沿\s*革|法規名稱|修正日期|公布日期|制定日期)")

# 刪除條文標記
_DELETED = re.compile(r"（\s*刪\s*除\s*）|删除|刪除")


def _is_article_title(text: str) -> bool:
    return bool(_ARTICLE_TITLE.match(text.strip()))


def _title_meta(text: str) -> dict:
    """從條文標題行取 article_key 與原始寫法。"""
    raw = text.strip()
    key = normalize_article_key(raw)
    return {"article_key": key, "article_no_raw": raw}


def segment_statute(document_id: str, lines: list[dict],
                    statute_name: str) -> list[dict]:
    """法規逐條切段。回傳 section dict 清單（含未歸屬行的 preamble/exclusion）。

    每個 section：section_type, ordinal, line_range, source_spans, quote_text, metadata。
    """
    sections: list[dict] = []
    ordinal = 0
    current_chapter: Optional[str] = None

    # 找出所有條文標題行的索引
    title_idxs = [i for i, ln in enumerate(lines) if _is_article_title(ln["text"])]

    # preamble：第一個條文標題之前的行（法規名稱、修正日期、章節等）
    first_title = title_idxs[0] if title_idxs else len(lines)
    if first_title > 0:
        ordinal += 1
        sections.append(_make_section(
            document_id, lines, 0, first_title, ordinal,
            section_type="preamble", metadata={"statute_name": statute_name},
        ))

    for n, ti in enumerate(title_idxs):
        end = title_idxs[n + 1] if n + 1 < len(title_idxs) else len(lines)
        # 更新章節：掃描此條標題前最近的章節標題
        for j in range(ti, -1, -1):
            if _CHAPTER_TITLE.match(lines[j]["text"].strip()):
                current_chapter = lines[j]["text"].strip()
                break
        tmeta = _title_meta(lines[ti]["text"])
        body_text = "".join(lines[k]["text"] for k in range(ti + 1, end))
        status = "deleted" if _DELETED.search(body_text) and len(body_text.strip()) < 10 else "active"
        ordinal += 1
        sections.append(_make_section(
            document_id, lines, ti, end, ordinal,
            section_type="statute_article",
            metadata={
                "statute_name": statute_name,
                "article_key": tmeta["article_key"],
                "article_no_raw": tmeta["article_no_raw"],
                "chapter": current_chapter,
                "article_status": status,
                # 生效日等未查證欄位留 null，由標註層補
                "is_current": None,
            },
        ))
    return sections


# ---- 決定書 ----
_DEC_MARKERS = [("main_text", "主文"), ("facts", "事實"), ("reasons", "理由"),
                ("teaching", "教示")]


def _match_marker_line(text: str, label: str) -> bool:
    """整行是否為分節標題（允許字間全形/半形空白）。"""
    t = text.strip().replace("\u3000", "")
    t = re.sub(r"\s+", "", t)
    return t == label


def segment_decision(document_id: str, lines: list[dict]) -> list[dict]:
    """訴願決定書切段：header + 主文/事實/理由/教示。無事實標題不補假段。"""
    sections: list[dict] = []
    ordinal = 0

    # 找分節標題行
    marker_idx: dict[str, int] = {}
    for i, ln in enumerate(lines):
        for key, lbl in _DEC_MARKERS:
            if key not in marker_idx and _match_marker_line(ln["text"], lbl):
                marker_idx[key] = i
    ordered = sorted(marker_idx.items(), key=lambda kv: kv[1])

    first = ordered[0][1] if ordered else len(lines)
    if first > 0:
        ordinal += 1
        sections.append(_make_section(
            document_id, lines, 0, first, ordinal,
            section_type="decision_header", metadata={},
        ))

    for n, (key, idx) in enumerate(ordered):
        end = ordered[n + 1][1] if n + 1 < len(ordered) else len(lines)
        ordinal += 1
        sections.append(_make_section(
            document_id, lines, idx, end, ordinal,
            section_type=f"decision_{key}", metadata={"section_role": key},
        ))
    return sections


# ---- 函釋 / 判解 ----
_INTERP_MARKERS = ["主旨", "說明", "結論", "附件"]
_PREC_MARKERS = ["主文", "事實", "理由", "事實及理由", "爭點", "解釋文", "解釋理由書"]


def _segment_by_markers(document_id: str, lines: list[dict],
                        markers: list[str], header_type: str,
                        body_prefix: str) -> list[dict]:
    sections: list[dict] = []
    ordinal = 0
    marker_positions: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        t = re.sub(r"\s+", "", ln["text"].strip().replace("\u3000", ""))
        for m in markers:
            # 標題行：以標記開頭且長度接近（避免內文提及）
            if t == m or t == m + "：" or t.startswith(m + "：") and len(t) <= len(m) + 2:
                marker_positions.append((i, m))
                break
    # 去重保留首次
    seen = set()
    dedup = []
    for i, m in marker_positions:
        if m not in seen:
            seen.add(m)
            dedup.append((i, m))
    dedup.sort()

    first = dedup[0][0] if dedup else len(lines)
    if first > 0:
        ordinal += 1
        sections.append(_make_section(
            document_id, lines, 0, first, ordinal,
            section_type=header_type, metadata={},
        ))
    for n, (idx, m) in enumerate(dedup):
        end = dedup[n + 1][0] if n + 1 < len(dedup) else len(lines)
        ordinal += 1
        sections.append(_make_section(
            document_id, lines, idx, end, ordinal,
            section_type=f"{body_prefix}_{m}", metadata={"marker": m},
        ))
    # 若完全無標記，整份為 unsectioned
    if not dedup and lines:
        sections = [_make_section(
            document_id, lines, 0, len(lines), 1,
            section_type="unsectioned", metadata={},
        )]
    return sections


def segment_interpretation(document_id: str, lines: list[dict]) -> list[dict]:
    return _segment_by_markers(document_id, lines, _INTERP_MARKERS,
                               "interpretation_header", "interpretation")


def segment_precedent(document_id: str, lines: list[dict]) -> list[dict]:
    return _segment_by_markers(document_id, lines, _PREC_MARKERS,
                               "precedent_header", "precedent")


# ---- 共用：由行範圍建 section ----

def _make_section(document_id: str, lines: list[dict], start: int, end: int,
                  ordinal: int, section_type: str, metadata: dict) -> dict:
    seg = lines[start:end]
    source_spans = [full_line_span(document_id, ln["page"], ln) for ln in seg]
    quote_text = "\n".join(ln["text"] for ln in seg)
    return {
        "ordinal": ordinal,
        "section_type": section_type,
        "line_start_idx": start,
        "line_end_idx": end,
        "source_spans": source_spans,
        "quote_text": quote_text,
        "metadata": metadata,
    }
