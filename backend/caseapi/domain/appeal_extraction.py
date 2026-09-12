"""Rule-based field extraction from a fixed-format 訴願書 (appeal letter).

The 訴願書 is a standardized Executive Yuan form, so a template-aware regex
approach is appropriate here — unlike the 行政處分函 (disposition letter),
which has no fixed layout and is not attempted here (see the intake service
docstring). PyMuPDF's default text order jumbles the top table (all labels
first, then all values, because that is how the form's table cells are laid
out), so extraction anchors on parts of the form that stay intact regardless
of table-cell ordering:

- appellant name: the clean restatement near the signature block
  ("訴 願 人：NAME"), not the scrambled top-table occurrence.
- disposition authority: the "原行政處分機關 / 受理訴願機關" label pair.
- disposition doc number / date: the "發文日期及文號 / 行政處分之年月日"
  label pair, with internal whitespace stripped first — PDF line-wraps can
  split a document number or date in the middle of a token
  (e.g. "第11\\n40140639號"), so isolate the block between labels before
  applying the fine-grained pattern rather than trying to guess wrap points.

Fields this cannot read reliably from the appeal letter alone — the
appellant's address, and anything about service (送達) of the original
disposition — are left as `None` rather than guessed. That is a deliberate
scope boundary (docs/協作設計/06 §5.2), not a bug: a wrong guess here would
be worse than leaving the field for human editing via `PATCH /facts`.
"""

from __future__ import annotations

import re

_ROC_YEAR_OFFSET = 1911

_ALL_FIELD_PATHS = (
    'appellant.name',
    'appellant.address',
    'disposition.authority',
    'disposition.doc_no',
    'disposition.date',
    'service.date',
    'service.method',
    'appeal.filed_date',
)


def extract_appeal_fields(text: str) -> dict[str, str | None]:
    """Best-effort extraction; any field it cannot read confidently is None."""
    fields: dict[str, str | None] = dict.fromkeys(_ALL_FIELD_PATHS)
    fields['appellant.name'] = _extract_appellant_name(text)
    fields['disposition.authority'] = _extract_disposition_authority(text)
    fields['disposition.doc_no'] = _extract_disposition_doc_no(text)
    fields['disposition.date'] = _extract_disposition_date(text)
    fields['appeal.filed_date'] = _extract_appeal_filed_date(text)
    return fields


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r'\s+', '', value.replace('　', ''))
    return value or None


def _roc_to_iso(roc_year: int, month: int, day: int) -> str | None:
    try:
        from datetime import date

        return date(roc_year + _ROC_YEAR_OFFSET, month, day).isoformat()
    except ValueError:
        return None


def _extract_appellant_name(text: str) -> str | None:
    match = re.search(r'訴\s*願\s*人\s*[:：]\s*([^\n]+)', text)
    return _clean(match.group(1)) if match else None


def _extract_disposition_authority(text: str) -> str | None:
    match = re.search(r'原行政處分機關\s*\n?\s*([^\n]+?)\s*\n?\s*受理訴願機關', text)
    return _clean(match.group(1)) if match else None


def _extract_disposition_doc_no(text: str) -> str | None:
    block = _isolate_block(text, r'發文日期及文號', r'行政處分之年')
    if block is None:
        return None
    # The block is "<ROC date><authority abbreviation>字第<number>號..."; anchor
    # past the date so the greedy CJK run doesn't swallow the trailing 日 of it.
    match = re.search(r'\d+年\d+月\d+日([一-鿿]+字第[0-9A-Za-z]+號)', block)
    return match.group(1) if match else None


def _extract_disposition_date(text: str) -> str | None:
    block = _isolate_block(text, r'行政處分之年\s*月\s*日', r'本訴願事件')
    return _first_roc_date(block) if block else None


def _extract_appeal_filed_date(text: str) -> str | None:
    """Filing date sits right after the signature-line appellant name.

    Anchoring there (rather than "the last ROC date in the document")
    avoids picking up the disposition date, which also reads as
    "中華民國...年...月...日" but means something else.
    """
    name_match = re.search(r'訴\s*願\s*人\s*[:：]\s*[^\n]+', text)
    if name_match is None:
        return None
    return _first_roc_date(text[name_match.end():])


_NARRATIVE_END_MARKERS = (r'檢附之證據或附件', r'此\s*致')


def extract_case_narrative(text: str) -> str | None:
    """事實／理由段落，供 選法規 拿去當 BM25 查詢字串用。

    這段是全文裡唯一可能出現實體法規名稱與條號的地方；前面的表頭
    （稱謂／姓名／…）與後面的結尾格式（檢附之證據或附件、此致、簽名）
    只是樣板文字，混進查詢只會稀釋真正有意義的詞。抓不到「事實：」這個
    標籤就回 None，不要拿整份文件頂替——那樣搜出來的法規會被表頭雜訊
    帶偏。
    """
    start = re.search(r'事\s*實[：:]', text)
    if start is None:
        return None
    tail = text[start.end():]
    end_pos = len(tail)
    for marker in _NARRATIVE_END_MARKERS:
        end_match = re.search(marker, tail)
        if end_match is not None:
            end_pos = min(end_pos, end_match.start())
    narrative = re.sub(r'\s+', '', tail[:end_pos])
    return narrative or None


def _isolate_block(text: str, start_label: str, end_label: str) -> str | None:
    match = re.search(f'{start_label}(.*?){end_label}', text, re.S)
    if match is None:
        return None
    return re.sub(r'\s+', '', match.group(1))


def _first_roc_date(text: str) -> str | None:
    match = re.search(r'中\s*華\s*民\s*國\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', text)
    if match is None:
        return None
    roc_year, month, day = (int(group) for group in match.groups())
    return _roc_to_iso(roc_year, month, day)
