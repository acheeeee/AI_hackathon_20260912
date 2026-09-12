"""
步驟 E：由 section 產生檢索用 chunk。

長度起始設定（以清理後 Unicode 字元數計，非 token）：
- 一般子段目標 400–800 字；1,200 字為重新檢查切點的軟上限。
- 完整短條/短段不強迫補滿。
- 先按法律結構（項/款/目、編號論點），再按句界；不從句中硬切、不截掉後半、不把但書單獨留下。
- 核心子段不重疊；超長原子單元無法安全再切標 oversize_atomic，保留全文不靜默截斷。

chunk-2.0：所有切點以 quote_text 內的字元 offset 追蹤，切出的每個 chunk 都用
offset 對應回原行清單算出精確 source_spans（可能是某行的部分字元範圍），
不再整段沿用 section 的全部 spans。這修正 r1 623/3,106 個 chunk 的 quote／
spans 不一致缺口（chunk 只取整段的一部分文字，卻標記整段來源座標）。
"""
from __future__ import annotations

import re

from .common import (
    CHUNKING_VERSION, count_chars, make_chunk_id, normalize_search_text,
    spans_key,
)
from .extract import make_span

TARGET_MIN = 400
TARGET_MAX = 800
SOFT_CAP = 1200

# 項次/款/目 起始（法規子段）
_PARA_MARK = re.compile(r"^(?:\d+|[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\))")
# 決定書理由編號論點
_POINT_MARK = re.compile(r"^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[、.．])")
# 中文句界（保留標點）
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？；])")


def _line_offsets(lines: list[str]) -> list[tuple[int, int]]:
    """回傳每行在『以 \\n 相接』的完整文字內的 (start, end) 字元 offset。"""
    offsets: list[tuple[int, int]] = []
    pos = 0
    for ln in lines:
        start = pos
        end = pos + len(ln)
        offsets.append((start, end))
        pos = end + 1  # +1 為分行的 \n
    return offsets


def _structure_ranges(quote_text: str) -> list[tuple[int, int]]:
    """依項/款/編號論點的行首標記把 quote_text 分成連續、不重疊的字元範圍。"""
    lines = quote_text.split("\n")
    offsets = _line_offsets(lines)
    group_starts = [0]
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if i > 0 and (_PARA_MARK.match(stripped) or _POINT_MARK.match(stripped)):
            group_starts.append(i)
    group_starts = sorted(set(group_starts))
    ranges: list[tuple[int, int]] = []
    for idx, ls in enumerate(group_starts):
        le = group_starts[idx + 1] if idx + 1 < len(group_starts) else len(lines)
        if le <= ls:
            continue
        ranges.append((offsets[ls][0], offsets[le - 1][1]))
    return ranges


def _sentence_ranges(text: str, base_offset: int) -> list[tuple[int, int]]:
    """把 text（quote_text 中 [base_offset, base_offset+len(text)) 的片段）依句界切，
    回傳對應到 quote_text 座標系的字元範圍清單。split 使用零寬斷言，片段串接
    後與原字串完全相同，offset 用累計長度推算，不做子字串搜尋。"""
    parts = _SENTENCE_BOUNDARY.split(text)
    ranges: list[tuple[int, int]] = []
    pos = 0
    for part in parts:
        if part:
            ranges.append((base_offset + pos, base_offset + pos + len(part)))
        pos += len(part)
    return ranges


def _pack_ranges(ranges: list[tuple[int, int]], quote_text: str) -> list[tuple[int, int]]:
    """貪婪打包連續字元範圍到目標長度；超過軟上限的原子範圍先切出，
    再嘗試按句界細分，句界仍無法切開則保留為 oversize 原子範圍。"""
    packed: list[tuple[int, int]] = []
    buf_start: int | None = None
    buf_end: int | None = None

    def flush() -> None:
        nonlocal buf_start, buf_end
        if buf_start is not None:
            packed.append((buf_start, buf_end))
        buf_start = buf_end = None

    for (s, e) in ranges:
        length = e - s
        if length > SOFT_CAP:
            flush()
            sub_ranges = _sentence_ranges(quote_text[s:e], s)
            if len(sub_ranges) <= 1:
                # 無句界可切，保留為單一超長原子範圍
                packed.append((s, e))
                continue
            for sub in _pack_ranges(sub_ranges, quote_text):
                packed.append(sub)
            continue
        if buf_start is None:
            buf_start, buf_end = s, e
        elif (buf_end - buf_start) + length > TARGET_MAX:
            flush()
            buf_start, buf_end = s, e
        else:
            buf_end = e
    flush()
    return packed


def _spans_for_range(document_id: str, offset_table: list[tuple[int, int, dict]],
                     start: int, end: int) -> list[dict]:
    """依 quote_text 內的 [start, end) 字元範圍，對應回原行清單，
    產生可能含部分字元範圍的精確 source_spans。"""
    spans: list[dict] = []
    for line_start, line_end, ln in offset_table:
        os_ = max(start, line_start)
        oe_ = min(end, line_end)
        if oe_ > os_:
            spans.append(make_span(
                document_id, ln["page"], ln["line"],
                os_ - line_start, oe_ - line_start,
            ))
    return spans


def make_chunks(section: dict, document_id: str, index_eligible: bool,
                quality_flags: list[str]) -> list[dict]:
    """由一個 section 產生 chunk 清單。

    每個 chunk 的文字直接來自 quote_text 的字元切片（保證與來源逐字相同），
    source_spans 由該切片的 offset 對應回原行精確算出，不再借用整段 spans。
    """
    quote = section["quote_text"]
    total = count_chars(quote)
    section_id = section["section_id"]

    # 由 section 的行清單重建 (start,end,ln) offset table；section 的
    # source_spans 是依原行順序產生（見 segment.py _make_section），
    # 順序與 quote_text.split("\n") 完全對應。
    seg_lines = quote.split("\n")
    line_offsets = _line_offsets(seg_lines)
    offset_table = [
        (line_offsets[i][0], line_offsets[i][1], {
            "page": section["source_spans"][i]["page"],
            "line": section["source_spans"][i]["line"],
        })
        for i in range(len(seg_lines))
    ]
    # 分行符（\n）位置＝某一行的 end 且不是任何行的 start（最後一行的 end 是
    # 全文終點，不是分行符，故排除）。句界切分只用累計字元長度算 offset，
    # 不知道行界；若句尾標點剛好是某行最後一個字，切點數值會等於該行的
    # end，這個值當「結束」正確，但當下一段的「開始」會把分行符也算進去，
    # 導致 quote 多一個 \n、由 spans 重建卻對不上（因為分行符不屬於任何
    # 行，spans 無法代表它）。故把落在分行符位置的 range 起點往後移一格。
    line_gap_positions = {line_offsets[i][1] for i in range(len(seg_lines) - 1)}

    if total <= TARGET_MAX:
        ranges = [(0, len(quote))]
    else:
        struct_ranges = _structure_ranges(quote)
        ranges = _pack_ranges(struct_ranges, quote)
    ranges = [
        (start + 1 if start in line_gap_positions else start, end)
        for (start, end) in ranges
    ]

    chunks: list[dict] = []
    for (start, end) in ranges:
        piece = quote[start:end]
        if not piece.strip():
            continue
        piece_spans = _spans_for_range(document_id, offset_table, start, end)
        flags = list(quality_flags)
        if count_chars(piece) > SOFT_CAP:
            flags.append("oversize_atomic")
        search_text = normalize_search_text(piece)
        sk = spans_key(piece_spans)
        chunk_id = make_chunk_id(section_id, sk, piece)
        chunks.append({
            "chunk_id": chunk_id,
            "section_id": section_id,
            "document_id": document_id,
            "chunking_version": CHUNKING_VERSION,
            "quote_text": piece,
            "search_text": search_text,
            "source_spans": piece_spans,
            "context_section_ids": [],
            "index_eligible": index_eligible,
            "quality_flags": flags,
            "char_count": count_chars(piece),
        })
    return chunks
