"""B1 run persistence: frozen context, ordered events, JSON replay and cancellation."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caseapi.db.connection import connect, transaction
from caseapi.services import run_service

from conftest import create_case, mutate


def _create_run(
    db_path: Path,
    case_id: str,
    *,
    context_manifest: dict | None = None,
    provider_config: dict | None = None,
) -> dict:
    conn = connect(db_path)
    try:
        with transaction(conn):
            return run_service.create_run(
                conn,
                case_id=case_id,
                actor_id='actor_test',
                kind='chat',
                expected_case_revision=1,
                context_manifest=context_manifest or {
                    'case_revision': 1,
                    'kb_release_id': 'r3',
                    'target': {'kind': 'case'},
                },
                prompt_version='fake-v1',
                provider_config=provider_config or {
                    'provider': 'fixed',
                    'model': 'deterministic-v1',
                },
                job_kind='chat.run',
                input_refs={'message_id': 'msg_test_1'},
            )
    finally:
        conn.close()


def _append_completed_run(db_path: Path, case_id: str, run_id: str) -> None:
    conn = connect(db_path)
    try:
        with transaction(conn):
            run_service.start_run(
                conn,
                case_id=case_id,
                actor_id='actor_test',
                run_id=run_id,
                lease_until='2026-09-12T01:00:00.000Z',
            )
            run_service.append_event(
                conn,
                case_id=case_id,
                actor_id='actor_test',
                run_id=run_id,
                event_type='tool.started',
                tool_call_id='tool_1',
                payload={'tool': 'search_knowledge'},
            )
            run_service.append_event(
                conn,
                case_id=case_id,
                actor_id='actor_test',
                run_id=run_id,
                event_type='tool.completed',
                tool_call_id='tool_1',
                payload={'hit_count': 1},
            )
            run_service.complete_run(
                conn,
                case_id=case_id,
                actor_id='actor_test',
                run_id=run_id,
                proposal_ids=[],
                payload={'message_id': 'msg_answer_1'},
            )
    finally:
        conn.close()


def test_run_creation_freezes_context_and_queues_one_job(
    client: TestClient, settings
) -> None:
    case_id = create_case(client)
    context = {
        'case_revision': 1,
        'kb_release_id': 'r3',
        'target': {'kind': 'case'},
    }

    created = _create_run(settings.db_path, case_id, context_manifest=context)
    context['kb_release_id'] = 'mutated-after-create'

    conn = connect(settings.db_path)
    try:
        row = conn.execute('SELECT * FROM ai_runs WHERE id = ?', (created['run_id'],)).fetchone()
        job = conn.execute('SELECT * FROM jobs WHERE run_id = ?', (created['run_id'],)).fetchone()
    finally:
        conn.close()

    assert row['state'] == 'queued'
    assert json.loads(row['context_manifest_json'])['kb_release_id'] == 'r3'
    assert row['last_event_sequence'] == 0
    assert job['state'] == 'queued'
    assert job['attempt'] == 0


def test_provider_config_rejects_credentials(client: TestClient, settings) -> None:
    case_id = create_case(client)

    with pytest.raises(ValueError, match='credential'):
        _create_run(
            settings.db_path,
            case_id,
            provider_config={
                'provider': 'fixed',
                'model': 'deterministic-v1',
                'api_key': 'must-not-be-stored',
            },
        )

    conn = connect(settings.db_path)
    try:
        count = conn.execute('SELECT COUNT(*) FROM ai_runs').fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_run_events_are_monotonic_and_json_replay_is_paginated(
    client: TestClient, settings
) -> None:
    case_id = create_case(client)
    created = _create_run(settings.db_path, case_id)
    _append_completed_run(settings.db_path, case_id, created['run_id'])

    run_response = client.get(f'/api/v1/cases/{case_id}/runs/{created["run_id"]}')
    events_response = client.get(
        f'/api/v1/cases/{case_id}/runs/{created["run_id"]}/events',
        params={'format': 'json', 'after_sequence': 1, 'limit': 2},
    )

    assert run_response.status_code == 200
    assert run_response.json()['data']['state'] == 'completed'
    assert run_response.json()['data']['last_event_sequence'] == 4
    assert events_response.status_code == 200
    page = events_response.json()['data']
    assert [event['sequence'] for event in page['items']] == [2, 3]
    assert page['next_after_sequence'] == 3
    assert [event['event_type'] for event in page['items']] == [
        'tool.started',
        'tool.completed',
    ]


def test_cancellation_is_idempotent_and_cancels_queued_job(
    client: TestClient, settings
) -> None:
    case_id = create_case(client)
    created = _create_run(settings.db_path, case_id)
    url = f'/api/v1/cases/{case_id}/runs/{created["run_id"]}/cancellations'
    key = 'cancel_same_run'

    first = mutate(client, 'POST', url, {'reason': '使用者取消'}, key=key)
    replay = mutate(client, 'POST', url, {'reason': '使用者取消'}, key=key)
    second_cancel = mutate(client, 'POST', url, {'reason': '再次取消'})

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()['data']['state'] == 'cancelled'
    assert second_cancel.status_code == 409
    assert second_cancel.json()['error']['code'] == 'RUN_NOT_CANCELLABLE'

    conn = connect(settings.db_path)
    try:
        job = conn.execute('SELECT state FROM jobs WHERE run_id = ?', (created['run_id'],)).fetchone()
        events = conn.execute(
            'SELECT sequence, event_type FROM run_events WHERE run_id = ?',
            (created['run_id'],),
        ).fetchall()
    finally:
        conn.close()
    assert job['state'] == 'cancelled'
    assert [(row['sequence'], row['event_type']) for row in events] == [
        (1, 'run.cancelled')
    ]


def test_run_access_is_case_scoped(client: TestClient, settings) -> None:
    first_case = create_case(client, '案件一')
    second_case = create_case(client, '案件二')
    created = _create_run(settings.db_path, first_case)

    response = client.get(f'/api/v1/cases/{second_case}/runs/{created["run_id"]}')

    assert response.status_code == 404
    assert response.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_unknown_event_type_is_rejected_without_advancing_sequence(
    client: TestClient, settings
) -> None:
    case_id = create_case(client)
    created = _create_run(settings.db_path, case_id)
    conn = connect(settings.db_path)
    try:
        with pytest.raises(ValueError, match='event type'):
            with transaction(conn):
                run_service.append_event(
                    conn,
                    case_id=case_id,
                    actor_id='actor_test',
                    run_id=created['run_id'],
                    event_type='model.claimed_it_read_everything',
                    tool_call_id=None,
                    payload={},
                )
        row = conn.execute(
            'SELECT last_event_sequence FROM ai_runs WHERE id = ?',
            (created['run_id'],),
        ).fetchone()
    finally:
        conn.close()
    assert row['last_event_sequence'] == 0
