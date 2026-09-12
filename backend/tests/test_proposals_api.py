"""A3 提案建立與範圍驗證。對應驗收 A02。"""

from fastapi.testclient import TestClient

from tests.conftest import (
    block_target,
    create_case,
    create_draft,
    mutate,
    proposal_body,
    replace_text_group,
)

BLOCK_1 = '原處分機關認事用法並無違誤。'
BLOCK_2 = '訴願人所訴各節，均難謂有理由。'
FORMAL = '原處分機關認事用法尚無違誤，應予維持。'

EVIDENCE = {
    'evidence_id': 'evidence_demo_1',
    'source_ref': {
        'kb_release_id': 'r2',
        'document_id': 'doc_appeal_act',
        'extraction_version': 'ext-1.0',
        'source_spans': [{'page': 2, 'line': 5, 'char_start': 0, 'char_end': 24}],
    },
    'quote': '訴願之提起，應自行政處分達到之次日起三十日內為之。',
}


def post_proposal(client: TestClient, case_id: str, body: dict):
    return mutate(client, 'POST', f'/api/v1/cases/{case_id}/proposals', body)


def test_creating_a_proposal_does_not_change_official_content(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)

    # Act
    response = post_proposal(
        client,
        case_id,
        proposal_body(
            draft,
            expected_case_revision=draft['case_revision'],
            change_groups=[
                replace_text_group(
                    draft, block_id='reason-1', before_text=BLOCK_1, after_text=FORMAL
                )
            ],
        ),
    )

    # Assert
    assert response.status_code == 201
    data = response.json()['data']
    assert data['state'] == 'ready'
    assert data['base_case_revision'] == draft['case_revision']
    head = client.get(f'/api/v1/cases/{case_id}/resources/{draft["draft_id"]}').json()['data']
    assert head['content']['blocks'][0]['text'] == BLOCK_1
    assert head['resource_revision'] == draft['resource_revision']


def test_a_proposal_can_be_read_back_with_its_groups(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    created = post_proposal(
        client,
        case_id,
        proposal_body(
            draft,
            expected_case_revision=draft['case_revision'],
            change_groups=[
                replace_text_group(
                    draft, block_id='reason-1', before_text=BLOCK_1, after_text=FORMAL
                )
            ],
        ),
    ).json()['data']

    # Act
    response = client.get(f'/api/v1/cases/{case_id}/proposals/{created["proposal_id"]}')

    # Assert
    data = response.json()['data']
    assert [group['id'] for group in data['change_groups']] == ['group_wording_1']
    assert data['change_groups'][0]['operations'][0]['op'] == 'replace_text'
    assert data['applied_group_ids'] == []


def test_an_operation_outside_the_selected_range_is_rejected(client: TestClient) -> None:
    # Arrange: 提案的目標是 reason-1，卻想改 reason-2
    case_id = create_case(client)
    draft = create_draft(client, case_id)

    # Act
    response = post_proposal(
        client,
        case_id,
        proposal_body(
            draft,
            expected_case_revision=draft['case_revision'],
            change_groups=[
                replace_text_group(
                    draft, block_id='reason-2', before_text=BLOCK_2, after_text='偷改別段'
                )
            ],
        ),
    )

    # Assert
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'OUT_OF_SCOPE_PATCH'


def test_a_base_text_that_does_not_match_the_version_is_rejected(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    target = block_target(draft, 'reason-1', BLOCK_1)
    group = replace_text_group(
        draft, block_id='reason-1', before_text=BLOCK_1, after_text=FORMAL
    )
    group['operations'][0]['target']['selected_text'] = '不存在的原文'
    group['operations'][0]['target']['char_end'] = len('不存在的原文')
    group['operations'][0]['target']['selected_text_sha256'] = __import__('hashlib').sha256(
        '不存在的原文'.encode('utf-8')
    ).hexdigest()

    # Act
    response = post_proposal(
        client,
        case_id,
        proposal_body(
            draft,
            expected_case_revision=draft['case_revision'],
            target=target,
            change_groups=[group],
        ),
    )

    # Assert: 候選基底必須與已凍結版本一致
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'OUT_OF_SCOPE_PATCH'


def test_a_citation_pointing_at_unknown_evidence_is_rejected(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    group = {
        'id': 'group_citation_1',
        'change_class': 'citation',
        'reason': '補上依據',
        'depends_on_group_ids': [],
        'evidence_ids': ['evidence_missing'],
        'operations': [
            {
                'op': 'add_citation',
                'target': {
                    'resource_id': draft['draft_id'],
                    'resource_revision': draft['resource_revision'],
                    'block_id': 'reason-1',
                },
                'evidence_id': 'evidence_missing',
            }
        ],
    }

    # Act
    response = post_proposal(
        client,
        case_id,
        proposal_body(
            draft, expected_case_revision=draft['case_revision'], change_groups=[group]
        ),
    )

    # Assert
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_CITATION'


def test_fixture_evidence_is_stored_as_unverified(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)

    # Act
    post_proposal(
        client,
        case_id,
        proposal_body(
            draft,
            expected_case_revision=draft['case_revision'],
            evidence=[EVIDENCE],
            change_groups=[
                replace_text_group(
                    draft, block_id='reason-1', before_text=BLOCK_1, after_text=FORMAL,
                    evidence_ids=['evidence_demo_1'],
                )
            ],
        ),
    )

    # Assert: 沒有來源儲存可比對，就不能自稱已查證
    evidence = client.get(
        f'/api/v1/cases/{case_id}/evidence/evidence_demo_1'
    ).json()['data']
    assert evidence['source_exists'] is None
    assert evidence['quote_matches'] is None
    assert evidence['support_status'] == 'unknown'
    assert evidence['assessed_by'] == 'unverified'
    assert evidence['temporal_status'] == 'unknown'


def test_a_proposal_built_on_a_stale_case_revision_is_rejected(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)

    # Act
    response = post_proposal(
        client,
        case_id,
        proposal_body(
            draft,
            expected_case_revision=draft['case_revision'] - 1,
            change_groups=[
                replace_text_group(
                    draft, block_id='reason-1', before_text=BLOCK_1, after_text=FORMAL
                )
            ],
        ),
    )

    # Assert
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'


def test_replace_document_cannot_share_a_proposal_with_other_groups(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    document_group = {
        'id': 'group_full_1',
        'change_class': 'structure',
        'reason': '完整重生',
        'depends_on_group_ids': [],
        'evidence_ids': [],
        'operations': [
            {
                'op': 'replace_document',
                'target': {
                    'kind': 'document',
                    'resource_id': draft['draft_id'],
                    'resource_revision': draft['resource_revision'],
                },
                'after_blocks': [{'block_id': 'reason-1', 'text': '全新寫法。'}],
            }
        ],
    }

    # Act
    response = post_proposal(
        client,
        case_id,
        proposal_body(
            draft,
            expected_case_revision=draft['case_revision'],
            mode='full',
            target={
                'kind': 'document',
                'resource_id': draft['draft_id'],
                'resource_revision': draft['resource_revision'],
            },
            change_groups=[
                document_group,
                replace_text_group(
                    draft, block_id='reason-1', before_text=BLOCK_1, after_text=FORMAL,
                    group_id='group_wording_2',
                ),
            ],
        ),
    )

    # Assert: replace_document 不可拆組，也不能與同文件的局部操作混用
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'
