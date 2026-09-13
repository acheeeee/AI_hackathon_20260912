"""Article 77 branching: facts, absence, timing and cross-clause isolation."""

from datetime import date, datetime

import pytest

from caseapi.domain.appeal_deadline import review_appeal_deadline
from caseapi.domain.article77 import review_article_77
from caseapi.schemas.facts import FactFieldChange


def assess(clause: int, facts: dict[str, str], *, today: date = date(2026, 9, 1)):
    review = review_appeal_deadline(
        service_date=facts.get('service.date'),
        filed_date=facts.get('appeal.received_date') or facts.get('appeal.filed_date'),
    )
    return review_article_77(facts=facts, deadline_review=review, as_of=today)[clause - 1]


@pytest.mark.parametrize(('clause', 'clear', 'trigger'), [
    (1, {'appeal.form_defect': 'no'},
     {'appeal.form_defect': 'yes', 'appeal.defect_remediable': 'no'}),
    (2, {'service.date': '2026-07-01', 'appeal.received_date': '2026-07-31',
         'appeal.initial_submission_method': 'written'},
     {'service.date': '2026-07-01', 'appeal.received_date': '2026-08-01',
      'appeal.initial_submission_method': 'written'}),
    (3, {'appellant.standing': 'recipient'}, {'appellant.standing': 'not_eligible'}),
    (4, {'appellant.capacity': 'capable'},
     {'appellant.capacity': 'incapable', 'legal_representative.present': 'no',
      'appeal.correction_scope': 'capacity', 'appeal.correction_notified': 'yes',
      'appeal.correction_deadline': '2026-08-01', 'appeal.correction_completed': 'no'}),
    (5, {'appellant.entity_type': 'legal_person', 'representative.name': '林明',
         'representative.authority': 'yes'},
     {'appellant.entity_type': 'legal_person', 'representative.authority': 'no',
      'appeal.correction_scope': 'representation', 'appeal.correction_notified': 'yes',
      'appeal.correction_deadline': '2026-08-01', 'appeal.correction_completed': 'no'}),
    (6, {'disposition.current_status': 'exists'}, {'disposition.current_status': 'revoked'}),
    (7, {'case.prior_decision_record': 'no', 'case.prior_withdrawal_record': 'no'},
     {'case.prior_withdrawal_record': 'yes'}),
    (8, {'challenged_act.type': 'administrative_disposition',
         'challenged_act.within_appeal_scope': 'yes'},
     {'challenged_act.type': 'non_administrative'}),
])
def test_each_clause_changes_with_confirmed_facts(clause, clear, trigger):
    assert assess(clause, clear).status == 'NOT_TRIGGERED'
    assert assess(clause, trigger).status == 'TRIGGERED'
    assert assess(clause, {}).status == 'INSUFFICIENT_EVIDENCE'
    assert assess(clause, clear).evaluation_mode == 'rule'


def test_correction_requires_procedural_notice_and_matching_scope():
    facts = {'appeal.form_defect': 'yes', 'appeal.defect_remediable': 'yes',
             'appeal.correction_deadline': '2026-08-01',
             'appeal.correction_completed': 'no'}
    result = assess(1, facts)
    assert result.status == 'INSUFFICIENT_EVIDENCE'
    assert 'appeal.correction_scope' in result.missing_fields
    facts.update({'appeal.correction_scope': 'capacity', 'appeal.correction_notified': 'yes'})
    assert assess(1, facts).status == 'INSUFFICIENT_EVIDENCE'
    facts['appeal.correction_scope'] = 'form'
    facts['appeal.correction_notified'] = 'no'
    assert assess(1, facts).status == 'NOT_TRIGGERED'


@pytest.mark.parametrize(('clause', 'facts'), [
    (1, {'appeal.form_defect': 'yes', 'appeal.defect_remediable': 'yes'}),
    (4, {'appellant.capacity': 'incapable', 'legal_representative.present': 'no'}),
    (5, {'appellant.entity_type': 'legal_person', 'representative.authority': 'no'}),
])
def test_no_correction_notice_never_requires_inventing_a_scope(clause, facts):
    result = assess(clause, {**facts, 'appeal.correction_notified': 'no'})
    assert result.status == 'NOT_TRIGGERED'
    assert result.missing_fields == ()
    result = assess(clause, {**facts, 'appeal.correction_notified': 'yes'})
    assert result.status == 'INSUFFICIENT_EVIDENCE'
    assert result.missing_fields == ('appeal.correction_scope',)


@pytest.mark.parametrize(('completed', 'completion_date', 'today', 'status'), [
    ('no', None, date(2026, 8, 1), 'NOT_TRIGGERED'),
    ('no', None, date(2026, 8, 2), 'TRIGGERED'),
    ('yes', '2026-08-01', date(2026, 8, 2), 'NOT_TRIGGERED'),
    ('yes', '2026-08-02', date(2026, 8, 3), 'TRIGGERED'),
    ('yes', None, date(2026, 8, 3), 'INSUFFICIENT_EVIDENCE'),
    ('yes', '2026-08-02', date(2026, 8, 1), 'NEEDS_HUMAN'),
])
def test_correction_deadline_boundaries(completed, completion_date, today, status):
    facts = {'appeal.form_defect': 'yes', 'appeal.defect_remediable': 'yes',
             'appeal.correction_scope': 'form', 'appeal.correction_notified': 'yes',
             'appeal.correction_deadline': '2026-08-01',
             'appeal.correction_completed': completed}
    if completion_date:
        facts['appeal.correction_date'] = completion_date
    assert assess(1, facts, today=today).status == status


def test_missing_booleans_are_not_false_and_inactive_fields_are_not_required():
    result = assess(7, {'case.prior_decision_record': 'no'})
    assert result.status == 'INSUFFICIENT_EVIDENCE'
    assert result.missing_fields == ('case.prior_withdrawal_record',)
    result = assess(1, {'appeal.form_defect': 'no'})
    assert result.missing_fields == ()
    assert 'appeal.correction_deadline' in result.input
    assert assess(5, {'appellant.entity_type': 'individual'}).status == 'NOT_APPLICABLE'


@pytest.mark.parametrize(('field', 'value', 'clause'), [
    ('appellant.standing', 'uncertain', 3),
    ('appellant.capacity', 'uncertain', 4),
    ('disposition.current_status', 'uncertain', 6),
    ('challenged_act.type', 'uncertain', 8),
])
def test_ambiguous_legal_facts_request_human_review(field, value, clause):
    assert assess(clause, {field: value}).status == 'NEEDS_HUMAN'


def test_received_date_takes_priority_over_signature_date():
    result = assess(2, {'service.date': '2026-07-01', 'appeal.filed_date': '2026-07-10',
                        'appeal.received_date': '2026-08-01',
                        'appeal.initial_submission_method': 'written'})
    assert result.status == 'TRIGGERED'
    assert result.input['computed.days_from_deadline'] == 1


@pytest.mark.parametrize(('objection', 'written', 'completed', 'today', 'status'), [
    ('2026-07-20', '2026-08-19', 'yes', date(2026, 8, 20), 'NOT_TRIGGERED'),
    ('2026-07-20', '2026-08-20', 'yes', date(2026, 8, 21), 'TRIGGERED'),
    ('2026-08-01', '2026-08-02', 'yes', date(2026, 8, 3), 'TRIGGERED'),
    ('2026-07-20', None, 'no', date(2026, 8, 19), 'NOT_TRIGGERED'),
    ('2026-07-20', None, 'no', date(2026, 8, 20), 'TRIGGERED'),
    ('2026-07-20', None, None, date(2026, 8, 20), 'INSUFFICIENT_EVIDENCE'),
    ('2026-07-20', '2026-07-19', 'yes', date(2026, 8, 20), 'NEEDS_HUMAN'),
])
def test_article57_indication_and_followup_are_separate_branches(
    objection, written, completed, today, status,
):
    facts = {'service.date': '2026-07-01', 'appeal.initial_submission_method': 'objection',
             'appeal.objection_date': objection}
    if written:
        facts['appeal.written_submission_date'] = written
    if completed:
        facts['appeal.written_submission_completed'] = completed
    result = assess(2, facts, today=today)
    assert result.status == status
    assert '第57條' in result.rule_description


def test_article57_late_followup_triggers_even_when_service_date_is_missing():
    result = assess(2, {'appeal.initial_submission_method': 'objection',
                        'appeal.objection_date': '2026-07-01',
                        'appeal.written_submission_completed': 'yes',
                        'appeal.written_submission_date': '2026-08-02'})
    assert result.status == 'TRIGGERED'


@pytest.mark.parametrize(('field', 'value'), [
    ('appellant.capacity', 'anything'),
    ('appeal.correction_completed', False),
    ('appeal.form_defect', 'false'),
    ('appeal.correction_deadline', '2026-02-30'),
    ('appeal.objection_date', '2026-7-1'),
    ('appeal.written_submission_date', 20260701),
    ('appeal.received_date', '2026-02-30'),
])
def test_fact_boundary_rejects_invalid_procedural_data(field, value):
    with pytest.raises(ValueError):
        FactFieldChange(field_path=field, value=value, reason='欄位驗證')


@pytest.mark.parametrize(('field', 'value'), [
    ('appellant.capacity', 'capable'),
    ('appellant.entity_type', 'local_government'),
    ('appeal.correction_completed', 'no'),
    ('appeal.correction_deadline', '2026-07-31'),
    ('appellant.standing', None),
])
def test_fact_boundary_accepts_supported_values_and_explicit_clearing(field, value):
    assert FactFieldChange(field_path=field, value=value, reason='人工確認').value == value


def test_extreme_valid_service_date_does_not_overflow_the_period_calculator():
    review = review_appeal_deadline(service_date='9999-12-31', filed_date=None)
    assert review.status == 'insufficient_data'
    assert '日期超出' in str(review.caveats)


def test_extreme_objection_date_does_not_overflow_the_computed_field():
    result = assess(2, {'appeal.initial_submission_method': 'objection',
                        'appeal.objection_date': '9999-12-31'}, today=date.max)
    assert result.status == 'NEEDS_HUMAN'
    assert result.input.get('computed.written_submission_deadline') is None


def test_default_review_day_uses_taipei_timezone(monkeypatch):
    zones = []

    class Clock:
        @staticmethod
        def now(zone):
            zones.append(zone.key)
            return datetime(2026, 9, 2, 4, 0, tzinfo=zone)

    monkeypatch.setattr('caseapi.domain.article77.datetime', Clock)
    facts = {'appeal.form_defect': 'yes', 'appeal.defect_remediable': 'yes',
             'appeal.correction_scope': 'form', 'appeal.correction_notified': 'yes',
             'appeal.correction_deadline': '2026-09-01', 'appeal.correction_completed': 'no'}
    review = review_appeal_deadline(service_date=None, filed_date=None)
    assert review_article_77(facts=facts, deadline_review=review)[0].status == 'TRIGGERED'
    assert zones == ['Asia/Taipei']
