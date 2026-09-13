"""A2 事實編輯：不可變版本、樂觀鎖、失效標記、稽核。對應驗收 H01。"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import create_case, create_draft, mutate

FIRST_DATE = '2026-08-01'
CORRECTED_DATE = '2026-08-05'


def patch_facts(client: TestClient, case_id: str, expected_revision: int, **overrides):
    body = {
        'expected_case_revision': expected_revision,
        'reason': '人工更正送達日期',
        'field_changes': [
            {
                'field_path': 'service.date',
                'value': FIRST_DATE,
                'human_asserted': False,
                'reason': '送達證書第 2 頁',
            }
        ],
    }
    body.update(overrides)
    return mutate(client, 'PATCH', f'/api/v1/cases/{case_id}/facts', body)


def test_saving_a_fact_creates_a_version_and_bumps_case_revision(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)

    # Act
    response = patch_facts(client, case_id, expected_revision=1)

    # Assert
    assert response.status_code == 200
    data = response.json()['data']
    assert data['case_revision'] == 2
    assert data['resource_revision'].startswith('res_')
    assert data['fields']['service.date']['value'] == FIRST_DATE


def test_the_original_value_stays_readable_after_a_correction(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    first = patch_facts(client, case_id, expected_revision=1).json()['data']

    # Act
    patch_facts(
        client,
        case_id,
        expected_revision=2,
        field_changes=[
            {'field_path': 'service.date', 'value': CORRECTED_DATE, 'human_asserted': False,
             'reason': '改依送達證書記載'}
        ],
    )

    # Assert: 指定舊版本仍讀得到原值
    old = client.get(
        f'/api/v1/cases/{case_id}/resources/facts?revision={first["resource_revision"]}'
    ).json()['data']
    head = client.get(f'/api/v1/cases/{case_id}/resources/facts').json()['data']
    assert old['content']['fields']['service.date']['value'] == FIRST_DATE
    assert head['content']['fields']['service.date']['value'] == CORRECTED_DATE
    assert head['parent_revision'] == first['resource_revision']


def test_changing_a_fact_marks_the_draft_stale(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)

    # Act
    response = patch_facts(client, case_id, expected_revision=draft['case_revision'])

    # Assert
    assert draft['freshness'] == 'current'
    assert response.json()['data']['stale_resources'] == [draft['draft_id']]
    head = client.get(f'/api/v1/cases/{case_id}/resources/{draft["draft_id"]}').json()['data']
    assert head['freshness'] == 'stale'


def test_missing_expected_case_revision_is_rejected(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)

    # Act
    response = mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/facts',
        {'reason': '忘了帶版本', 'field_changes': []},
    )

    # Assert
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_stale_expected_case_revision_returns_revision_conflict(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    patch_facts(client, case_id, expected_revision=1)

    # Act: 另一個分頁還以為案件停在 revision 1
    response = patch_facts(client, case_id, expected_revision=1)

    # Assert
    assert response.status_code == 409
    error = response.json()['error']
    assert error['code'] == 'REVISION_CONFLICT'
    assert error['details']['current_case_revision'] == 2


def test_field_path_outside_the_allowlist_is_rejected(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)

    # Act
    response = patch_facts(
        client,
        case_id,
        expected_revision=1,
        field_changes=[
            {'field_path': 'deadline.days_overdue', 'value': '3', 'human_asserted': True,
             'reason': '直接改逾期天數'}
        ],
    )

    # Assert: 計算輸出不是可直接改的事實欄位
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'


@pytest.mark.parametrize(
    ('field_path', 'limit'),
    [
        ('analysis.statute_query', 80),
        ('analysis.keywords', 120),
        ('disposition.summary', 800),
    ],
)
def test_analysis_field_value_limits_are_enforced_at_the_patch_boundary(
    client: TestClient, field_path: str, limit: int
) -> None:
    """Clients must not persist oversized analysis values by bypassing the UI."""
    case_id = create_case(client)

    response = patch_facts(
        client,
        case_id,
        expected_revision=1,
        field_changes=[
            {
                'field_path': field_path,
                'value': '甲' * (limit + 1),
                'human_asserted': True,
                'reason': '測試欄位長度限制',
            }
        ],
    )

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_human_asserted_values_are_labelled_as_such(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)

    # Act
    response = patch_facts(
        client,
        case_id,
        expected_revision=1,
        field_changes=[
            {'field_path': 'service.method', 'value': '寄存送達', 'human_asserted': True,
             'reason': '訴願人口述，尚無文件佐證'}
        ],
    )

    # Assert
    field = response.json()['data']['fields']['service.method']
    assert field['human_asserted'] is True
    assert field['origin'] == 'human'


def test_fact_change_is_audited_with_before_and_after(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    patch_facts(client, case_id, expected_revision=1)

    # Act
    entries = client.get(f'/api/v1/cases/{case_id}/audit').json()['data']['items']

    # Assert
    fact_entry = entries[-1]
    assert fact_entry['action'] == 'facts.updated'
    assert fact_entry['reason'] == '人工更正送達日期'
    assert fact_entry['after_refs']['changed_field_paths'] == ['service.date']


def test_replaying_the_same_fact_patch_does_not_apply_twice(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    body = {
        'expected_case_revision': 1,
        'reason': '人工更正送達日期',
        'field_changes': [
            {'field_path': 'service.date', 'value': FIRST_DATE, 'human_asserted': False,
             'reason': '送達證書第 2 頁'}
        ],
    }
    first = mutate(client, 'PATCH', f'/api/v1/cases/{case_id}/facts', body, key='key-fact')

    # Act: 回應遺失後前端重送同一把鍵
    second = mutate(client, 'PATCH', f'/api/v1/cases/{case_id}/facts', body, key='key-fact')

    # Assert
    assert second.status_code == 200
    assert second.json()['data'] == first.json()['data']
    assert client.get(f'/api/v1/cases/{case_id}').json()['data']['case_revision'] == 2


def test_a_failure_partway_through_rolls_everything_back(
    client: TestClient, monkeypatch
) -> None:
    # Arrange: V07，稽核寫入失敗
    case_id = create_case(client)
    draft = create_draft(client, case_id)

    def fail_audit(*args, **kwargs):
        raise RuntimeError('稽核寫入失敗')

    monkeypatch.setattr('caseapi.services.facts_service.append_entry', fail_audit)

    # Act
    with pytest.raises(RuntimeError):
        patch_facts(client, case_id, expected_revision=draft['case_revision'])
    monkeypatch.undo()

    # Assert: 事實版本、case head 與稽核要同時成功或同時不變
    detail = client.get(f'/api/v1/cases/{case_id}').json()['data']
    assert detail['case_revision'] == draft['case_revision']
    assert 'facts' not in detail['active_heads']
    assert client.get(f'/api/v1/cases/{case_id}/versions?resource_id=facts').status_code == 404
    actions = [
        entry['action']
        for entry in client.get(f'/api/v1/cases/{case_id}/audit').json()['data']['items']
    ]
    assert actions == ['case.created', 'draft.created']
