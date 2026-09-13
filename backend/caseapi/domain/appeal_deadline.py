"""訴願法第14條的三十日期間計算（程序審查）。

只算日曆天數，不處理國定假日順延（行政程序法第48條第4項需要假日曆，這裡
沒有就明說限制，不裝懂）。沒有送達日期就回報缺資料，不拿處分日期頂替——
處分日期不等於送達日期，用它算會低估期限，可能把還沒過期的案件誤判成
逾期。這裡的輸出只是「計算過程與依據法條」，不是不受理與否的最終認定；
呼叫端（API 回應、前端畫面）必須自己標明未經法律覆核。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

APPEAL_PERIOD_DAYS = 30
STATUTE_BASIS = (
    '訴願法第14條第1項：訴願之提起，應自行政處分達到或公告期滿之次日起'
    '三十日內為之。'
)
_HOLIDAY_CAVEAT = '未考慮國定假日順延（行政程序法第48條第4項），僅算日曆天數。'

STATUS_INSUFFICIENT = 'insufficient_data'
STATUS_DEADLINE_KNOWN = 'deadline_known_filing_unknown'
STATUS_WITHIN_PERIOD = 'within_period'
STATUS_OVERDUE = 'overdue'


@dataclass(frozen=True)
class DeadlineReview:
    status: str
    deadline_date: str | None
    days_from_deadline: int | None
    """逾期天數；正值代表已逾期，0 或負值代表距期限還有幾天。"""
    missing_fields: tuple[str, ...]
    statute_basis: str
    caveats: tuple[str, ...]


def review_appeal_deadline(
    *, service_date: str | None, filed_date: str | None
) -> DeadlineReview:
    service = _parse_date(service_date) if service_date is not None else None
    if service is None:
        return _insufficient(missing=('service.date',))

    deadline = calendar_period_end(service)
    if deadline is None:
        return _insufficient(
            missing=('service.date',),
            caveat='日期超出可計算範圍，請更正送達日期或人工核對。',
        )
    filed = _parse_date(filed_date) if filed_date is not None else None
    if filed is None:
        return DeadlineReview(
            status=STATUS_DEADLINE_KNOWN,
            deadline_date=deadline.isoformat(),
            days_from_deadline=None,
            missing_fields=('appeal.filed_date',),
            statute_basis=STATUTE_BASIS,
            caveats=(_HOLIDAY_CAVEAT,),
        )

    days_from_deadline = (filed - deadline).days
    status = STATUS_OVERDUE if days_from_deadline > 0 else STATUS_WITHIN_PERIOD
    return DeadlineReview(
        status=status,
        deadline_date=deadline.isoformat(),
        days_from_deadline=days_from_deadline,
        missing_fields=(),
        statute_basis=STATUTE_BASIS,
        caveats=(_HOLIDAY_CAVEAT,),
    )


def calendar_period_end(start: date) -> date | None:
    """Return the calendar-day deadline, or None outside Python's date range."""
    try:
        return start + timedelta(days=APPEAL_PERIOD_DAYS)
    except OverflowError:
        return None


def _insufficient(*, missing: tuple[str, ...], caveat: str | None = None) -> DeadlineReview:
    return DeadlineReview(
        status=STATUS_INSUFFICIENT,
        deadline_date=None,
        days_from_deadline=None,
        missing_fields=missing,
        statute_basis=STATUTE_BASIS,
        caveats=(_HOLIDAY_CAVEAT, *((caveat,) if caveat else ())),
    )


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
