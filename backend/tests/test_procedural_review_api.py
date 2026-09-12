"""GET /cases/{case_id}/procedural-review：讀取當下 facts 即時算出期間審查。

沒有分析表、沒有快照——結果不持久化，每次都用目前的 facts 重算，跟
case_service._processing_status 的作法一致（見 06 §5.2）。
"""

from fastapi.testclient import TestClient

from conftest import create_case, mutate


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


def test_review_with_both_dates_computes_overdue(client: TestClient) -> None:
    case_id = create_case(client)
    _patch_fact(client, case_id, 1, 'service.date', '2025-07-01')
    _patch_fact(client, case_id, 2, 'appeal.filed_date', '2025-08-15')

    response = client.get(f'/api/v1/cases/{case_id}/procedural-review')

    data = response.json()['data']
    assert data['status'] == 'overdue'
    assert data['days_from_deadline'] == 15
    assert data['missing_fields'] == []


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
