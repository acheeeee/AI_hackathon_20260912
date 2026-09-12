"""訴願法第14條的三十日期間計算（程序審查）。

只算日曆天數，不處理國定假日順延（行政程序法§48 IV 需要假日曆，沒有就不裝
懂）；沒有送達日期就不算，不拿處分日期偷偷頂替——處分日期不等於送達日期，
用它算會低估期限，可能把還沒過期的案件誤判成逾期。這裡只產生「計算過程與
依據法條」，不是不受理與否的最終認定。
"""

from caseapi.domain.appeal_deadline import (
    STATUS_DEADLINE_KNOWN,
    STATUS_INSUFFICIENT,
    STATUS_OVERDUE,
    STATUS_WITHIN_PERIOD,
    review_appeal_deadline,
)


def test_missing_service_date_is_insufficient_data_not_a_guess() -> None:
    review = review_appeal_deadline(service_date=None, filed_date='2025-08-01')

    assert review.status == STATUS_INSUFFICIENT
    assert review.deadline_date is None
    assert review.missing_fields == ('service.date',)


def test_service_date_alone_computes_a_deadline_but_cannot_judge_timeliness() -> None:
    review = review_appeal_deadline(service_date='2025-07-01', filed_date=None)

    assert review.status == STATUS_DEADLINE_KNOWN
    assert review.deadline_date == '2025-07-31'
    assert review.days_from_deadline is None
    assert review.missing_fields == ('appeal.filed_date',)


def test_filed_exactly_on_the_deadline_is_within_period() -> None:
    review = review_appeal_deadline(service_date='2025-07-01', filed_date='2025-07-31')

    assert review.status == STATUS_WITHIN_PERIOD
    assert review.days_from_deadline == 0


def test_filed_one_day_after_the_deadline_is_overdue() -> None:
    review = review_appeal_deadline(service_date='2025-07-01', filed_date='2025-08-01')

    assert review.status == STATUS_OVERDUE
    assert review.days_from_deadline == 1


def test_filed_well_before_the_deadline_is_within_period() -> None:
    review = review_appeal_deadline(service_date='2025-07-01', filed_date='2025-07-10')

    assert review.status == STATUS_WITHIN_PERIOD
    assert review.days_from_deadline == -21


def test_the_service_date_itself_does_not_count_toward_the_thirty_days() -> None:
    # 民法第120條：始日不算入。服務日當天不算第一天，隔天起算。
    review = review_appeal_deadline(service_date='2025-01-01', filed_date='2025-01-31')

    assert review.status == STATUS_WITHIN_PERIOD
    assert review.days_from_deadline == 0


def test_unparseable_service_date_is_insufficient_data() -> None:
    review = review_appeal_deadline(service_date='114年7月1日', filed_date=None)

    assert review.status == STATUS_INSUFFICIENT
    assert review.missing_fields == ('service.date',)


def test_every_result_carries_the_statute_basis_and_a_holiday_caveat() -> None:
    review = review_appeal_deadline(service_date=None, filed_date=None)

    assert '訴願法第14條' in review.statute_basis
    assert any('假日' in caveat or '休息日' in caveat for caveat in review.caveats)
