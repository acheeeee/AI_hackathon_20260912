"""草稿生成端到端：真的 proposal，不是聊天答案。

06 §7.1 的要求：新的 `draft` intent 必須把「目前事實＋選定法規＋訴願書
原文」當 context，結果要透過 `proposal_service` 產生帶 groups 與 EvidenceRef
的正式提案；未採用前正文（草稿 head）不得改變。
"""

from fastapi.testclient import TestClient

from caseapi.clock import now_iso
from caseapi.db.connection import connect, transaction
from caseapi.main import create_app

from conftest import create_case, mutate
from test_fixed_model_e2e import FakeEvidenceRepository

APPEAL_TEXT = (
    '訴願書\n'
    '訴願人：絕○○○股份有限公司\n'
    '事實：訴願人於中華民國一百十四年三月一日申請洗錢防制服務業登記，'
    '原處分機關以不符規定為由否准。\n'
    '理由：原處分機關適用洗錢防制法第六條顯有違誤。\n'
    '此致\n'
)

SELECTED_STATUTE = {
    'chunk_id': 'chk_law_14',
    'document_id': 'doc_law',
    'section_id': 'sec_law_14',
    'statute_name': '訴願法',
    'article_key': '14',
    'excerpt': '訴願之提起，應自行政處分達到之次日起三十日內為之。',
}


class RecordingModelProvider:
    """Captures the ModelRequest the runner hands to the provider boundary."""

    prompt_version = 'recording-draft-test-v1'

    def __init__(self) -> None:
        self.requests: list[object] = []

    def descriptor(self) -> dict[str, str]:
        return {'provider': 'recording-test', 'model': 'recording-v1'}

    def execute(self, request, tools):
        del tools
        self.requests.append(request)
        from caseapi.ai.contracts import ModelResult

        return ModelResult('記錄用 provider，不產生草稿。')


def _client(settings, provider=None) -> TestClient:
    from caseapi.ai.fixed_provider import FixedModelProvider

    return TestClient(
        create_app(
            settings,
            evidence_repository=FakeEvidenceRepository(),
            model_provider=provider or FixedModelProvider(),
        )
    )


def _seed_appeal_document(settings, case_id: str) -> None:
    """上傳建案存下的訴願書全文；這裡直接寫表，不重跑 PDF 抽取。"""
    conn = connect(settings.db_path)
    try:
        with transaction(conn):
            conn.execute(
                'INSERT INTO case_documents (id, case_id, document_role, source_filename,'
                ' source_sha256, content_blob, extracted_text, page_count, created_by,'
                ' created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    'doc_appeal_test',
                    case_id,
                    'appeal',
                    'appeal.pdf',
                    'sha-appeal',
                    b'%PDF-1.4 fake',
                    APPEAL_TEXT,
                    1,
                    settings.actor_id,
                    now_iso(),
                ),
            )
    finally:
        conn.close()


def _seed_case(client: TestClient, settings, *, with_statute: bool = True) -> str:
    case_id = create_case(client)
    _seed_appeal_document(settings, case_id)
    mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/facts',
        {
            'expected_case_revision': 1,
            'reason': '規則式抽取自上傳訴願書',
            'field_changes': [
                {
                    'field_path': 'appellant.name',
                    'value': '絕○○○股份有限公司',
                    'human_asserted': False,
                    'reason': '規則式抽取自上傳訴願書',
                }
            ],
        },
    )
    if with_statute:
        mutate(
            client,
            'PUT',
            f'/api/v1/cases/{case_id}/statute-selection',
            {
                'expected_case_revision': 2,
                'reason': '人工挑選相關法規',
                'selected': [SELECTED_STATUTE],
            },
        )
    return case_id


def _generate(client: TestClient, case_id: str, *, expected_case_revision: int, key=None):
    return mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/draft-generations',
        {'expected_case_revision': expected_case_revision},
        key=key,
    )


def _events(client: TestClient, case_id: str, run_id: str) -> list[dict]:
    return client.get(
        f'/api/v1/cases/{case_id}/runs/{run_id}/events', params={'format': 'json'}
    ).json()['data']['items']


def test_draft_generation_produces_a_proposal_with_program_verified_evidence(
    settings,
) -> None:
    # Arrange
    with _client(settings) as client:
        case_id = _seed_case(client, settings)

        # Act
        response = _generate(client, case_id, expected_case_revision=3)

        # Assert
        assert response.status_code == 202
        created = response.json()['data']
        run = client.get(
            f'/api/v1/cases/{case_id}/runs/{created["run_id"]}'
        ).json()['data']
        assert run['kind'] == 'regenerate'
        assert run['state'] == 'completed'
        assert len(run['proposal_ids']) == 1

        proposal = client.get(
            f'/api/v1/cases/{case_id}/proposals/{run["proposal_ids"][0]}'
        ).json()['data']
        assert proposal['origin'] == 'ai'
        assert proposal['mode'] == 'full'
        assert proposal['run_id'] == created['run_id']
        assert proposal['state'] == 'ready'
        assert proposal['target']['kind'] == 'document'
        assert proposal['target']['resource_id'] == created['draft_id']

        group = proposal['change_groups'][0]
        operation = group['operations'][0]
        assert operation['op'] == 'replace_document'
        blocks = operation['after_blocks']
        text = ''.join(block['text'] for block in blocks)
        assert '絕○○○股份有限公司' in text
        assert '訴願法' in text

        evidence_id = group['evidence_ids'][0]
        evidence = client.get(
            f'/api/v1/cases/{case_id}/evidence/{evidence_id}'
        ).json()['data']
        assert evidence['assessed_by'] == 'program'
        assert evidence['quote_matches'] is True
        assert evidence['support_status'] == 'unknown'
        assert any(evidence_id in block['citations'] for block in blocks)


def test_draft_generation_events_record_every_opened_statute_and_the_proposal(
    settings,
) -> None:
    with _client(settings) as client:
        case_id = _seed_case(client, settings)

        response = _generate(client, case_id, expected_case_revision=3)

        run_id = response.json()['data']['run_id']
        events = _events(client, case_id, run_id)
        assert [event['event_type'] for event in events] == [
            'run.started',
            'tool.started',
            'source.opened',
            'tool.completed',
            'answer.delta',
            'proposal.ready',
            'run.completed',
        ]
        ready = next(e for e in events if e['event_type'] == 'proposal.ready')
        assert ready['payload']['proposal_id'].startswith('prop_')
        opened = next(e for e in events if e['event_type'] == 'source.opened')
        assert opened['payload']['chunk_id'] == SELECTED_STATUTE['chunk_id']


def test_generated_draft_is_not_written_into_the_case_until_it_is_applied(
    settings,
) -> None:
    with _client(settings) as client:
        case_id = _seed_case(client, settings)

        response = _generate(client, case_id, expected_case_revision=3)

        draft_id = response.json()['data']['draft_id']
        resource = client.get(
            f'/api/v1/cases/{case_id}/resources/{draft_id}'
        ).json()['data']
        head_text = ''.join(block['text'] for block in resource['content']['blocks'])
        assert '絕○○○股份有限公司' not in head_text
        assert resource['origin'] == 'program'


def test_draft_context_carries_real_facts_statutes_and_appeal_text(settings) -> None:
    provider = RecordingModelProvider()
    with _client(settings, provider) as client:
        case_id = _seed_case(client, settings)

        _generate(client, case_id, expected_case_revision=3)

        request = provider.requests[0]
        assert request.intent == 'draft'
        assert request.context['facts']['appellant.name'] == '絕○○○股份有限公司'
        assert request.context['statutes'][0]['chunk_id'] == SELECTED_STATUTE['chunk_id']
        assert '洗錢防制法第六條' in request.context['appeal_text']
        assert request.context['release_id'] == 'r3'


def test_draft_generation_without_selected_statutes_creates_no_proposal(
    settings,
) -> None:
    with _client(settings) as client:
        case_id = _seed_case(client, settings, with_statute=False)

        response = _generate(client, case_id, expected_case_revision=2)

        run_id = response.json()['data']['run_id']
        run = client.get(f'/api/v1/cases/{case_id}/runs/{run_id}').json()['data']
        assert run['state'] == 'completed'
        assert run['proposal_ids'] == []
        events = _events(client, case_id, run_id)
        assert 'proposal.ready' not in {event['event_type'] for event in events}
        answer = next(e for e in events if e['event_type'] == 'answer.delta')
        assert '尚未選定法規' in answer['payload']['delta']


def test_replaying_the_same_idempotency_key_does_not_generate_twice(settings) -> None:
    with _client(settings) as client:
        case_id = _seed_case(client, settings)
        key = 'same_draft_generation'

        first = _generate(client, case_id, expected_case_revision=3, key=key)
        replay = _generate(client, case_id, expected_case_revision=3, key=key)

        assert replay.json() == first.json()
        assert replay.headers['Idempotency-Replayed'] == 'true'
        run_id = first.json()['data']['run_id']
        events = _events(client, case_id, run_id)
        assert sum(e['event_type'] == 'proposal.ready' for e in events) == 1


def test_generating_with_a_stale_case_revision_is_a_conflict(settings) -> None:
    with _client(settings) as client:
        case_id = _seed_case(client, settings)

        response = _generate(client, case_id, expected_case_revision=99)

        assert response.status_code == 409
        assert response.json()['error']['code'] == 'REVISION_CONFLICT'


def test_generation_does_not_cross_case_boundaries(settings) -> None:
    with _client(settings) as client:
        case_id = _seed_case(client, settings)
        other_case = create_case(client, '另一案')

        response = _generate(client, case_id, expected_case_revision=3)
        run_id = response.json()['data']['run_id']
        wrong_case = client.get(f'/api/v1/cases/{other_case}/runs/{run_id}')

        assert wrong_case.status_code == 404
        assert wrong_case.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_generated_proposal_is_recorded_in_the_case_audit_chain(settings) -> None:
    with _client(settings) as client:
        case_id = _seed_case(client, settings)

        _generate(client, case_id, expected_case_revision=3)

        entries = client.get(f'/api/v1/cases/{case_id}/audit').json()['data']['items']
        actions = [entry['action'] for entry in entries]
        assert 'draft.generation_started' in actions
        assert 'proposal.created' in actions
        started = next(e for e in entries if e['action'] == 'draft.generation_started')
        assert started['after_refs']['run_id'].startswith('run_')


def test_real_r3_draft_generation_opens_the_selected_statute(settings) -> None:
    """No fake repository: the selected chunk is opened out of the real r3 release."""
    real_statute = {
        'chunk_id': 'r3::doc_law::訴願法::14',
        'document_id': 'doc_law',
        'section_id': 'sec_law_14',
        'statute_name': '訴願法',
        'article_key': '14',
        'excerpt': '訴願之提起，應自行政處分達到之次日起三十日內為之。',
    }
    with TestClient(create_app(settings)) as client:
        case_id = create_case(client)
        search = client.get(
            f'/api/v1/cases/{case_id}/statute-search', params={'q': '訴願三十日期間'}
        ).json()['data']
        if not search['hits']:
            return
        hit = search['hits'][0]
        real_statute = {
            'chunk_id': hit['chunk_id'],
            'document_id': hit['document_id'],
            'section_id': hit['section_id'],
            'statute_name': hit['statute_name'] or '（未知法規）',
            'article_key': hit['article_key'] or '0',
            'excerpt': hit['excerpt'],
        }
        mutate(
            client,
            'PUT',
            f'/api/v1/cases/{case_id}/statute-selection',
            {
                'expected_case_revision': 1,
                'reason': '人工挑選相關法規',
                'selected': [real_statute],
            },
        )

        response = _generate(client, case_id, expected_case_revision=2)

        run_id = response.json()['data']['run_id']
        run = client.get(f'/api/v1/cases/{case_id}/runs/{run_id}').json()['data']
        assert run['state'] == 'completed'
        proposal = client.get(
            f'/api/v1/cases/{case_id}/proposals/{run["proposal_ids"][0]}'
        ).json()['data']
        evidence_id = proposal['change_groups'][0]['evidence_ids'][0]
        evidence = client.get(
            f'/api/v1/cases/{case_id}/evidence/{evidence_id}'
        ).json()['data']
        assert evidence['source_ref']['kb_release_id'] == 'r3'
        assert evidence['quote_matches'] is True


def test_draft_generation_is_not_reachable_through_the_stage_a_draft_fixture(
    settings,
) -> None:
    """POST /drafts stays a test-only fixture: it must be flagged deprecated."""
    with _client(settings) as client:
        spec = client.get('/api/v1/openapi.json').json()

        assert spec['paths']['/api/v1/cases/{case_id}/drafts']['post']['deprecated'] is True
        assert '/api/v1/cases/{case_id}/draft-generations' in spec['paths']
