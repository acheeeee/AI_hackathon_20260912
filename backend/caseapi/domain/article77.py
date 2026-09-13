"""Fact-dependent Article 77 checks; outputs remain preliminary procedural findings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from caseapi.domain.appeal_deadline import (
    DeadlineReview, STATUS_OVERDUE, STATUS_WITHIN_PERIOD, calendar_period_end,
    review_appeal_deadline,
)
from caseapi.domain.procedural_fields import validate_procedural_field_value

OUTCOME_NOT_TRIGGERED = 'NOT_TRIGGERED'
OUTCOME_TRIGGERED = 'TRIGGERED'
OUTCOME_NOT_APPLICABLE = 'NOT_APPLICABLE'
OUTCOME_INSUFFICIENT = 'INSUFFICIENT_EVIDENCE'
OUTCOME_NEEDS_HUMAN = 'NEEDS_HUMAN'
MODE_RULE = 'rule'
MODE_MANUAL_REVIEW = 'manual_review'
InputValue = str | int | bool | None

_CORRECTION_FIELDS = (
    'appeal.correction_scope', 'appeal.correction_notified',
    'appeal.correction_deadline', 'appeal.correction_completed', 'appeal.correction_date',
)
_INPUT_FIELDS = {
    1: ('appeal.form_defect', 'appeal.defect_remediable', *_CORRECTION_FIELDS),
    2: ('service.date', 'appeal.received_date', 'appeal.filed_date',
        'appeal.initial_submission_method', 'appeal.objection_date',
        'appeal.written_submission_completed', 'appeal.written_submission_date'),
    3: ('appellant.name', 'disposition.recipient', 'appellant.standing'),
    4: ('appellant.capacity', 'legal_representative.present', *_CORRECTION_FIELDS),
    5: ('appellant.entity_type', 'representative.name', 'representative.authority',
        *_CORRECTION_FIELDS),
    6: ('disposition.doc_no', 'disposition.current_status'),
    7: ('case.prior_decision_record', 'case.prior_withdrawal_record'),
    8: ('challenged_act.type', 'challenged_act.within_appeal_scope'),
}
_DESCRIPTIONS = {
    1: '檢查訴願書法定程式：不能補正的欠缺，或已通知限期補正而逾期未完成的欠缺，標記本款條件。',
    2: '依第14條試算提起期間；先作不服表示者另依第57條但書檢查自表示日起三十日內補送訴願書。兩分支任一逾期即標記。',
    3: '依已確認的訴願人資格，檢查是否為第18條的處分相對人或法律上利害關係人。',
    4: '檢查欠缺訴願能力者是否由法定代理人代為訴願；未代理者須經通知限期補正而逾期未完成，才標記本款條件。',
    5: '檢查法人、非法人團體及地方自治團體是否由代表人或管理人為訴願行為；未符合者須經通知限期補正而逾期未完成，才標記本款條件。',
    6: '依已確認的原行政處分目前狀態，檢查原處分是否已不存在。',
    7: '檢查同一事件是否已有訴願決定或曾撤回訴願，而又再次提起。任一紀錄經確認即標記本款條件。',
    8: '依已確認的法律性質與救濟範圍，檢查是否對非行政處分或依法不屬訴願救濟範圍的事項提起。',
}


@dataclass(frozen=True)
class Article77Assessment:
    clause_no: int
    rule_id: str
    input: dict[str, InputValue]
    status: str
    rule_description: str
    reason: str
    evaluation_mode: str
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Result:
    status: str
    reason: str
    missing_fields: tuple[str, ...] = ()


def _missing(*paths: str, reason: str = '尚缺本分支所需的確認資料。') -> _Result:
    return _Result(OUTCOME_INSUFFICIENT, reason, paths)


def _clear(reason: str) -> _Result:
    return _Result(OUTCOME_NOT_TRIGGERED, reason)


def _trigger(reason: str) -> _Result:
    return _Result(OUTCOME_TRIGGERED, reason)


def _human(reason: str) -> _Result:
    return _Result(OUTCOME_NEEDS_HUMAN, reason)


def _day(facts: Mapping[str, InputValue], path: str) -> date | None:
    value = facts.get(path)
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def review_article_77(
    *, facts: Mapping[str, InputValue], deadline_review: DeadlineReview,
    as_of: date | None = None,
) -> tuple[Article77Assessment, ...]:
    """Evaluate each independent clause; unknown values never imply negative facts."""
    today = as_of or datetime.now(ZoneInfo('Asia/Taipei')).date()
    method = facts.get('appeal.initial_submission_method')
    effective_date = (facts.get('appeal.objection_date') if method == 'objection'
                      else facts.get('appeal.received_date') or facts.get('appeal.filed_date'))
    period = review_appeal_deadline(
        service_date=facts.get('service.date') if isinstance(facts.get('service.date'), str) else None,
        filed_date=effective_date if isinstance(effective_date, str) else None,
    ) if method in ('written', 'objection') else deadline_review
    results = []
    for clause in range(1, 9):
        inputs = {path: facts.get(path) for path in _INPUT_FIELDS[clause]}
        invalid = []
        for path, value in inputs.items():
            try:
                validate_procedural_field_value(path, value)
            except ValueError:
                invalid.append(path)
        if invalid:
            result = _Result(OUTCOME_NEEDS_HUMAN, '既有資料含無效選項或日期，請更正後重算。', tuple(invalid))
        elif clause == 1:
            result = _form(facts, today)
        elif clause == 2:
            result = _filing(facts, period, today)
        elif clause == 3:
            result = _standing(facts)
        elif clause == 4:
            result = _capacity(facts, today)
        elif clause == 5:
            result = _representation(facts, today)
        elif clause == 6:
            result = _disposition(facts)
        elif clause == 7:
            result = _prior_case(facts)
        else:
            result = _scope(facts)
        if clause == 2:
            inputs.update({'computed.deadline_date': period.deadline_date,
                           'computed.days_from_deadline': period.days_from_deadline})
            objection = _day(facts, 'appeal.objection_date')
            if method == 'objection' and objection:
                followup_deadline = calendar_period_end(objection)
                inputs['computed.written_submission_deadline'] = (
                    followup_deadline.isoformat() if followup_deadline else None
                )
        results.append(Article77Assessment(
            clause_no=clause, rule_id=f'art77_para{clause}', input=inputs,
            status=result.status, rule_description=_DESCRIPTIONS[clause],
            reason=result.reason,
            evaluation_mode=MODE_MANUAL_REVIEW if result.status == OUTCOME_NEEDS_HUMAN else MODE_RULE,
            missing_fields=result.missing_fields,
        ))
    return tuple(results)


def _correction(facts: Mapping[str, InputValue], scope: str, today: date) -> _Result:
    if facts.get('appeal.correction_scope') not in (scope, 'all'):
        return _missing('appeal.correction_scope', reason='尚無涵蓋本款欠缺的訴願程序補正紀錄。')
    notified = facts.get('appeal.correction_notified')
    if notified == 'no':
        return _clear('尚未通知限期補正，目前未符合「經通知而逾期未補正」條件。')
    if notified != 'yes':
        return _missing('appeal.correction_notified')
    deadline = _day(facts, 'appeal.correction_deadline')
    if deadline is None:
        return _missing('appeal.correction_deadline')
    completed = facts.get('appeal.correction_completed')
    completion = _day(facts, 'appeal.correction_date')
    if completion and (completion > today or completed == 'no'):
        return _human('補正日期與目前日期或完成狀態矛盾，請核對。')
    if completed == 'yes':
        if completion is None:
            return _missing('appeal.correction_date')
        if completion <= deadline:
            return _clear(f'已於 {completion} 完成補正，未逾 {deadline} 期限。')
        return _trigger(f'補正日期 {completion} 晚於通知期限 {deadline}，標記逾期補正。')
    if today <= deadline:
        return _clear(f'補正期限為 {deadline}，截至 {today} 尚未屆滿，待期限後確認。')
    if completed == 'no':
        return _trigger(f'已通知限期補正，期限 {deadline} 已屆滿且確認尚未完成補正。')
    return _missing('appeal.correction_completed')


def _form(facts: Mapping[str, InputValue], today: date) -> _Result:
    if facts.get('appeal.form_defect') == 'no':
        return _clear('已確認訴願書符合本款所檢查的法定程式。')
    if facts.get('appeal.form_defect') != 'yes':
        return _missing('appeal.form_defect')
    if facts.get('appeal.defect_remediable') == 'no':
        return _trigger('已確認訴願書有不能補正的法定程式欠缺。')
    if facts.get('appeal.defect_remediable') != 'yes':
        return _missing('appeal.defect_remediable')
    return _correction(facts, 'form', today)


def _filing(facts: Mapping[str, InputValue], period: DeadlineReview, today: date) -> _Result:
    method = facts.get('appeal.initial_submission_method')
    if method not in ('written', 'objection'):
        return _missing('appeal.initial_submission_method',
                        reason='請確認最初提出方式，才能選擇書面訴願或第57條補送訴願書的期間分支。')
    initial = (_day(facts, 'appeal.objection_date') if method == 'objection' else
               _day(facts, 'appeal.received_date') or _day(facts, 'appeal.filed_date'))
    service = _day(facts, 'service.date')
    if initial and (initial > today or (service and initial < service)):
        return _human('提起／不服表示日期早於送達或晚於目前日期，需核對日期及起算基礎。')
    if period.status == STATUS_OVERDUE:
        return _trigger(f'提起／不服表示日晚於第14條試算期限 {period.deadline_date} 共 {period.days_from_deadline} 天。')
    followup = _supplement(facts, today) if method == 'objection' else None
    if followup and followup.status in (OUTCOME_TRIGGERED, OUTCOME_NEEDS_HUMAN):
        return followup
    if period.status != STATUS_WITHIN_PERIOD:
        missing = ('service.date',) if service is None else (
            'appeal.objection_date' if method == 'objection' else 'appeal.received_date',
        )
        if followup and followup.status == OUTCOME_INSUFFICIENT:
            missing = tuple(dict.fromkeys((*missing, *followup.missing_fields)))
        return _missing(*missing, reason='尚缺第14條期間試算所需日期，不能排除逾期分支。')
    if followup:
        return followup
    return _clear(f'訴願書已於第14條試算期限 {period.deadline_date} 內提出；不適用第57條補送分支。')


def _supplement(facts: Mapping[str, InputValue], today: date) -> _Result:
    objection = _day(facts, 'appeal.objection_date')
    if objection is None:
        return _missing('appeal.objection_date')
    deadline = calendar_period_end(objection)
    if deadline is None:
        return _human('不服表示日期超出可計算範圍，請更正或人工核對第57條期間。')
    completed = facts.get('appeal.written_submission_completed')
    submitted = _day(facts, 'appeal.written_submission_date')
    if submitted and (submitted < objection or submitted > today or completed == 'no'):
        return _human('補送訴願書日期與不服表示日、目前日期或完成狀態矛盾，請核對。')
    if completed == 'yes':
        if submitted is None:
            return _missing('appeal.written_submission_date')
        if submitted > deadline:
            return _trigger(f'第57條補送訴願書日期 {submitted} 晚於自不服表示起三十日期限 {deadline}。')
        return _clear(f'不服表示在第14條期間內，且已於第57條試算期限 {deadline} 內補送訴願書。')
    if today <= deadline:
        return _clear(f'不服表示在第14條期間內，第57條補送期限 {deadline} 尚未屆滿，待後續補送確認。')
    if completed == 'no':
        return _trigger(f'第57條補送期限 {deadline} 已屆滿，確認尚未補送訴願書。')
    return _missing('appeal.written_submission_completed')


def _standing(facts: Mapping[str, InputValue]) -> _Result:
    value = facts.get('appellant.standing')
    if value in ('recipient', 'interested'):
        return _clear('已確認訴願人為處分相對人或法律上利害關係人，符合第18條資格。')
    if value == 'not_eligible':
        return _trigger('已確認訴願人不符合第18條資格，標記本款條件。')
    if value == 'uncertain':
        return _human('訴願人與處分的法律上關係尚需人工判斷。')
    return _missing('appellant.standing')


def _capacity(facts: Mapping[str, InputValue], today: date) -> _Result:
    value = facts.get('appellant.capacity')
    if value == 'capable':
        return _clear('已確認具備訴願能力，本款欠缺能力的前提未成立。')
    if value == 'uncertain':
        return _human('訴願能力尚需人工判斷。')
    if value != 'incapable':
        return _missing('appellant.capacity')
    represented = facts.get('legal_representative.present')
    if represented == 'yes':
        return _clear('欠缺訴願能力者已由法定代理人代為訴願。')
    if represented != 'no':
        return _missing('legal_representative.present')
    return _correction(facts, 'capacity', today)


def _representation(facts: Mapping[str, InputValue], today: date) -> _Result:
    entity = facts.get('appellant.entity_type')
    if entity == 'individual':
        return _Result(OUTCOME_NOT_APPLICABLE, '訴願人為自然人，不適用本款團體代表的條件。')
    if entity is None:
        return _missing('appellant.entity_type')
    authority = facts.get('representative.authority')
    if authority == 'uncertain':
        return _human('代表人或管理人的權限尚需人工確認。')
    if authority == 'yes':
        if not facts.get('representative.name'):
            return _missing('representative.name')
        return _clear('團體已由確認有權的代表人或管理人為訴願行為。')
    if authority != 'no':
        return _missing('representative.authority')
    return _correction(facts, 'representation', today)


def _disposition(facts: Mapping[str, InputValue]) -> _Result:
    value = facts.get('disposition.current_status')
    if value == 'exists':
        return _clear('已確認原行政處分仍存在。')
    if value in ('revoked', 'abolished', 'nonexistent'):
        return _trigger('已確認原行政處分已不存在，標記本款條件。')
    if value == 'uncertain':
        return _human('原行政處分是否仍存在尚需人工確認。')
    return _missing('disposition.current_status')


def _prior_case(facts: Mapping[str, InputValue]) -> _Result:
    paths = _INPUT_FIELDS[7]
    if any(facts.get(path) == 'yes' for path in paths):
        return _trigger('已確認同一事件有前次決定或撤回紀錄，而再次提起。')
    missing = tuple(path for path in paths if facts.get(path) != 'no')
    if missing:
        return _missing(*missing, reason='需確認同一事件的前次決定及撤回紀錄，缺值不視為沒有紀錄。')
    return _clear('已確認同一事件沒有前次訴願決定，也未曾撤回訴願。')


def _scope(facts: Mapping[str, InputValue]) -> _Result:
    nature = facts.get('challenged_act.type')
    scope = facts.get('challenged_act.within_appeal_scope')
    if nature == 'non_administrative' or scope == 'no':
        return _trigger('已確認為非行政處分，或依法不屬訴願救濟範圍，標記本款條件。')
    if nature == 'uncertain' or scope == 'uncertain':
        return _human('法律性質或訴願救濟範圍尚需人工判斷。')
    missing = tuple(path for path in _INPUT_FIELDS[8] if facts.get(path) is None)
    if missing:
        return _missing(*missing)
    return _clear('已確認被爭執事項為行政處分，且屬訴願救濟範圍。')
