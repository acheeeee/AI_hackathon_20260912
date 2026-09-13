"""GET /cases/{case_id}/procedural-review：讀取當下 facts 即時算出期間審查。

沒有分析表、沒有快照——結果不持久化，每次都用目前的 facts 重算，跟
case_service._processing_status 的作法一致（見 06 §5.2）。
"""

from fastapi.testclient import TestClient

from conftest import create_case, mutate


ARTICLE_77_OUTCOMES = {
    'NOT_TRIGGERED',
    'TRIGGERED',
    'NOT_APPLICABLE',
    'INSUFFICIENT_EVIDENCE',
    'NEEDS_HUMAN',
}

def _patch_fact(client: TestClient, case_id: str, expected_revision: int, field_path: str, value: str):
    return mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/facts',
        {
            'expected_case_revision': expected_revision,
            'reason': '人工補值供程序審查測試',
            'field_changes': [
                {
                    'field_path': field_path,
                    'value': value,
                    'human_asserted': True,
                    'reason': '人工補值供程序審查測試',
                }
            ],
        },
    )


def test_review_with_no_facts_reports_missing_service_date(client: TestClient) -> None:
    case_id = create_case(client)

    response = client.get(f'/api/v1/cases/{case_id}/procedural-review')

    assert response.status_code == 200
    data = response.json()['data']
    assert data['status'] == 'insufficient_data'
    assert data['missing_fields'] == ['service.date']
    assert data['legal_review_status'] == 'not_reviewed'
    assert '訴願法第14條' in data['statute_basis']


def test_review_exposes_one_explicit_assessment_contract_for_each_article_77_clause(
    client: TestClient,
) -> None:
    """八款均依事實判斷，空案只缺其當前分支需要的資料。"""
    case_id = create_case(client)

    response = client.get(f'/api/v1/cases/{case_id}/procedural-review')

    assert response.status_code == 200
    assessments = response.json()['data']['clause_assessments']
    assert [item['clause_no'] for item in assessments] == list(range(1, 9))
    assert [item['rule_id'] for item in assessments] == [
        f'art77_para{clause_no}' for clause_no in range(1, 9)
    ]
    assert len({item['rule_id'] for item in assessments}) == 8

    for assessment in assessments:
        clause_no = assessment['clause_no']
        assert {
            'rule_id',
            'input',
            'status',
            'rule_description',
            'reason',
        } <= assessment.keys()
        assert isinstance(assessment['input'], dict)
        assert assessment['status'] in ARTICLE_77_OUTCOMES
        assert isinstance(assessment['rule_description'], str)
        assert assessment['rule_description'].strip()
        assert isinstance(assessment['reason'], str)
        assert assessment['reason'].strip()
        user_copy = f"{assessment['rule_description']} {assessment['reason']}"
        assert 'mock' not in user_copy.lower()
        assert 'demo' not in user_copy.lower()
        assert '示範' not in user_copy
        assert assessment['evaluation_mode'] == 'rule'
        assert assessment['status'] == 'INSUFFICIENT_EVIDENCE'
        assert assessment['missing_fields']


def test_review_with_only_service_date_gives_a_deadline_without_a_verdict(
    client: TestClient,
) -> None:
    case_id = create_case(client)
    _patch_fact(client, case_id, 1, 'service.date', '2025-07-01')

    response = client.get(f'/api/v1/cases/{case_id}/procedural-review')

    data = response.json()['data']
    assert data['status'] == 'deadline_known_filing_unknown'
    assert data['deadline_date'] == '2025-07-31'
    assert data['days_from_deadline'] is None
    assert data['missing_fields'] == ['appeal.filed_date']
    clause_2 = next(
        item for item in data['clause_assessments'] if item['clause_no'] == 2
    )
    assert clause_2['status'] == 'INSUFFICIENT_EVIDENCE'


def test_review_with_both_dates_computes_overdue(client: TestClient) -> None:
    case_id = create_case(client)
    _patch_fact(client, case_id, 1, 'service.date', '2025-07-01')
    _patch_fact(client, case_id, 2, 'appeal.filed_date', '2025-08-15')
    _patch_fact(client, case_id, 3, 'appeal.initial_submission_method', 'written')

    response = client.get(f'/api/v1/cases/{case_id}/procedural-review')

    data = response.json()['data']
    assert data['status'] == 'overdue'
    assert data['days_from_deadline'] == 15
    assert data['missing_fields'] == []


def test_article_77_clause_2_reuses_the_existing_deadline_calculation(
    client: TestClient,
) -> None:
    """新增八款陣列不能另寫一套時效邏輯，必須沿用既有第14條試算。"""
    case_id = create_case(client)
    _patch_fact(client, case_id, 1, 'service.date', '2025-07-01')
    _patch_fact(client, case_id, 2, 'appeal.filed_date', '2025-08-15')
    _patch_fact(client, case_id, 3, 'appeal.initial_submission_method', 'written')

    response = client.get(f'/api/v1/cases/{case_id}/procedural-review')

    assert response.status_code == 200
    data = response.json()['data']
    clause_2 = next(
        item for item in data['clause_assessments'] if item['clause_no'] == 2
    )
    assert data['status'] == 'overdue'
    assert data['deadline_date'] == '2025-07-31'
    assert data['days_from_deadline'] == 15
    assert clause_2['rule_id'] == 'art77_para2'
    assert clause_2['evaluation_mode'] == 'rule'
    assert clause_2['input']['service.date'] == '2025-07-01'
    assert clause_2['input']['appeal.filed_date'] == '2025-08-15'
    assert clause_2['status'] == 'TRIGGERED'
    assert '15' in clause_2['reason']


def test_article_77_clause_2_requests_method_instead_of_assuming_article_57(
    client: TestClient,
) -> None:
    case_id = create_case(client)
    _patch_fact(client, case_id, 1, 'service.date', '2025-07-01')
    _patch_fact(client, case_id, 2, 'appeal.filed_date', '2025-07-10')

    response = client.get(f'/api/v1/cases/{case_id}/procedural-review')

    assert response.status_code == 200
    data = response.json()['data']
    clause_2 = next(
        item for item in data['clause_assessments'] if item['clause_no'] == 2
    )
    assert data['status'] == 'within_period'
    assert data['days_from_deadline'] == -21
    assert clause_2['status'] == 'INSUFFICIENT_EVIDENCE'
    assert '第57條但書' in clause_2['rule_description']
    assert '補送訴願書' in clause_2['reason']
    assert clause_2['missing_fields'] == ['appeal.initial_submission_method']
    assert 'appeal.written_submission_date' in clause_2['input']


def test_review_never_asserts_a_final_admissibility_decision(client: TestClient) -> None:
    case_id = create_case(client)
    _patch_fact(client, case_id, 1, 'service.date', '2025-07-01')
    _patch_fact(client, case_id, 2, 'appeal.filed_date', '2025-08-15')

    response = client.get(f'/api/v1/cases/{case_id}/procedural-review')

    data = response.json()['data']
    # 契約層級的保證：欄位裡不能出現「不受理」這種最終認定用字，
    # 那要留給人工覆核，不是這支端點的責任。
    assert '不受理' not in str(data)
    assert data['legal_review_status'] == 'not_reviewed'


def test_review_for_unknown_case_returns_404(client: TestClient) -> None:
    response = client.get('/api/v1/cases/case_missing/procedural-review')

    assert response.status_code == 404


def test_human_confirmed_facts_recompute_all_eight_clauses_and_expose_origins(client: TestClient):
    case_id = create_case(client)
    facts = {
        'appeal.form_defect': 'no', 'service.date': '2026-07-01',
        'appeal.received_date': '2026-07-15', 'appeal.initial_submission_method': 'written',
        'appellant.standing': 'recipient', 'appellant.capacity': 'capable',
        'appellant.entity_type': 'legal_person', 'representative.name': '林明',
        'representative.authority': 'yes', 'disposition.current_status': 'exists',
        'case.prior_decision_record': 'no', 'case.prior_withdrawal_record': 'no',
        'challenged_act.type': 'administrative_disposition',
        'challenged_act.within_appeal_scope': 'yes',
    }
    response = mutate(client, 'PATCH', f'/api/v1/cases/{case_id}/facts', {
        'expected_case_revision': 1, 'reason': '逐項核對原始證據',
        'field_changes': [
            {'field_path': path, 'value': value, 'human_asserted': True,
             'reason': '已由承辦人確認'} for path, value in facts.items()
        ],
    })
    assert response.status_code == 200
    data = client.get(f'/api/v1/cases/{case_id}/procedural-review').json()['data']
    assert data['case_revision'] == 2
    assert len(data['field_definitions']) >= len(facts)
    assert all(item['status'] == 'NOT_TRIGGERED' for item in data['clause_assessments'])
    assert all(item['missing_fields'] == [] for item in data['clause_assessments'])
    assert data['clause_assessments'][2]['input_sources']['appellant.standing']['origin'] == 'human'
    _patch_fact(client, case_id, 2, 'case.prior_withdrawal_record', 'yes')
    updated = client.get(f'/api/v1/cases/{case_id}/procedural-review').json()['data']
    assert updated['clause_assessments'][6]['status'] == 'TRIGGERED'
    assert updated['clause_assessments'][0]['status'] == 'NOT_TRIGGERED'


def test_invalid_procedural_fact_patch_does_not_modify_case(client: TestClient):
    case_id = create_case(client)
    response = _patch_fact(client, case_id, 1, 'appeal.form_defect', 'false')
    assert response.status_code == 422
    data = client.get(f'/api/v1/cases/{case_id}/procedural-review').json()['data']
    assert data['case_revision'] == 1
    assert data['clause_assessments'][0]['input']['appeal.form_defect'] is None
