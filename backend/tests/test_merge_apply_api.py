"""A3 三方合併預覽與逐組採用。對應驗收 V01–V06。"""

from fastapi.testclient import TestClient

from tests.conftest import create_case, create_draft, mutate, proposal_body, replace_text_group

BLOCK_1 = '原處分機關認事用法並無違誤。'
BLOCK_2 = '訴願人所訴各節，均難謂有理由。'
FORMAL = '原處分機關認事用法尚無違誤，應予維持。'
HUMAN_EDIT = '原處分機關的認定，承辦人另有意見。'


def make_proposal(client: TestClient, case_id: str, body: dict) -> dict:
    response = mutate(client, 'POST', f'/api/v1/cases/{case_id}/proposals', body)
    assert response.status_code == 201, response.text
    return response.json()['data']


def simple_wording_proposal(client: TestClient, case_id: str, draft: dict, **overrides) -> dict:
    body = proposal_body(
        draft,
        expected_case_revision=draft['case_revision'],
        change_groups=[
            replace_text_group(draft, block_id='reason-1', before_text=BLOCK_1, after_text=FORMAL)
        ],
        **overrides,
    )
    return make_proposal(client, case_id, body)


def preview(client: TestClient, case_id: str, proposal_id: str, revision: int, groups: list[str]):
    return mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/proposals/{proposal_id}/merge-previews',
        {'expected_case_revision': revision, 'selected_group_ids': groups},
    )


def edit_block(client: TestClient, case_id: str, draft: dict, block_id: str, text: str, rev: int):
    return mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}',
        {
            'expected_case_revision': rev,
            'base_resource_revision': draft['resource_revision'],
            'block_changes': [{'block_id': block_id, 'text': text}],
        },
    ).json()['data']


def test_a_clean_preview_can_be_applied_and_updates_the_draft(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = simple_wording_proposal(client, case_id, draft)
    prepared = preview(
        client, case_id, proposal['proposal_id'], draft['case_revision'], ['group_wording_1']
    ).json()['data']

    # Act
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}/applications',
        {
            'expected_case_revision': draft['case_revision'],
            'preview_id': prepared['preview_id'],
            'preview_hash': prepared['preview_hash'],
            'accepted_group_ids': ['group_wording_1'],
        },
    )

    # Assert
    assert prepared['can_apply'] is True
    data = response.json()['data']
    assert data['applied_group_ids'] == ['group_wording_1']
    assert data['proposal_state'] == 'applied'
    head = client.get(f'/api/v1/cases/{case_id}/resources/{draft["draft_id"]}').json()['data']
    assert head['content']['blocks'][0]['text'] == FORMAL
    assert head['origin'] == 'merged'


def test_current_content_is_untouched_until_the_proposal_is_applied(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = simple_wording_proposal(client, case_id, draft)

    # Act
    preview(client, case_id, proposal['proposal_id'], draft['case_revision'], ['group_wording_1'])

    # Assert
    head = client.get(f'/api/v1/cases/{case_id}/resources/{draft["draft_id"]}').json()['data']
    assert head['content']['blocks'][0]['text'] == BLOCK_1
    assert head['resource_revision'] == draft['resource_revision']


def test_a_human_edit_to_the_same_block_produces_a_three_way_conflict(client: TestClient) -> None:
    # Arrange: V01
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = simple_wording_proposal(client, case_id, draft)
    edited = edit_block(client, case_id, draft, 'reason-1', HUMAN_EDIT, draft['case_revision'])

    # Act
    prepared = preview(
        client, case_id, proposal['proposal_id'], edited['case_revision'], ['group_wording_1']
    ).json()['data']

    # Assert
    assert prepared['can_apply'] is False
    assert prepared['conflicts'][0]['code'] == 'SAME_BLOCK_CHANGED'
    diff = prepared['diffs'][0]
    assert (diff['base'], diff['current'], diff['candidate']) == (BLOCK_1, HUMAN_EDIT, FORMAL)


def test_a_human_edit_to_another_block_still_merges(client: TestClient) -> None:
    # Arrange: V02
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = simple_wording_proposal(client, case_id, draft)
    edited = edit_block(client, case_id, draft, 'reason-2', '訴願人另有補充理由。',
                        draft['case_revision'])

    # Act
    prepared = preview(
        client, case_id, proposal['proposal_id'], edited['case_revision'], ['group_wording_1']
    ).json()['data']
    applied = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}/applications',
        {
            'expected_case_revision': edited['case_revision'],
            'preview_id': prepared['preview_id'],
            'preview_hash': prepared['preview_hash'],
            'accepted_group_ids': ['group_wording_1'],
        },
    )

    # Assert: 無關段落的人工修改要保留
    assert prepared['can_apply'] is True
    assert applied.status_code == 200
    blocks = client.get(
        f'/api/v1/cases/{case_id}/resources/{draft["draft_id"]}'
    ).json()['data']['content']['blocks']
    texts = {block['block_id']: block['text'] for block in blocks}
    assert texts == {'reason-1': FORMAL, 'reason-2': '訴願人另有補充理由。'}


def test_changed_facts_make_a_legal_group_dependency_stale(client: TestClient) -> None:
    # Arrange: V03，文字沒變但事實變了
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    facts = mutate(client, 'PATCH', f'/api/v1/cases/{case_id}/facts', {
        'expected_case_revision': draft['case_revision'],
        'reason': '登錄送達日期',
        'field_changes': [{'field_path': 'service.date', 'value': '2026-08-01',
                           'human_asserted': False, 'reason': '送達證書'}],
    }).json()['data']
    proposal = simple_wording_proposal(
        client,
        case_id,
        {**draft, 'case_revision': facts['case_revision']},
        dependencies={'facts_revision': facts['resource_revision']},
    )
    later = mutate(client, 'PATCH', f'/api/v1/cases/{case_id}/facts', {
        'expected_case_revision': facts['case_revision'],
        'reason': '更正送達日期',
        'field_changes': [{'field_path': 'service.date', 'value': '2026-08-05',
                           'human_asserted': True, 'reason': '寄存通知書'}],
    }).json()['data']

    # Act: 把這組標成法律判斷而非單純潤飾
    legal = proposal_body(
        draft,
        expected_case_revision=later['case_revision'],
        dependencies={'facts_revision': facts['resource_revision']},
        change_groups=[
            replace_text_group(draft, block_id='reason-1', before_text=BLOCK_1,
                               after_text=FORMAL, change_class='legal_assessment')
        ],
    )
    legal_proposal = make_proposal(client, case_id, legal)
    prepared = preview(client, case_id, legal_proposal['proposal_id'],
                       later['case_revision'], ['group_wording_1']).json()['data']
    wording_prepared = preview(client, case_id, proposal['proposal_id'],
                               later['case_revision'], ['group_wording_1']).json()['data']

    # Assert
    assert prepared['can_apply'] is False
    assert prepared['conflicts'][0]['code'] == 'DEPENDENCY_STALE'
    # 設計 03 §6.1 規則 6：純 wording 且宣告依賴未變，仍可在新 current 上預覽
    assert wording_prepared['can_apply'] is True


def test_full_regeneration_shows_base_current_and_candidate(client: TestClient) -> None:
    # Arrange: V04
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    document_target = {
        'kind': 'document',
        'resource_id': draft['draft_id'],
        'resource_revision': draft['resource_revision'],
    }
    proposal = make_proposal(client, case_id, proposal_body(
        draft,
        expected_case_revision=draft['case_revision'],
        mode='full',
        target=document_target,
        change_groups=[{
            'id': 'group_full_1',
            'change_class': 'structure',
            'reason': '依更新後事實完整重生',
            'depends_on_group_ids': [],
            'evidence_ids': [],
            'operations': [{
                'op': 'replace_document',
                'target': document_target,
                'after_blocks': [
                    {'block_id': 'reason-1', 'text': FORMAL},
                    {'block_id': 'reason-3', 'text': '新增一段補充理由。'},
                ],
            }],
        }],
    ))

    # Act
    prepared = preview(client, case_id, proposal['proposal_id'], draft['case_revision'],
                       ['group_full_1']).json()['data']

    # Assert: 逐段可比，且未採用前正文不變
    by_block = {diff['block_id']: diff for diff in prepared['diffs']}
    assert by_block['reason-1']['base'] == BLOCK_1
    assert by_block['reason-1']['candidate'] == FORMAL
    assert by_block['reason-2']['candidate'] is None
    assert by_block['reason-3']['base'] is None
    head = client.get(f'/api/v1/cases/{case_id}/resources/{draft["draft_id"]}').json()['data']
    assert head['resource_revision'] == draft['resource_revision']


def test_accepting_text_without_its_required_citation_is_refused(client: TestClient) -> None:
    # Arrange: V05
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    evidence = {
        'evidence_id': 'evidence_demo_1',
        'source_ref': {'kb_release_id': 'r2', 'document_id': 'doc_x',
                       'extraction_version': 'ext-1.0',
                       'source_spans': [{'page': 1, 'line': 1, 'char_start': 0, 'char_end': 10}]},
        'quote': '訴願之提起，應自行政處分達到之次日起三十日內為之。',
    }
    citation_group = {
        'id': 'group_citation_1',
        'change_class': 'citation',
        'reason': '加入所引法條',
        'depends_on_group_ids': [],
        'evidence_ids': ['evidence_demo_1'],
        'operations': [{
            'op': 'add_citation',
            'target': {'resource_id': draft['draft_id'],
                       'resource_revision': draft['resource_revision'],
                       'block_id': 'reason-1'},
            'evidence_id': 'evidence_demo_1',
        }],
    }
    text_group = replace_text_group(
        draft, block_id='reason-1', before_text=BLOCK_1,
        after_text='依訴願法第十四條規定，本件已逾法定期間。',
        group_id='group_legal_1', change_class='legal_assessment',
        depends_on=['group_citation_1'], evidence_ids=['evidence_demo_1'],
    )
    proposal = make_proposal(client, case_id, proposal_body(
        draft,
        expected_case_revision=draft['case_revision'],
        evidence=[evidence],
        change_groups=[citation_group, text_group],
    ))

    # Act: 只採文字組，不採必要的引用組
    prepared = preview(client, case_id, proposal['proposal_id'], draft['case_revision'],
                       ['group_legal_1']).json()['data']
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}/applications',
        {
            'expected_case_revision': draft['case_revision'],
            'preview_id': prepared['preview_id'],
            'preview_hash': prepared['preview_hash'],
            'accepted_group_ids': ['group_legal_1'],
        },
    )

    # Assert
    assert prepared['can_apply'] is False
    assert prepared['missing_group_dependencies'] == [
        {'group_id': 'group_legal_1', 'requires': ['group_citation_1']}
    ]
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_CITATION'


def test_replaying_an_apply_returns_the_same_result(client: TestClient) -> None:
    # Arrange: V06
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = simple_wording_proposal(client, case_id, draft)
    prepared = preview(client, case_id, proposal['proposal_id'], draft['case_revision'],
                       ['group_wording_1']).json()['data']
    body = {
        'expected_case_revision': draft['case_revision'],
        'preview_id': prepared['preview_id'],
        'preview_hash': prepared['preview_hash'],
        'accepted_group_ids': ['group_wording_1'],
    }
    url = f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}/applications'
    first = mutate(client, 'POST', url, body, key='key-apply')

    # Act
    replay = mutate(client, 'POST', url, body, key='key-apply')

    # Assert
    assert replay.json()['data'] == first.json()['data']
    assert client.get(f'/api/v1/cases/{case_id}').json()['data']['case_revision'] == (
        first.json()['data']['resulting_case_revision']
    )


def test_applying_the_same_group_again_with_a_new_key_is_refused(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = simple_wording_proposal(client, case_id, draft)
    prepared = preview(client, case_id, proposal['proposal_id'], draft['case_revision'],
                       ['group_wording_1']).json()['data']
    url = f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}/applications'
    applied = mutate(client, 'POST', url, {
        'expected_case_revision': draft['case_revision'],
        'preview_id': prepared['preview_id'],
        'preview_hash': prepared['preview_hash'],
        'accepted_group_ids': ['group_wording_1'],
    }).json()['data']

    # Act: 重新預覽後用新的冪等鍵再採用一次同一組
    second_preview = preview(client, case_id, proposal['proposal_id'],
                             applied['resulting_case_revision'],
                             ['group_wording_1']).json()['data']
    response = mutate(client, 'POST', url, {
        'expected_case_revision': applied['resulting_case_revision'],
        'preview_id': second_preview['preview_id'],
        'preview_hash': second_preview['preview_hash'],
        'accepted_group_ids': ['group_wording_1'],
    })

    # Assert
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'PROPOSAL_ALREADY_APPLIED'


def test_a_tampered_preview_hash_is_refused(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = simple_wording_proposal(client, case_id, draft)
    prepared = preview(client, case_id, proposal['proposal_id'], draft['case_revision'],
                       ['group_wording_1']).json()['data']

    # Act
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}/applications',
        {
            'expected_case_revision': draft['case_revision'],
            'preview_id': prepared['preview_id'],
            'preview_hash': 'deadbeef',
            'accepted_group_ids': ['group_wording_1'],
        },
    )

    # Assert
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'


def test_accepted_groups_must_match_the_preview_exactly(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = make_proposal(client, case_id, proposal_body(
        draft,
        expected_case_revision=draft['case_revision'],
        mode='full',
        target={'kind': 'document', 'resource_id': draft['draft_id'],
                'resource_revision': draft['resource_revision']},
        change_groups=[
            replace_text_group(draft, block_id='reason-1', before_text=BLOCK_1,
                               after_text=FORMAL, group_id='group_a'),
            replace_text_group(draft, block_id='reason-2', before_text=BLOCK_2,
                               after_text='訴願人主張不足採。', group_id='group_b'),
        ],
    ))
    prepared = preview(client, case_id, proposal['proposal_id'], draft['case_revision'],
                       ['group_a']).json()['data']

    # Act: 採用時臨時多加一組
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}/applications',
        {
            'expected_case_revision': draft['case_revision'],
            'preview_id': prepared['preview_id'],
            'preview_hash': prepared['preview_hash'],
            'accepted_group_ids': ['group_a', 'group_b'],
        },
    )

    # Assert
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_applying_one_of_two_groups_leaves_the_proposal_partially_applied(
    client: TestClient,
) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = make_proposal(client, case_id, proposal_body(
        draft,
        expected_case_revision=draft['case_revision'],
        mode='full',
        target={'kind': 'document', 'resource_id': draft['draft_id'],
                'resource_revision': draft['resource_revision']},
        change_groups=[
            replace_text_group(draft, block_id='reason-1', before_text=BLOCK_1,
                               after_text=FORMAL, group_id='group_a'),
            replace_text_group(draft, block_id='reason-2', before_text=BLOCK_2,
                               after_text='訴願人主張不足採。', group_id='group_b'),
        ],
    ))
    prepared = preview(client, case_id, proposal['proposal_id'], draft['case_revision'],
                       ['group_a']).json()['data']

    # Act
    applied = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}/applications',
        {
            'expected_case_revision': draft['case_revision'],
            'preview_id': prepared['preview_id'],
            'preview_hash': prepared['preview_hash'],
            'accepted_group_ids': ['group_a'],
        },
    ).json()['data']

    # Assert
    assert applied['proposal_state'] == 'partially_applied'
    blocks = client.get(
        f'/api/v1/cases/{case_id}/resources/{draft["draft_id"]}'
    ).json()['data']['content']['blocks']
    texts = {block['block_id']: block['text'] for block in blocks}
    assert texts == {'reason-1': FORMAL, 'reason-2': BLOCK_2}


def test_a_manual_resolution_creates_a_new_preview_without_changing_the_old_one(
    client: TestClient,
) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = simple_wording_proposal(client, case_id, draft)
    edited = edit_block(client, case_id, draft, 'reason-1', HUMAN_EDIT, draft['case_revision'])
    conflicted = preview(client, case_id, proposal['proposal_id'], edited['case_revision'],
                         ['group_wording_1']).json()['data']

    # Act
    merged_text = '原處分機關認事用法尚無違誤；承辦人意見另列。'
    resolved = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}'
        f'/merge-previews/{conflicted["preview_id"]}/resolutions',
        {
            'expected_case_revision': edited['case_revision'],
            'resolutions': [{'resource_id': draft['draft_id'], 'block_id': 'reason-1',
                             'text': merged_text}],
        },
    )

    # Assert
    assert resolved.status_code == 201
    data = resolved.json()['data']
    assert data['preview_id'] != conflicted['preview_id']
    assert data['can_apply'] is True
    assert data['diffs'][0]['candidate'] == merged_text
    old = client.get(
        f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}'
    ).json()['data']
    assert old['state'] == 'ready'


def test_rejecting_a_proposal_keeps_it_readable(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    proposal = simple_wording_proposal(client, case_id, draft)

    # Act
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}/rejections',
        {'reason': '這個寫法不採用'},
    )

    # Assert
    assert response.status_code == 200
    assert response.json()['data']['state'] == 'rejected'
    head = client.get(f'/api/v1/cases/{case_id}/resources/{draft["draft_id"]}').json()['data']
    assert head['content']['blocks'][0]['text'] == BLOCK_1


def test_applying_a_fact_change_marks_the_draft_stale(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    facts = mutate(client, 'PATCH', f'/api/v1/cases/{case_id}/facts', {
        'expected_case_revision': draft['case_revision'],
        'reason': '依處分書登錄送達日期',
        'field_changes': [{'field_path': 'service.date', 'value': '2026-08-01',
                           'human_asserted': False, 'reason': '送達證書'}],
    }).json()['data']
    fact_target = {'kind': 'fact_field', 'resource_id': 'facts',
                   'resource_revision': facts['resource_revision'],
                   'field_path': 'service.date'}
    proposal = make_proposal(client, case_id, proposal_body(
        draft,
        expected_case_revision=facts['case_revision'],
        target=fact_target,
        change_groups=[{
            'id': 'group_fact_1',
            'change_class': 'fact',
            'reason': '依寄存通知書更正送達日',
            'depends_on_group_ids': [],
            'evidence_ids': [],
            'operations': [{
                'op': 'replace_fact',
                'target': fact_target,
                'before_value': '2026-08-01',
                'after_value': '2026-08-05',
            }],
        }],
    ))
    prepared = preview(client, case_id, proposal['proposal_id'], facts['case_revision'],
                       ['group_fact_1']).json()['data']

    # Act
    applied = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/proposals/{proposal["proposal_id"]}/applications',
        {
            'expected_case_revision': facts['case_revision'],
            'preview_id': prepared['preview_id'],
            'preview_hash': prepared['preview_hash'],
            'accepted_group_ids': ['group_fact_1'],
        },
    ).json()['data']

    # Assert
    assert applied['invalidated_resources'] == [draft['draft_id']]
    facts = client.get(f'/api/v1/cases/{case_id}/resources/facts').json()['data']
    assert facts['content']['fields']['service.date']['value'] == '2026-08-05'
    assert facts['origin'] == 'merged'


def test_full_regeneration_over_a_human_edit_keeps_all_three_versions(
    client: TestClient,
) -> None:
    # Arrange: V04，重生的基底之後又被人工改過
    case_id = create_case(client)
    draft = create_draft(client, case_id)
    document_target = {
        'kind': 'document',
        'resource_id': draft['draft_id'],
        'resource_revision': draft['resource_revision'],
    }
    proposal = make_proposal(client, case_id, proposal_body(
        draft,
        expected_case_revision=draft['case_revision'],
        mode='full',
        target=document_target,
        change_groups=[{
            'id': 'group_full_1',
            'change_class': 'structure',
            'reason': '依更新後事實完整重生',
            'depends_on_group_ids': [],
            'evidence_ids': [],
            'operations': [{
                'op': 'replace_document',
                'target': document_target,
                'after_blocks': [{'block_id': 'reason-1', 'text': FORMAL},
                                 {'block_id': 'reason-2', 'text': BLOCK_2}],
            }],
        }],
    ))
    edited = edit_block(client, case_id, draft, 'reason-1', HUMAN_EDIT, draft['case_revision'])

    # Act
    prepared = preview(client, case_id, proposal['proposal_id'], edited['case_revision'],
                       ['group_full_1']).json()['data']

    # Assert: 三方都看得到，且人工內容未被覆寫
    diff = next(item for item in prepared['diffs'] if item['block_id'] == 'reason-1')
    assert (diff['base'], diff['current'], diff['candidate']) == (BLOCK_1, HUMAN_EDIT, FORMAL)
    assert prepared['can_apply'] is False
    assert prepared['conflicts'][0]['code'] == 'SAME_DOCUMENT_CHANGED'
    head = client.get(f'/api/v1/cases/{case_id}/resources/{draft["draft_id"]}').json()['data']
    assert head['content']['blocks'][0]['text'] == HUMAN_EDIT
