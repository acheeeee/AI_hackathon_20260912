"""Render the current persisted draft head as a portable A4 PDF.

The renderer deliberately consumes only ``content.blocks[].text``.  Citation
ids, dependency snapshots, hashes, source documents, and provider metadata are
not presentation content and therefore never enter the PDF.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any

import fitz

from caseapi.errors import invalid_field, resource_not_found
from caseapi.services import case_repository as repo
from caseapi.services import resource_service

A4_WIDTH = 595.28
A4_HEIGHT = 841.89
LEFT_MARGIN = 56.7
RIGHT_MARGIN = 56.7
TOP_MARGIN = 48.0
BOTTOM_MARGIN = 54.0
BODY_FONT_SIZE = 12.0
BODY_LINE_HEIGHT = 21.0
MAX_EXPORT_CHARS = 200_000
PDF_FILENAME = 'appeal-decision-draft.pdf'

_FONT_NAME = 'DraftTraditionalChinese'
_PAGE_NUMBER_FONT_SIZE = 9.0
_FONT_BYTES = fitz.Font(fontname='china-t').buffer


@dataclass(frozen=True)
class _LineStyle:
    font_size: float = BODY_FONT_SIZE
    line_height: float = BODY_LINE_HEIGHT
    align: str = 'left'
    left_indent: float = 0.0


def render_current_draft_head(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    draft_id: str,
) -> bytes:
    """Load and render exactly the current head of ``draft_id``.

    There is intentionally no revision argument.  A caller cannot use the
    export route to fetch an obsolete or foreign draft revision.
    """
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    head = repo.load_heads(case_row).get(draft_id)
    if head is None or head.get('kind') != repo.KIND_DRAFT:
        raise resource_not_found()

    row = resource_service.require_version(
        conn,
        case_id=case_id,
        resource_id=draft_id,
        revision_id=head['revision_id'],
    )
    content = json.loads(row['content_json'])
    blocks = content.get('blocks')
    if not isinstance(blocks, list) or not blocks:
        raise invalid_field('草稿沒有可匯出的正文區塊')
    return render_draft_pdf(blocks)


def render_draft_pdf(blocks: list[dict[str, Any]]) -> bytes:
    """Render persisted block text in order without deriving legal content."""
    normalized = _presentation_blocks(blocks)
    if not normalized:
        raise invalid_field('草稿沒有可匯出的正式正文區塊')
    if sum(len(text) for _, text in normalized) > MAX_EXPORT_CHARS:
        raise invalid_field('草稿正文過長，無法匯出 PDF')

    font = fitz.Font(fontbuffer=_FONT_BYTES)
    _validate_font_coverage(normalized, font)
    document = fitz.open()
    writer = _DraftPdfWriter(document=document, font=font)
    try:
        for block_index, (block_id, text) in enumerate(normalized):
            if block_index:
                writer.add_vertical_space(8.0)
            writer.write_block(block_id, text)
        writer.add_page_numbers()
        document.set_metadata(
            {
                'title': '訴願決定書草稿',
                'subject': '未經核定之工作草稿',
                'creator': '訴願案件協作系統',
                'producer': 'PyMuPDF',
            }
        )
        document.subset_fonts()
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()


def _validate_font_coverage(
    blocks: list[tuple[str, str]],
    font: fitz.Font,
) -> None:
    """Fail explicitly when the portable embedded font cannot preserve text.

    PyMuPDF otherwise writes an unsupported character as a NUL glyph while
    still returning a valid PDF.  A visible 422 is safer than silently changing
    a party name or legal text in the exported document.
    """
    for _, text in blocks:
        for character in text:
            if character != '\n' and not font.has_glyph(ord(character)):
                codepoint = f'U+{ord(character):04X}'
                raise invalid_field(
                    f'草稿含目前 PDF 字型無法輸出的字元 {codepoint}，請更換字元後重試'
                )


def _presentation_blocks(blocks: list[dict[str, Any]]) -> list[tuple[str, str]]:
    presentation: list[tuple[str, str]] = []
    for block in blocks:
        if not isinstance(block, dict):
            raise invalid_field('草稿正文區塊格式錯誤')
        block_id = block.get('block_id')
        text = block.get('text')
        if not isinstance(block_id, str) or not isinstance(text, str):
            raise invalid_field('草稿正文區塊缺少 block_id 或 text')
        # ``index-header-1`` is the search/database index shown beside a saved
        # decision.  It repeats the title and introduces labels such as 全文,
        # but it is not part of the formal decision body that a user downloads.
        # Keep it persisted for the UI and provenance contract; omit it only at
        # the presentation boundary so the PDF has one canonical document.
        if block_id == 'index-header-1':
            continue
        presentation.append((block_id, _sanitize_text(text)))
    return presentation


def _sanitize_text(text: str) -> str:
    """Normalize line endings and drop PDF-hostile control characters.

    Text is never interpreted as HTML, markup, a filename, or a PDF command.
    Ordinary Unicode, including the user's masking character ``○``, remains
    byte-for-byte equivalent after UTF-8 decoding.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\t', '    ')
    return ''.join(
        character
        for character in text
        if character == '\n' or unicodedata.category(character) != 'Cc'
    )


class _DraftPdfWriter:
    def __init__(self, *, document: fitz.Document, font: fitz.Font) -> None:
        self.document = document
        self.font = font
        self.page: fitz.Page | None = None
        self.y = TOP_MARGIN
        self._new_page()

    @property
    def content_width(self) -> float:
        return A4_WIDTH - LEFT_MARGIN - RIGHT_MARGIN

    def _new_page(self) -> None:
        self.page = self.document.new_page(width=A4_WIDTH, height=A4_HEIGHT)
        self.page.insert_font(fontname=_FONT_NAME, fontbuffer=_FONT_BYTES)
        self.y = TOP_MARGIN

    def _ensure_space(self, height: float) -> None:
        if self.y + height <= A4_HEIGHT - BOTTOM_MARGIN:
            return
        self._new_page()

    def add_vertical_space(self, height: float) -> None:
        self._ensure_space(height)
        self.y += height

    def write_block(self, block_id: str, text: str) -> None:
        lines = text.split('\n')
        self._ensure_space(self._minimum_block_height(block_id, lines))
        for line_index, logical_line in enumerate(lines):
            style = _style_for(block_id, line_index, logical_line)
            if not logical_line:
                self.add_vertical_space(style.line_height * 0.55)
                continue
            wrapped = self._wrap(logical_line, style)
            for visual_line in wrapped:
                self._write_line(visual_line, style)

    def _minimum_block_height(self, block_id: str, lines: list[str]) -> float:
        if not lines:
            return BODY_LINE_HEIGHT
        first = _style_for(block_id, 0, lines[0])
        following = _style_for(block_id, 1, lines[1] if len(lines) > 1 else '')
        return first.line_height + following.line_height

    def _wrap(self, text: str, style: _LineStyle) -> list[str]:
        available = self.content_width - style.left_indent
        if available <= 0:
            return [text]
        lines: list[str] = []
        current = ''
        for character in text:
            candidate = current + character
            if current and self.font.text_length(candidate, fontsize=style.font_size) > available:
                lines.append(current)
                current = character
            else:
                current = candidate
        lines.append(current)
        return lines

    def _write_line(self, text: str, style: _LineStyle) -> None:
        self._ensure_space(style.line_height)
        assert self.page is not None
        width = self.font.text_length(text, fontsize=style.font_size)
        if style.align == 'center':
            x = max(LEFT_MARGIN, (A4_WIDTH - width) / 2)
        elif style.align == 'right':
            x = max(LEFT_MARGIN, A4_WIDTH - RIGHT_MARGIN - width)
        else:
            x = LEFT_MARGIN + style.left_indent
        baseline = self.y + style.font_size
        self.page.insert_text(
            (x, baseline),
            text,
            fontname=_FONT_NAME,
            fontsize=style.font_size,
            color=(0, 0, 0),
        )
        self.y += style.line_height

    def add_page_numbers(self) -> None:
        page_count = self.document.page_count
        for page_index, page in enumerate(self.document):
            page.insert_font(fontname=_FONT_NAME, fontbuffer=_FONT_BYTES)
            label = f'{page_index + 1} / {page_count}'
            width = self.font.text_length(label, fontsize=_PAGE_NUMBER_FONT_SIZE)
            page.insert_text(
                ((A4_WIDTH - width) / 2, A4_HEIGHT - 24.0),
                label,
                fontname=_FONT_NAME,
                fontsize=_PAGE_NUMBER_FONT_SIZE,
                color=(0.35, 0.35, 0.35),
            )


def _style_for(block_id: str, line_index: int, text: str) -> _LineStyle:
    if block_id == 'index-header-1' and line_index == 0:
        return _LineStyle(font_size=17.0, line_height=28.0, align='center')
    if block_id == 'body-heading-1':
        if line_index == 0:
            return _LineStyle(font_size=17.0, line_height=29.0, align='center')
        return _LineStyle(font_size=11.0, line_height=20.0, align='right')
    if block_id in {'main-1', 'fact-1', 'reason-1'} and line_index == 0:
        return _LineStyle(font_size=14.0, line_height=26.0, align='center')
    if block_id == 'parties-1':
        return _LineStyle(left_indent=28.0)
    if block_id in {'signature-1', 'remedy-1', 'date-1'}:
        return _LineStyle(font_size=11.0, line_height=20.0, left_indent=14.0)
    if text.startswith(('一、', '二、', '三、', '四、', '五、', '六、', '七、', '八、')):
        return _LineStyle(left_indent=0.0)
    return _LineStyle()
