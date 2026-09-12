"""
前處理共用工具：雜湊、穩定 ID、正規化、版本常數。

依《資料前處理與切分交接規格》§5、§6。所有輸出 UTF-8 / LF。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Optional

# ---- 版本常數（切點/清理規則變動時必須更新）----
SCHEMA_VERSION = "1.0"
EXTRACTION_VERSION = "ext-1.0"
SEGMENTATION_VERSION = "seg-1.0"
CHUNKING_VERSION = "chunk-1.0"
ALIAS_TABLE_VERSION = "alias-1.0"

# ---- 枚舉 ----
DOCUMENT_TYPES = {"decision", "statute", "interpretation", "precedent"}
REVIEW_STATUSES = {"unreviewed", "verified", "needs_review", "rejected"}
SOURCE_ORIGINS = {"official_batch", "public_extension", "synthetic"}
MISSING_REASONS = {
    "not_stated", "no_explicit_section", "unreadable",
    "parse_failed", "ambiguous", "conflicting_sources", "not_applicable",
}

# ---- 名稱別名（僅用於 search_text / 正規化欄位，引用原文照錄）----
STATUTE_ALIASES = {
    "空氣汙染防制法": "空氣污染防制法",
}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_hash(text: str, n: int = 12) -> str:
    return sha256_text(text)[:n]


# ---- 穩定 ID（依 §6.1）----

def make_document_id(source_sha256: str) -> str:
    """以 PDF 位元組 SHA-256 產生不含結果暗示的穩定 ID；改路徑不改 ID。"""
    return "doc_" + source_sha256[:16]


def make_section_id(document_id: str, ordinal: int) -> str:
    raw = f"{document_id}|{EXTRACTION_VERSION}|{SEGMENTATION_VERSION}|{ordinal}"
    return "sec_" + short_hash(raw, 16)


def make_chunk_id(section_id: str, source_spans_key: str, quote_text: str) -> str:
    raw = f"{section_id}|{CHUNKING_VERSION}|{source_spans_key}|{sha256_text(quote_text)}"
    return "chk_" + short_hash(raw, 16)


def spans_key(source_spans: list[dict]) -> str:
    parts = []
    for s in source_spans:
        parts.append(
            f"{s['document_id']}:{s['extraction_version']}:{s['page']}:"
            f"{s['line']}:{s['char_start']}:{s['char_end']}"
        )
    return ";".join(parts)


# ---- 文字正規化（只作用於 search_text，不改 quote/raw）----

def normalize_search_text(text: str) -> str:
    """檢索正規化：統一全形空白、連續空白、換行；套用法名別名。

    不改否定詞、但書、日期、金額、條號、文號。
    """
    if text is None:
        return ""
    # 全形空白 -> 半形
    text = text.replace("\u3000", " ")
    # 統一換行
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 連續空白
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 名稱別名（僅檢索層）
    for src, dst in STATUTE_ALIASES.items():
        text = text.replace(src, dst)
    return text.strip()


def count_chars(text: str) -> int:
    """以 Unicode code point 數計（非 token、非 byte）。"""
    return len(text)


def normalize_article_key(raw: str) -> Optional[str]:
    """把『第 15 條』『第 15-2 條』『第十五條之二』正規化為 '15' / '15-2'。

    保留原始寫法由呼叫端負責；此處只回傳正規化鍵，無法解析回 None。
    """
    if not raw:
        return None
    s = raw.replace("\u3000", " ").strip()
    # 阿拉伯數字：第 15-2 條 / 第15條
    m = re.search(r"第\s*(\d+)(?:\s*-\s*(\d+))?\s*條", s)
    if m:
        return m.group(1) if not m.group(2) else f"{m.group(1)}-{m.group(2)}"
    # 中文數字：第十五條之二
    m = re.search(r"第\s*([一二三四五六七八九十百千零]+)\s*條(?:\s*之\s*([一二三四五六七八九十百千零]+))?", s)
    if m:
        base = cn_to_int(m.group(1))
        if base is None:
            return None
        if m.group(2):
            sub = cn_to_int(m.group(2))
            return f"{base}-{sub}" if sub is not None else str(base)
        return str(base)
    return None


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def cn_to_int(s: str) -> Optional[int]:
    """中文數字轉整數，支援十/百/千（法條號範圍足夠）。

    例：一->1、十->10、十五->15、二十一->21、一百零八->108。
    """
    if not s:
        return None
    total = 0
    current = 0
    for ch in s:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            total += (current or 1) * unit
            current = 0
        else:
            return None
    total += current
    return total or None
