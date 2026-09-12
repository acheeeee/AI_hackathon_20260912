"""Case list/detail expose a derived processing_status, not a new state column.

Status is read at query time from data that already exists: whether the
case has a draft head at all, and whether any draft on it has ever been
through POST .../reviews (audit action 'draft.reviewed'). No new column is
added to `cases` — see docs/協作設計/06 §5.2 on not inventing a state
machine when the signal is already derivable.
"""

from fastapi.testclient import TestClient

from conftest import create_case, create_draft, mutate


def _get_case(client: TestClient, case_id: str) -> dict:
    return client.get(f'/api/v1/cases/{case_id}').json()['data']


def _get_summary_from_list(client: TestClient, case_id: str) -> dict:
    items = client.get('/api/v1/cases').json()['data']['items']
    return next(item for item in items if item['case_id'] == case_id)


def test_freshly_created_case_is_unprocessed(client: TestClient) -> None:
    case_id = create_case(client)

    assert _get_case(client, case_id)['processing_status'] == 'unprocessed'
    assert _get_summary_from_list(client, case_id)['processing_status'] == 'unprocessed'


def test_case_with_a_draft_but_no_review_is_processing(client: TestClient) -> None:
    case_id = create_case(client)
    create_draft(client, case_id)

    assert _get_case(client, case_id)['processing_status'] == 'processing'
    assert _get_summary_from_list(client, case_id)['processing_status'] == 'processing'


def test_case_with_a_reviewed_draft_is_completed(client: TestClient) -> None:
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    case_revision = _get_case(client, case_id)['case_revision']

    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}/reviews',
        {
            'expected_case_revision': case_revision,
            'base_resource_revision': draft['resource_revision'],
            'reason': '已完成覆核，內容可送出',
        },
    )
    assert response.status_code == 201

    assert _get_case(client, case_id)['processing_status'] == 'completed'
    assert _get_summary_from_list(client, case_id)['processing_status'] == 'completed'
