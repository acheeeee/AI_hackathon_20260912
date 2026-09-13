"""Fixed-provider end-to-end chat, tools, evidence, messages and SSE replay."""

import hashlib
import json
from dataclasses import replace

from fastapi.testclient import TestClient

from caseapi.ai.contracts import ModelResult
from caseapi.ai.fixed_provider import FixedModelProvider
from caseapi.db.connection import connect, transaction
from caseapi.evidence.repository import OpenedSource, SearchHit
from caseapi.main import create_app
from caseapi.services import run_service

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
                chunk_id=f'chk_law_{article}',
                document_id=self.opened.document_id,
                section_id=f'sec_law_{article}',
                document_type='statute',
                case_family_id=None,
                excerpt=self.opened.quote_text,
                source_spans=self.opened.source_spans,
                metadata={'statute_name': '訴願法', 'article_key': article},
                score=4.0 - index,
                index_eligible=True,
            )
            for index, article in enumerate(('14', '15', '16'))
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


class FailingModelProvider:
    prompt_version = 'failing-test-v1'

    def descriptor(self) -> dict[str, str]:
        return {'provider': 'fixed-test-failure', 'model': 'deterministic-failure'}

    def execute(self, request, tools):
        del request, tools
        raise RuntimeError('provider exploded with private input')


class CancellingModelProvider:
    """Simulates a user cancelling a run while the provider is still executing."""

    prompt_version = 'cancel-race-test-v1'

    def __init__(self, db_path, actor_id: str) -> None:
        self._db_path = db_path
        self._actor_id = actor_id

    def descriptor(self) -> dict[str, str]:
        return {'provider': 'fixed-test-cancel-race', 'model': 'deterministic-cancel'}

    def execute(self, request, tools):
        del tools
        conn = connect(self._db_path)
        try:
            with transaction(conn):
                run_service.cancel_run(
                    conn,
                    case_id=request.case_id,
                    actor_id=self._actor_id,
                    run_id=request.run_id,
                    reason='user cancelled mid-flight',
                )
        finally:
            conn.close()
        return ModelResult('answer generated after cancellation')


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
            '已核對法規原文：「訴願應於三十日內提起。」；'
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
        search_completed = next(
            event
            for event in events
            if event['event_type'] == 'tool.completed'
            and event['payload']['tool'] == 'search_knowledge'
        )
        assert search_completed['payload']['hit_count'] == 3
        assert sum(event['event_type'] == 'source.opened' for event in events) == 1
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
            '法規資料庫未找到足夠依據；尚未確認最新法規。'
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
            '選取內容：「選取文字」。'
            '自動分析已讀取指定內容，未作法律判斷。'
        )
        assert [event['event_type'] for event in events] == [
            'run.started',
            'tool.started',
            'tool.completed',
            'answer.delta',
            'run.completed',
        ]


def test_fixed_explain_reads_a_fact_field_value(settings) -> None:
    """A fact_field target's writable_target has no selected_text key (that
    only exists on draft_block targets) — the actual value lives in
    context.field instead, and the provider has to know to look there.
    """
    with _fixed_client(settings) as client:
        case_id = create_case(client)
        patch_response = mutate(
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
        facts_revision = patch_response.json()['data']['resource_revision']
        thread_id = _create_thread(client, case_id)

        response = _send_message(
            client,
            case_id,
            thread_id,
            content='這個欄位是什麼意思？',
            intent='explain',
            expected_case_revision=2,
            target={
                'kind': 'fact_field',
                'resource_id': 'facts',
                'resource_revision': facts_revision,
                'field_path': 'appellant.name',
            },
        )

        run_id = response.json()['data']['run_id']
        messages = client.get(
            f'/api/v1/cases/{case_id}/chat-threads/{thread_id}/messages'
        ).json()['data']['items']
        assert '絕○○○股份有限公司' in messages[-1]['content']


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


def test_runner_failure_is_persisted_without_leaking_exception_text(settings) -> None:
    with TestClient(
        create_app(
            settings,
            evidence_repository=FakeEvidenceRepository(),
            model_provider=FailingModelProvider(),
        )
    ) as client:
        case_id = create_case(client)
        thread_id = _create_thread(client, case_id)

        response = _send_message(
            client,
            case_id,
            thread_id,
            content='私人案件內容',
            intent='verify',
            expected_case_revision=1,
        )

        run_id = response.json()['data']['run_id']
        run = client.get(f'/api/v1/cases/{case_id}/runs/{run_id}').json()['data']
        assert run['state'] == 'failed'
        assert run['error'] == {
            'code': 'MODEL_RUN_FAILED',
            'type': 'RuntimeError',
        }
        events = client.get(
            f'/api/v1/cases/{case_id}/runs/{run_id}/events',
            params={'format': 'json'},
        ).json()['data']['items']
        assert [event['event_type'] for event in events] == [
            'run.started',
            'run.failed',
        ]
        conn = connect(settings.db_path)
        try:
            job = conn.execute(
                'SELECT state, error_json FROM jobs WHERE run_id = ?',
                (run_id,),
            ).fetchone()
        finally:
            conn.close()
        assert job['state'] == 'failed'
        assert 'private input' not in json.dumps(run['error'])
        assert 'private input' not in job['error_json']
        assert create_draft(client, case_id)['resource_revision']


def test_cancelling_a_running_run_survives_a_provider_that_finishes_late(
    settings,
) -> None:
    with TestClient(
        create_app(
            settings,
            evidence_repository=FakeEvidenceRepository(),
            model_provider=CancellingModelProvider(
                settings.db_path, settings.actor_id
            ),
        )
    ) as client:
        case_id = create_case(client)
        thread_id = _create_thread(client, case_id)

        response = _send_message(
            client,
            case_id,
            thread_id,
            content='私人案件內容',
            intent='verify',
            expected_case_revision=1,
        )

        run_id = response.json()['data']['run_id']
        run = client.get(f'/api/v1/cases/{case_id}/runs/{run_id}').json()['data']
        assert run['state'] == 'cancelled'
        events = client.get(
            f'/api/v1/cases/{case_id}/runs/{run_id}/events',
            params={'format': 'json'},
        ).json()['data']['items']
        assert [event['event_type'] for event in events] == [
            'run.started',
            'run.cancelled',
        ]
        messages = client.get(
            f'/api/v1/cases/{case_id}/chat-threads/{thread_id}/messages'
        ).json()['data']['items']
        assert [message['role'] for message in messages] == ['user']


def test_chat_and_evidence_reads_do_not_cross_case_boundaries(settings) -> None:
    with _fixed_client(settings) as client:
        first_case = create_case(client, '案件一')
        second_case = create_case(client, '案件二')
        thread_id = _create_thread(client, first_case)
        response = _send_message(
            client,
            first_case,
            thread_id,
            content='訴願期限是多少？',
            intent='verify',
            expected_case_revision=1,
        )
        run_id = response.json()['data']['run_id']
        events = client.get(
            f'/api/v1/cases/{first_case}/runs/{run_id}/events',
            params={'format': 'json'},
        ).json()['data']['items']
        evidence_id = next(
            event['payload']['evidence_id']
            for event in events
            if event['event_type'] == 'source.opened'
        )

        wrong_thread = client.get(
            f'/api/v1/cases/{second_case}/chat-threads/{thread_id}/messages'
        )
        wrong_evidence = client.get(
            f'/api/v1/cases/{second_case}/evidence/{evidence_id}'
        )

        assert wrong_thread.status_code == 404
        assert wrong_evidence.status_code == 404
        assert wrong_thread.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
        assert wrong_evidence.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_default_fixed_model_opens_program_verified_source_from_real_r3(settings) -> None:
    with TestClient(create_app(settings)) as client:
        case_id = create_case(client)
        thread_id = _create_thread(client, case_id)

        response = _send_message(
            client,
            case_id,
            thread_id,
            content='訴願應自行政處分達到次日起三十日內提起',
            intent='verify',
            expected_case_revision=1,
        )

        run_id = response.json()['data']['run_id']
        run = client.get(f'/api/v1/cases/{case_id}/runs/{run_id}').json()['data']
        events = client.get(
            f'/api/v1/cases/{case_id}/runs/{run_id}/events',
            params={'format': 'json'},
        ).json()['data']['items']
        messages = client.get(
            f'/api/v1/cases/{case_id}/chat-threads/{thread_id}/messages'
        ).json()['data']['items']
        evidence_id = next(
            event['payload']['evidence_id']
            for event in events
            if event['event_type'] == 'source.opened'
        )
        evidence = client.get(
            f'/api/v1/cases/{case_id}/evidence/{evidence_id}'
        ).json()['data']

        assert run['state'] == 'completed'
        assert messages[-1]['content'].startswith('已核對法規原文：')
        assert evidence['source_exists'] is True
        assert evidence['quote_matches'] is True
        assert evidence['source_ref']['kb_release_id'] == 'r3'
