"""
步驟 E：由 section 產生檢索用 chunk。

長度起始設定（以清理後 Unicode 字元數計，非 token）：
- 一般子段目標 400–800 字；1,200 字為重新檢查切點的軟上限。
- 完整短條/短段不強迫補滿。
- 先按法律結構（項/款/目、編號論點），再按句界；不從句中硬切、不截掉後半、不把但書單獨留下。
- 核心子段不重疊；超長原子單元無法安全再切標 oversize_atomic，保留全文不靜默截斷。
"""
from __future__ import annotations

import re

from .common import (
    count_chars, make_chunk_id, normalize_search_text, spans_key,
)

TARGET_MIN = 400
TARGET_MAX = 800
SOFT_CAP = 1200

# 項次/款/目 起始（法規子段）
_PARA_MARK = re.compile(r"^(?:\d+|[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\))")
# 決定書理由編號論點
_POINT_MARK = re.compile(r"^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[、.．])")


def _split_by_structure(quote_text: str) -> list[str]:
    """先按行結構（項/款/編號論點）分組。回傳片段清單，各含原始換行。"""
    lines = quote_text.split("\n")
    groups: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if (_PARA_MARK.match(stripped) or _POINT_MARK.match(stripped)) and cur:
            groups.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        groups.append(cur)
    return ["\n".join(g) for g in groups]


def _split_by_sentence(text: str) -> list[str]:
    """按中文句界（。！？；）切，保留標點。不從句中硬切。"""
    parts = re.split(r"(?<=[。！？；])", text)
    return [p for p in parts if p.strip()]


def _pack(fragments: list[str]) -> list[str]:
    """把片段貪婪打包到目標長度，超過軟上限的原子片段獨立保留。"""
    chunks: list[str] = []
    buf = ""
    for frag in fragments:
        if count_chars(frag) > SOFT_CAP:
            # 先送出現有 buffer
            if buf.strip():
                chunks.append(buf)
                buf = ""
            # 再嘗試按句界切
            sents = _split_by_sentence(frag)
            sbuf = ""
            for s in sents:
                if count_chars(sbuf) + count_chars(s) > TARGET_MAX and sbuf.strip():
                    chunks.append(sbuf)
                    sbuf = s
                else:
                    sbuf += s
            if sbuf.strip():
                chunks.append(sbuf)
            continue
        if count_chars(buf) + count_chars(frag) > TARGET_MAX and buf.strip():
            chunks.append(buf)
            buf = frag
        else:
            buf = buf + "\n" + frag if buf else frag
    if buf.strip():
        chunks.append(buf)
    return chunks


def make_chunks(section: dict, document_id: str, index_eligible: bool,
                quality_flags: list[str]) -> list[dict]:
    """由一個 section 產生 chunk 清單。

    短 section 直接成單一 chunk；長 section 按結構→句界打包。
    每個 chunk 的 source_spans 沿用 section 的行 span（chunk 為 section 內連續內容，
    以 section 整體 span 標示可回查；細粒度 span 由 section 保存）。
    """
    quote = section["quote_text"]
    total = count_chars(quote)
    section_id = section["section_id"]

    if total <= TARGET_MAX:
        pieces = [quote]
    else:
        frags = _split_by_structure(quote)
        pieces = _pack(frags)

    chunks: list[dict] = []
    for piece in pieces:
        flags = list(quality_flags)
        if count_chars(piece) > SOFT_CAP:
            flags.append("oversize_atomic")
        search_text = normalize_search_text(piece)
        # chunk 沿用 section 的 source_spans（可回查原行）；quote 為該片段原文
        sk = spans_key(section["source_spans"]) + "|" + str(len(chunks))
        chunk_id = make_chunk_id(section_id, sk, piece)
        chunks.append({
            "chunk_id": chunk_id,
            "section_id": section_id,
            "document_id": document_id,
            "quote_text": piece,
            "search_text": search_text,
            "source_spans": section["source_spans"],
            "context_section_ids": [],
            "index_eligible": index_eligible,
            "quality_flags": flags,
            "char_count": count_chars(piece),
        })
    return chunks
