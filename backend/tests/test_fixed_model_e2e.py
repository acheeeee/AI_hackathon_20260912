"""Fixed-provider end-to-end chat, tools, evidence, messages and SSE replay."""

import hashlib
from dataclasses import replace

from fastapi.testclient import TestClient

from caseapi.ai.fixed_provider import FixedModelProvider
from caseapi.evidence.repository import OpenedSource, SearchHit
from caseapi.main import create_app

from conftest import block_target, create_case, create_draft, mutate


class FakeEvidenceRepository:
    release_id = 'r3'

    def __init__(self) -> None:
        quote = '訴願應於三十日內提起。'
        self.opened = OpenedSource(
            release_id='r3',
            chunk_id='chk_law_14',
            document_id='doc_law',
            section_id='sec_law_14',
            quote_text=quote,
            source_spans=(
                {
                    'document_id': 'doc_law',
                    'extraction_version': 'ext-2.0',
                    'page': 1,
                    'line': 1,
                    'char_start': 0,
                    'char_end': len(quote),
                },
            ),
            source_file='data/raw/相關法規/訴願法.pdf',
            source_sha256='law-sha',
            content_hash=hashlib.sha256(quote.encode('utf-8')).hexdigest(),
            source_exists=True,
            quote_matches=True,
            temporal_status='snapshot_only',
            metadata={'statute_name': '訴願法', 'article_key': '14'},
        )

    def search(self, query: str, **_: object) -> list[SearchHit]:
        if query == '完全查無資料':
            return []
        return [
            SearchHit(
                release_id='r3',
                chunk_id=self.opened.chunk_id,
                document_id=self.opened.document_id,
                section_id=self.opened.section_id,
                document_type='statute',
                case_family_id=None,
                excerpt=self.opened.quote_text,
                source_spans=self.opened.source_spans,
                metadata=self.opened.metadata,
                score=3.5,
                index_eligible=True,
            )
        ]

    def open_source(self, chunk_id: str) -> OpenedSource:
        return replace(self.opened, chunk_id=chunk_id)


def _fixed_client(settings) -> TestClient:
    return TestClient(
        create_app(
            settings,
            evidence_repository=FakeEvidenceRepository(),
            model_provider=FixedModelProvider(),
        )
    )


def _create_thread(client: TestClient, case_id: str) -> str:
    response = mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/chat-threads',
        {'title': '期限查證'},
    )
    assert response.status_code == 201
    return response.json()['data']['thread_id']


def _send_message(
    client: TestClient,
    case_id: str,
    thread_id: str,
    *,
    content: str,
    intent: str,
    expected_case_revision: int,
    target: dict | None = None,
    key: str | None = None,
):
    return mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/chat-threads/{thread_id}/messages',
        {
            'expected_case_revision': expected_case_revision,
            'content': content,
            'intent': intent,
            'target': target,
            'annotation_refs': [],
        },
        key=key,
    )


def test_fixed_verify_flow_persists_answer_evidence_and_ordered_events(settings) -> None:
    with _fixed_client(settings) as client:
        case_id = create_case(client)
        thread_id = _create_thread(client, case_id)

        response = _send_message(
            client,
            case_id,
            thread_id,
            content='訴願期限是多少？',
            intent='verify',
            expected_case_revision=1,
            key='fixed_verify_once',
        )

        assert response.status_code == 202
        created = response.json()['data']
        assert created['state'] == 'queued'
        run = client.get(
            f'/api/v1/cases/{case_id}/runs/{created["run_id"]}'
        ).json()['data']
        messages = client.get(
            f'/api/v1/cases/{case_id}/chat-threads/{thread_id}/messages'
        ).json()['data']['items']
        events = client.get(
            f'/api/v1/cases/{case_id}/runs/{created["run_id"]}/events',
            params={'format': 'json'},
        ).json()['data']['items']

        assert run['state'] == 'completed'
        assert run['provider_config'] == {
            'provider': 'fixed',
            'model': 'deterministic-v1',
        }
        assert run['proposal_ids'] == []
        assert [message['role'] for message in messages] == ['user', 'assistant']
        assert messages[1]['content'] == (
            '已查閱 r3 原文：「訴願應於三十日內提起。」；'
            '此來源僅證明引文存在且一致，是否支持本案主張仍待判斷。'
        )
        assert [event['event_type'] for event in events] == [
            'run.started',
            'tool.started',
            'tool.completed',
            'tool.started',
            'source.opened',
            'tool.completed',
            'answer.delta',
            'run.completed',
        ]
        evidence_id = next(
            event['payload']['evidence_id']
            for event in events
            if event['event_type'] == 'source.opened'
        )
        evidence = client.get(
            f'/api/v1/cases/{case_id}/evidence/{evidence_id}'
        ).json()['data']
        assert evidence['assessed_by'] == 'program'
        assert evidence['quote_matches'] is True
        assert evidence['support_status'] == 'unknown'


def test_message_idempotency_does_not_rerun_fixed_provider(settings) -> None:
    with _fixed_client(settings) as client:
        case_id = create_case(client)
        thread_id = _create_thread(client, case_id)
        key = 'same_fixed_message'

        first = _send_message(
            client,
            case_id,
            thread_id,
            content='訴願期限是多少？',
            intent='verify',
            expected_case_revision=1,
            key=key,
        )
        replay = _send_message(
            client,
            case_id,
            thread_id,
            content='訴願期限是多少？',
            intent='verify',
            expected_case_revision=1,
            key=key,
        )

        assert replay.json() == first.json()
        assert replay.headers['Idempotency-Replayed'] == 'true'
        run_id = first.json()['data']['run_id']
        events = client.get(
            f'/api/v1/cases/{case_id}/runs/{run_id}/events',
            params={'format': 'json'},
        ).json()['data']['items']
        messages = client.get(
            f'/api/v1/cases/{case_id}/chat-threads/{thread_id}/messages'
        ).json()['data']['items']
        assert len(events) == 8
        assert len(messages) == 2


def test_fixed_verify_no_hit_states_snapshot_gap_without_evidence(settings) -> None:
    with _fixed_client(settings) as client:
        case_id = create_case(client)
        thread_id = _create_thread(client, case_id)

        response = _send_message(
            client,
            case_id,
            thread_id,
            content='完全查無資料',
            intent='verify',
            expected_case_revision=1,
        )

        run_id = response.json()['data']['run_id']
        messages = client.get(
            f'/api/v1/cases/{case_id}/chat-threads/{thread_id}/messages'
        ).json()['data']['items']
        events = client.get(
            f'/api/v1/cases/{case_id}/runs/{run_id}/events',
            params={'format': 'json'},
        ).json()['data']['items']
        assert messages[-1]['content'] == (
            '本地 r3 快照未找到足夠依據；尚未確認最新法規。'
        )
        assert 'source.opened' not in {event['event_type'] for event in events}
        assert client.get(
            f'/api/v1/cases/{case_id}/runs/{run_id}'
        ).json()['data']['state'] == 'completed'


def test_fixed_explain_reads_only_bounded_selection_context(settings) -> None:
    with _fixed_client(settings) as client:
        case_id = create_case(client)
        draft = create_draft(
            client,
            case_id,
            blocks=[
                {'block_id': 'before', 'text': '前段'},
                {'block_id': 'selected', 'text': '選取文字'},
                {'block_id': 'after', 'text': '後段'},
            ],
        )
        thread_id = _create_thread(client, case_id)

        response = _send_message(
            client,
            case_id,
            thread_id,
            content='解釋這段',
            intent='explain',
            expected_case_revision=2,
            target=block_target(draft, 'selected', '選取文字'),
        )

        run_id = response.json()['data']['run_id']
        messages = client.get(
            f'/api/v1/cases/{case_id}/chat-threads/{thread_id}/messages'
        ).json()['data']['items']
        events = client.get(
            f'/api/v1/cases/{case_id}/runs/{run_id}/events',
            params={'format': 'json'},
        ).json()['data']['items']
        assert messages[-1]['content'] == (
            '選取內容：「選取文字」。固定模型只確認上下文讀取鏈，未作法律判斷。'
        )
        assert [event['event_type'] for event in events] == [
            'run.started',
            'tool.started',
            'tool.completed',
            'answer.delta',
            'run.completed',
        ]


def test_sse_replays_only_events_after_last_event_id_without_rerun(settings) -> None:
    with _fixed_client(settings) as client:
        case_id = create_case(client)
        thread_id = _create_thread(client, case_id)
        response = _send_message(
            client,
            case_id,
            thread_id,
            content='訴願期限是多少？',
            intent='verify',
            expected_case_revision=1,
        )
        run_id = response.json()['data']['run_id']

        replay = client.get(
            f'/api/v1/cases/{case_id}/runs/{run_id}/events',
            params={'format': 'sse'},
            headers={'Last-Event-ID': '5'},
        )

        assert replay.status_code == 200
        assert replay.headers['content-type'].startswith('text/event-stream')
        assert 'id: 5\n' not in replay.text
        assert 'id: 6\n' in replay.text
        assert 'id: 8\n' in replay.text
        assert 'event: tool.completed\n' in replay.text
        assert 'event: run.completed\n' in replay.text
        events = client.get(
            f'/api/v1/cases/{case_id}/runs/{run_id}/events',
            params={'format': 'json'},
        ).json()['data']['items']
        assert len(events) == 8
