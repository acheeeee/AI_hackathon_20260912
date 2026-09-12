"""A2 註記：TargetRef 驗證、註記不改正式內容、resolve 需要版本。對應驗收 H02。"""

import hashlib

from fastapi.testclient import TestClient

from tests.conftest import create_case, create_draft, mutate

QUESTION = '這個日期可能是寄存日，請確認。'


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def draft_block_target(draft: dict, selected: str = '原處分機關') -> dict:
    return {
        'kind': 'draft_block',
        'resource_id': draft['draft_id'],
        'resource_revision': draft['resource_revision'],
        'block_id': 'reason-1',
        'char_start': 0,
        'char_end': len(selected),
        'selected_text': selected,
        'selected_text_sha256': sha256_of(selected),
    }


def fact_field_target(facts_revision: str) -> dict:
    return {
        'kind': 'fact_field',
        'resource_id': 'facts',
        'resource_revision': facts_revision,
        'field_path': 'service.date',
    }


def save_service_date(client: TestClient, case_id: str, expected_revision: int) -> dict:
    return mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/facts',
        {
            'expected_case_revision': expected_revision,
            'reason': '登錄送達日期',
            'field_changes': [
                {'field_path': 'service.date', 'value': '2026-08-01', 'human_asserted': False,
                 'reason': '送達證書'}
            ],
        },
    ).json()['data']


def test_creating_an_annotation_does_not_change_the_case_revision(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)

    # Act
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/annotations',
        {'target': draft_block_target(draft), 'body': QUESTION},
    )

    # Assert: 普通註記不增加 case_revision
    assert response.status_code == 201
    data = response.json()['data']
    assert data['status'] == 'open'
    assert data['case_revision'] == draft['case_revision']


def test_annotating_a_date_leaves_the_recorded_fact_unchanged(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    facts = save_service_date(client, case_id, expected_revision=1)

    # Act
    mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/annotations',
        {'target': fact_field_target(facts['resource_revision']), 'body': QUESTION},
    )

    # Assert
    head = client.get(f'/api/v1/cases/{case_id}/resources/facts').json()['data']
    assert head['content']['fields']['service.date']['value'] == '2026-08-01'
    assert head['resource_revision'] == facts['resource_revision']


def test_a_draft_block_target_without_block_id_is_rejected(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    target = draft_block_target(draft)
    del target['block_id']

    # Act
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/annotations',
        {'target': target, 'body': QUESTION},
    )

    # Assert
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_a_selected_text_hash_that_does_not_match_is_rejected(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    target = draft_block_target(draft)
    target['selected_text_sha256'] = sha256_of('別的文字')

    # Act
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/annotations',
        {'target': target, 'body': QUESTION},
    )

    # Assert: 後端不相信前端傳來的文字就是原文
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_resolving_with_a_stale_annotation_revision_returns_conflict(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    created = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/annotations',
        {'target': draft_block_target(draft), 'body': QUESTION},
    ).json()['data']
    url = f'/api/v1/cases/{case_id}/annotations/{created["annotation_id"]}'
    mutate(client, 'PATCH', url, {
        'expected_annotation_revision': created['annotation_revision'],
        'body': '補充：已向機關查詢。',
    })

    # Act: 用舊的註記版本再送一次
    response = mutate(client, 'PATCH', url, {
        'expected_annotation_revision': created['annotation_revision'],
        'status': 'resolved',
    })

    # Assert
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'


def test_resolving_an_annotation_keeps_the_earlier_body_readable(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    created = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/annotations',
        {'target': draft_block_target(draft), 'body': QUESTION},
    ).json()['data']

    # Act
    resolved = mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/annotations/{created["annotation_id"]}',
        {'expected_annotation_revision': created['annotation_revision'], 'status': 'resolved',
         'body': '機關已確認為寄存送達。'},
    ).json()['data']

    # Assert
    assert resolved['status'] == 'resolved'
    old = client.get(
        f'/api/v1/cases/{case_id}/resources/{created["annotation_id"]}'
        f'?revision={created["annotation_revision"]}'
    ).json()['data']
    assert old['content']['body'] == QUESTION


def test_annotations_can_be_filtered_by_resource(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    facts = save_service_date(client, case_id, expected_revision=draft['case_revision'])
    mutate(client, 'POST', f'/api/v1/cases/{case_id}/annotations',
           {'target': draft_block_target(draft), 'body': '草稿註記'})
    mutate(client, 'POST', f'/api/v1/cases/{case_id}/annotations',
           {'target': fact_field_target(facts['resource_revision']), 'body': '事實註記'})

    # Act
    draft_notes = client.get(
        f'/api/v1/cases/{case_id}/annotations?resource_id={draft["draft_id"]}'
    ).json()['data']['items']
    all_notes = client.get(f'/api/v1/cases/{case_id}/annotations').json()['data']['items']

    # Assert
    assert [note['body'] for note in draft_notes] == ['草稿註記']
    assert len(all_notes) == 2


def test_an_annotation_from_another_case_is_not_visible(client: TestClient) -> None:
    # Arrange
    case_a = create_case(client, title='案件 A')
    case_b = create_case(client, title='案件 B')
    draft = create_draft(client, case_a)
    created = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_a}/annotations',
        {'target': draft_block_target(draft), 'body': QUESTION},
    ).json()['data']

    # Act
    response = client.get(
        f'/api/v1/cases/{case_b}/annotations/{created["annotation_id"]}'
    )

    # Assert
    assert response.status_code == 404
