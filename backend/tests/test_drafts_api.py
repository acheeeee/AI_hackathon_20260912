"""A2 草稿編輯：區塊級修改、基底版本檢查、stale 不會被文字編輯偷偷解除。"""

from fastapi.testclient import TestClient

from tests.conftest import create_case, create_draft, mutate

REWRITTEN = '原處分機關認事用法尚無違誤，訴願人所指各節均不足採。'


def make_facts_change(client: TestClient, case_id: str, expected_revision: int):
    return mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/facts',
        {
            'expected_case_revision': expected_revision,
            'reason': '更正送達日期',
            'field_changes': [
                {'field_path': 'service.date', 'value': '2026-08-05', 'human_asserted': False,
                 'reason': '送達證書'}
            ],
        },
    )


def test_creating_a_draft_registers_a_head_and_first_version(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)

    # Act
    draft = create_draft(client, case_id)

    # Assert
    assert draft['case_revision'] == 2
    assert draft['freshness'] == 'current'
    detail = client.get(f'/api/v1/cases/{case_id}').json()['data']
    assert detail['active_heads'][draft['draft_id']]['revision_id'] == draft['resource_revision']


def test_editing_one_block_leaves_the_other_blocks_untouched(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)

    # Act
    response = mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}',
        {
            'expected_case_revision': draft['case_revision'],
            'base_resource_revision': draft['resource_revision'],
            'block_changes': [{'block_id': 'reason-1', 'text': REWRITTEN}],
        },
    )

    # Assert
    blocks = {block['block_id']: block['text'] for block in response.json()['data']['blocks']}
    assert blocks['reason-1'] == REWRITTEN
    assert blocks['reason-2'] == '訴願人所訴各節，均難謂有理由。'


def test_editing_an_unknown_block_is_rejected(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)

    # Act
    response = mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}',
        {
            'expected_case_revision': draft['case_revision'],
            'base_resource_revision': draft['resource_revision'],
            'block_changes': [{'block_id': 'reason-9', 'text': '不存在的區塊'}],
        },
    )

    # Assert
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'TARGET_MOVED'


def test_editing_from_an_outdated_base_revision_returns_conflict(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    first = mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}',
        {
            'expected_case_revision': draft['case_revision'],
            'base_resource_revision': draft['resource_revision'],
            'block_changes': [{'block_id': 'reason-1', 'text': '第一次修改'}],
        },
    ).json()['data']

    # Act: 另一個分頁還拿著最初的草稿版本
    response = mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}',
        {
            'expected_case_revision': first['case_revision'],
            'base_resource_revision': draft['resource_revision'],
            'block_changes': [{'block_id': 'reason-1', 'text': '第二次修改'}],
        },
    )

    # Assert
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'


def test_manual_text_editing_does_not_clear_the_stale_flag(client: TestClient) -> None:
    # Arrange: 事實變動後草稿已標過期
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    facts = make_facts_change(client, case_id, draft['case_revision']).json()['data']

    # Act: 只改文字
    response = mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}',
        {
            'expected_case_revision': facts['case_revision'],
            'base_resource_revision': draft['resource_revision'],
            'block_changes': [{'block_id': 'reason-1', 'text': REWRITTEN}],
        },
    )

    # Assert: 設計 03 §4，人工文字編輯不自動解除既有 stale
    assert response.json()['data']['freshness'] == 'stale'


def test_a_recorded_review_clears_stale_and_keeps_the_reason(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    facts = make_facts_change(client, case_id, draft['case_revision']).json()['data']

    # Act
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}/reviews',
        {
            'expected_case_revision': facts['case_revision'],
            'base_resource_revision': draft['resource_revision'],
            'reason': '已依新的送達日期逐段覆核，內容不需改動',
        },
    )

    # Assert
    assert response.status_code == 201
    assert response.json()['data']['freshness'] == 'current'
    entries = client.get(f'/api/v1/cases/{case_id}/audit').json()['data']['items']
    assert entries[-1]['action'] == 'draft.reviewed'
    assert entries[-1]['reason'] == '已依新的送達日期逐段覆核，內容不需改動'


def test_a_review_without_a_reason_is_rejected(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)

    # Act
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}/reviews',
        {
            'expected_case_revision': draft['case_revision'],
            'base_resource_revision': draft['resource_revision'],
            'reason': '',
        },
    )

    # Assert: 不能單改旗標，必須留下理由
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_version_list_shows_the_chain_newest_first(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}',
        {
            'expected_case_revision': draft['case_revision'],
            'base_resource_revision': draft['resource_revision'],
            'block_changes': [{'block_id': 'reason-1', 'text': REWRITTEN}],
        },
    )

    # Act
    items = client.get(
        f'/api/v1/cases/{case_id}/versions?resource_id={draft["draft_id"]}'
    ).json()['data']['items']

    # Assert
    assert len(items) == 2
    assert items[0]['parent_revision'] == items[1]['resource_revision']
    assert items[1]['parent_revision'] is None


def test_reading_a_resource_from_another_case_returns_404(client: TestClient) -> None:
    # Arrange
    case_a = create_case(client, title='案件 A')
    case_b = create_case(client, title='案件 B')
    draft = create_draft(client, case_a)

    # Act
    response = client.get(f'/api/v1/cases/{case_b}/resources/{draft["draft_id"]}')

    # Assert
    assert response.status_code == 404
