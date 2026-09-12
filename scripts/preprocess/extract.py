"""
步驟 B：逐頁抽取與原文座標。

用 PyMuPDF 抽取文字層，每頁保留頁寬高、旋轉、文字行、bbox、抽取順序。
座標規約（依規格 §5 步驟 B）：
- page：PDF 物理頁碼，從 1 起算。
- line：抽取版本固定的頁內行號，從 1 起算。
- bbox：[x0, y0, x1, y1]，PyMuPDF 該頁座標系。
- char_start/char_end：該原始行字串的 Unicode code point 範圍，0 起算、左含右不含。

不得把「抽不到字」直接判為「原文無內容」；低文字頁標記待人工檢查。
"""
from __future__ import annotations

from typing import Optional

import fitz  # PyMuPDF

from .common import EXTRACTION_VERSION

LOW_TEXT_THRESHOLD = 20  # 非空白字元數門檻


def extract_pages(pdf_path: str) -> list[dict]:
    """回傳每頁 dict：page, width, height, rotation, raw_text, lines[], extraction_method。"""
    doc = fitz.open(pdf_path)
    pages: list[dict] = []
    for i, page in enumerate(doc):
        rect = page.rect
        data = page.get_text("dict")
        lines: list[dict] = []
        raw_parts: list[str] = []
        line_no = 0
        # 依 PyMuPDF 抽取順序（保留 block/line 原始序）
        for block in data.get("blocks", []):
            if "lines" not in block:
                continue  # 影像 block 無文字行
            for ln in block["lines"]:
                text = "".join(span["text"] for span in ln.get("spans", []))
                if text == "":
                    continue
                line_no += 1
                bbox = [round(c, 2) for c in ln["bbox"]]
                lines.append({
                    "line": line_no,
                    "text": text,
                    "bbox": bbox,
                    "char_start": 0,
                    "char_end": len(text),  # Unicode code point 範圍
                })
                raw_parts.append(text)
        raw_text = "\n".join(raw_parts)
        nonspace = len("".join(raw_text.split()))
        pages.append({
            "page": i + 1,
            "width": round(rect.width, 2),
            "height": round(rect.height, 2),
            "rotation": page.rotation,
            "raw_text": raw_text,
            "lines": lines,
            "extraction_method": "text_layer",
            "nonspace_chars": nonspace,
            "low_text": nonspace < LOW_TEXT_THRESHOLD,
        })
    doc.close()
    return pages


def page_full_text(pages: list[dict]) -> str:
    """所有頁 raw_text 以換行連接（供結構辨識用；座標另存於 lines）。"""
    return "\n".join(p["raw_text"] for p in pages)


def flat_lines(pages: list[dict]) -> list[dict]:
    """把所有頁的行攤平為單一序列，供結構切分逐行歸屬。

    每筆：{page, line, text, char_start, char_end}。切分在此序列上進行，
    每個 section 記錄涵蓋的行範圍，quote_text 由這些原行逐字重建。
    """
    out: list[dict] = []
    for p in pages:
        for ln in p["lines"]:
            out.append({
                "page": p["page"],
                "line": ln["line"],
                "text": ln["text"],
                "char_start": ln["char_start"],
                "char_end": ln["char_end"],
            })
    return out


def make_span(document_id: str, page: int, line: int,
              char_start: int, char_end: int) -> dict:
    """建立標準 source_span 元素。"""
    return {
        "document_id": document_id,
        "extraction_version": EXTRACTION_VERSION,
        "page": page,
        "line": line,
        "char_start": char_start,
        "char_end": char_end,
    }


def full_line_span(document_id: str, page: int, ln: dict) -> dict:
    return make_span(document_id, page, ln["line"], ln["char_start"], ln["char_end"])
