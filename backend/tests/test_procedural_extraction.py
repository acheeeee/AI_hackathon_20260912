"""Source-backed procedural facts must work on both new and existing cases."""

from pathlib import Path

import pytest

from caseapi.db.connection import connect
from caseapi.services.intake_service import extract_pdf_text
from conftest import create_case, mutate, new_key


def _extract(text: str, role: str = 'appeal') -> dict:
    from caseapi.domain.procedural_extraction import extract_procedural_fields

    return extract_procedural_fields(text, document_role=role)


def test_explicit_procedural_statements_supply_values_and_exact_quotes() -> None:
    text = (
        '原處分於民國115年6月15日送達。本訴願自始以書面提出。'
        '訴願人具有訴願能力。原處分目前尚未撤銷或廢止。'
        '本事件此前未經訴願決定，亦未曾撤回後重行提起。'
    )
    fields = _extract(text)
    expected = {
        'service.date': '2026-06-15',
        'appeal.initial_submission_method': 'written',
        'appellant.capacity': 'capable',
        'disposition.current_status': 'exists',
        'case.prior_decision_record': 'no',
        'case.prior_withdrawal_record': 'no',
    }
    for path, value in expected.items():
        assert fields[path]['value'] == value
        assert fields[path]['quote'] in text
        assert text[fields[path]['start']:fields[path]['end']] == fields[path]['quote']


def test_application_correction_and_remedy_instruction_are_not_appeal_facts() -> None:
    text = (
        '原處分機關命登記申請人於115年6月1日前補正，逾期未補正。'
        '該補正通知於115年5月18日送達。請求撤銷原處分。'
        '如不服本處分，得於三十日內提起訴願。'
    )
    fields = _extract(text)
    assert 'service.date' not in fields
    assert not any(path.startswith('appeal.correction_') for path in fields)
    assert 'disposition.current_status' not in fields
    assert 'appeal.initial_submission_method' not in fields
    assert 'case.prior_decision_record' not in fields


@pytest.mark.parametrize('text', [
    '未確認訴願人具有訴願能力。',
    '假設原處分已撤銷。',
    '若訴願書符合法定程式，則繼續審理。',
])
def test_conditional_or_uncertain_statements_do_not_become_conclusive_facts(text: str) -> None:
    assert not _extract(text)


def test_contradictory_statements_remain_unresolved() -> None:
    fields = _extract('原處分目前仍然存在。原處分已撤銷。')
    assert fields['disposition.current_status']['value'] is None
    assert fields['disposition.current_status']['conflict'] is True


def test_new_demo_intake_seeds_source_backed_procedural_fields(client) -> None:
    root = Path(__file__).resolve().parents[2] / 'data' / 'demo'
    appeal = root / '展示用_虛擬資產服務登記_訴願書.pdf'
    disposition = root / '展示用_虛擬資產服務登記_行政處分函.pdf'
    response = client.post('/api/v1/cases/intake', headers={'Idempotency-Key': new_key()}, files={
        'appeal_pdf': ('appeal.pdf', appeal.read_bytes(), 'application/pdf'),
        'disposition_pdf': ('disposition.pdf', disposition.read_bytes(), 'application/pdf'),
    })
    assert response.status_code == 201
    case_id = response.json()['data']['case_id']
    fields = client.get(f'/api/v1/cases/{case_id}/facts').json()['data']['fields']
    assert fields['service.date']['value'] == '2026-06-15'
    assert fields['appeal.initial_submission_method']['value'] == 'written'
    assert fields['case.prior_decision_record']['value'] == 'no'
    assert fields['case.prior_withdrawal_record']['value'] == 'no'
    assert fields['appellant.entity_type']['value'] == 'legal_person'
    assert fields['service.date']['origin'] == 'program'
    source = fields['service.date']['source']
    assert source['document_id']
    assert source['source_sha256']
    assert source['quote']
    assert 'appeal.correction_deadline' not in fields


def test_existing_documents_are_reexamined_without_mutation_and_human_clear_wins(client, settings) -> None:
    case_id = create_case(client)
    other_case_id = create_case(client)
    with connect(settings.db_path) as db:
        for doc_id, target, body in [
            ('doc_this', case_id, '原處分於115年6月15日送達。本訴願自始以書面提出。'),
            ('doc_other', other_case_id, '原處分於115年1月1日送達。'),
        ]:
            db.execute(
                'INSERT INTO case_documents (id, case_id, document_role, source_filename, '
                'source_sha256, content_blob, extracted_text, page_count, created_by, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (doc_id, target, 'appeal', 'test.pdf', 'a' * 64, b'%PDF', body, 1,
                 'actor_test', '2026-09-13T00:00:00Z'),
            )
        db.commit()
    before = client.get(f'/api/v1/cases/{case_id}').json()['data']['case_revision']
    response = client.get(f'/api/v1/cases/{case_id}/procedural-review')
    assert response.status_code == 200
    second = response.json()['data']['clause_assessments'][1]
    assert second['input']['service.date'] == '2026-06-15'
    assert second['input_sources']['service.date']['source']['document_id'] == 'doc_this'
    assert client.get(f'/api/v1/cases/{case_id}').json()['data']['case_revision'] == before

    changed = mutate(client, 'PATCH', f'/api/v1/cases/{case_id}/facts', {
        'expected_case_revision': before, 'reason': '人工確認送達日尚待核對',
        'field_changes': [{'field_path': 'service.date', 'value': None,
                           'human_asserted': True, 'reason': '回執未確認'}],
    })
    assert changed.status_code == 200
    second = client.get(f'/api/v1/cases/{case_id}/procedural-review').json()['data']['clause_assessments'][1]
    assert second['input']['service.date'] is None
    assert second['input_sources']['service.date']['origin'] == 'human'
