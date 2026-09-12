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

from .annotate import find_law_header
from .common import make_law_id, normalize_article_key, parse_roc_date
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


def _filter_toc_widget_titles(title_idxs: list[int]) -> tuple[list[int], list[int]]:
    """排除來源順序無法還原視覺欄位時的連續假標題候選。

    r2 曾把 PyMuPDF 的 block 原順序誤判為 PDF 缺少條文標題；r3 已在抽取層
    依 bbox 重建法規的視覺閱讀順序，正常流程不會再出現整頁條號先於正文的
    假象。本函式保留為舊產物與非視覺順序呼叫者的防禦性退場機制：真正條文
    之間應有內文，連續兩個以上、完全沒有內文間隔的條號候選才排除。

    回傳 (real_title_idxs, excluded_idxs)。
    """
    if not title_idxs:
        return title_idxs, []
    excluded: set[int] = set()
    n = len(title_idxs)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and title_idxs[j + 1] == title_idxs[j] + 1:
            j += 1
        if j - i + 1 >= 2:
            excluded.update(title_idxs[i:j + 1])
        i = j + 1
    real = [t for t in title_idxs if t not in excluded]
    return real, sorted(excluded)


_ARTICLE_RELIABILITY_MIN_RATIO = 0.5


def _segment_statute_unreliable_titles(document_id: str, lines: list[dict],
                                       statute_name: str, law_meta_base: dict,
                                       excluded_count: int) -> list[dict]:
    """條號標題整體不可信時的退場機制（見 segment_statute 的判斷條件）。

    r3 正常法規流程會先依 bbox 重建視覺閱讀順序。只有呼叫者未提供該順序，
    或遇到無法靠幾何位置還原的其他版型，才可能進入本退場機制。此時按章／
    節切段保留全文與回查性，但不冒充已有 article_key 精確引用。
    """
    sections: list[dict] = []
    ordinal = 0
    note = (
        f"本次輸入順序中有 {excluded_count} 個連續『第 N 條』候選，"
        "無法可靠對應條文正文。改採章／節切分，保留全文但不提供 article_key "
        "層級引用；應先檢查是否使用法規 visual reading order，再判定來源版型。"
    )
    chapter_idxs = [i for i, ln in enumerate(lines) if _CHAPTER_TITLE.match(ln["text"].strip())]
    first = chapter_idxs[0] if chapter_idxs else len(lines)
    if first > 0:
        ordinal += 1
        sections.append(_make_section(
            document_id, lines, 0, first, ordinal, section_type="preamble",
            metadata=dict(law_meta_base, statute_name=statute_name,
                         unsegmented_article_note=note,
                         unsegmented_reason="all_article_titles_are_pagination_widget"),
        ))
    for n, ci in enumerate(chapter_idxs):
        end = chapter_idxs[n + 1] if n + 1 < len(chapter_idxs) else len(lines)
        ordinal += 1
        sections.append(_make_section(
            document_id, lines, ci, end, ordinal, section_type="statute_unsectioned",
            metadata=dict(
                law_meta_base, statute_name=statute_name,
                chapter=lines[ci]["text"].strip(), article_key=None,
                article_status="unknown", is_current=None, paragraph_path=None,
                unsegmented_article_note=note,
                unsegmented_reason="all_article_titles_are_pagination_widget",
            ),
        ))
    return sections


def segment_statute(document_id: str, lines: list[dict],
                    statute_name: str) -> list[dict]:
    """法規逐條切段。回傳 section dict 清單（含未歸屬行的 preamble/exclusion）。

    每個 section：section_type, ordinal, line_range, source_spans, quote_text, metadata。

    跳頁小工具假標題（見 `_filter_toc_widget_titles`）排除後，若某段真正
    section 的行範圍內仍含有被排除的假標題，代表小工具吞掉的那幾個條號的
    真正內容其實落在這段裡（PDF 沒有另外重複一次真正的標題行）。內容不會
    遺失（仍完整保留在該 section 的 quote_text），但無法逐條切開、無法用
    article_key 個別引用；用 `unsegmented_article_keys` 明記，並交
    review_queue 提示人工或後續規則補切，不假裝已切好。
    """
    sections: list[dict] = []
    ordinal = 0
    current_chapter: Optional[str] = None

    header = find_law_header(lines)
    law_id = make_law_id(statute_name)
    promulgation_date = None
    amendment_date = None
    if header["date_raw"]:
        parsed = parse_roc_date(header["date_raw"])
        if header["date_label"] == "修正日期":
            amendment_date = parsed
        elif header["date_label"] == "制定日期":
            promulgation_date = parsed
    law_meta_base = {
        "law_id": law_id,
        "source_version_id": document_id,
        "promulgation_date": promulgation_date,
        "amendment_date": amendment_date,
        "effective_from": None,
        "effective_to": None,
    }

    all_title_idxs = [i for i, ln in enumerate(lines) if _is_article_title(ln["text"])]
    title_idxs, excluded_idxs = _filter_toc_widget_titles(all_title_idxs)

    if all_title_idxs and len(title_idxs) / len(all_title_idxs) < _ARTICLE_RELIABILITY_MIN_RATIO:
        return _segment_statute_unreliable_titles(
            document_id, lines, statute_name, law_meta_base, len(excluded_idxs),
        )

    def _swallowed_keys(range_start: int, range_end: int) -> list[str]:
        keys = []
        for idx in excluded_idxs:
            if range_start <= idx < range_end:
                key = _title_meta(lines[idx]["text"])["article_key"]
                if key:
                    keys.append(key)
        return keys

    def _with_unsegmented_note(meta: dict, swallowed: list[str]) -> dict:
        if not swallowed:
            return meta
        meta = dict(meta)
        meta["unsegmented_article_keys"] = swallowed
        meta["unsegmented_article_note"] = (
            f"跳頁小工具排除 {len(swallowed)} 個假標題行（對應條號 {swallowed}）；"
            "真正內容仍完整保留於本 section 內文，但未能個別切成獨立 "
            "statute_article，需人工或後續規則補切（見 review_queue）。"
        )
        return meta

    # preamble：第一個真正條文標題之前的行（法規名稱、修正日期、章節等）
    first_title = title_idxs[0] if title_idxs else len(lines)
    preamble_meta = _with_unsegmented_note(
        dict(law_meta_base, statute_name=statute_name), _swallowed_keys(0, first_title),
    )
    if first_title > 0:
        ordinal += 1
        sections.append(_make_section(
            document_id, lines, 0, first_title, ordinal,
            section_type="preamble", metadata=preamble_meta,
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
        meta = _with_unsegmented_note(dict(
            law_meta_base,
            statute_name=statute_name,
            article_key=tmeta["article_key"],
            article_no_raw=tmeta["article_no_raw"],
            chapter=current_chapter,
            article_status=status,
            # 生效日／現行狀態未經另行查證，留 null 不臆測
            is_current=None,
            paragraph_path=None,
        ), _swallowed_keys(ti + 1, end))
        sections.append(_make_section(
            document_id, lines, ti, end, ordinal,
            section_type="statute_article", metadata=meta,
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
