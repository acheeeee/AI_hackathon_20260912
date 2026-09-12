"""AI run、工作與 append-only 事件的持久化服務。

所有寫入函式都假設呼叫端已開短交易。模型或工具執行不得放在交易內。
"""

import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from caseapi.clock import now_iso
from caseapi.errors import resource_not_found, run_not_cancellable, revision_conflict
from caseapi.ids import new_id
from caseapi.services.case_repository import assert_case_revision, require_case

RUN_KINDS = {'chat', 'regenerate', 'analysis'}
RUN_STATES = {'queued', 'running', 'completed', 'failed', 'cancelled', 'needs_input'}
EVENT_TYPES = {
    'run.started',
    'tool.started',
    'tool.completed',
    'tool.failed',
    'source.opened',
    'answer.delta',
    'proposal.ready',
    'run.completed',
    'run.failed',
    'run.cancelled',
    'run.needs_input',
}
TERMINAL_STATES = {'completed', 'failed', 'cancelled'}
_CREDENTIAL_KEYS = {
    'api_key',
    'apikey',
    'access_token',
    'token',
    'secret',
    'password',
    'credential',
    'credentials',
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _reject_credentials(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _CREDENTIAL_KEYS:
                raise ValueError('provider config must not contain credentials')
            _reject_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _reject_credentials(child)


def _require_run(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    run_id: str,
) -> sqlite3.Row:
    require_case(conn, case_id=case_id, actor_id=actor_id)
    row = conn.execute(
        'SELECT * FROM ai_runs WHERE id = ? AND case_id = ?',
        (run_id, case_id),
    ).fetchone()
    if row is None:
        raise resource_not_found()
    return row


def create_run(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    kind: str,
    expected_case_revision: int,
    context_manifest: dict[str, Any],
    prompt_version: str,
    provider_config: dict[str, Any],
    job_kind: str,
    input_refs: dict[str, Any],
) -> dict[str, Any]:
    """凍結一次 run 的案件基底並建立一筆 queued job。"""
    case = require_case(conn, case_id=case_id, actor_id=actor_id)
    assert_case_revision(case, expected_case_revision)
    if kind not in RUN_KINDS:
        raise ValueError('invalid run kind')
    _reject_credentials(provider_config)

    run_id = new_id('run')
    job_id = new_id('job')
    timestamp = now_iso()
    conn.execute(
        'INSERT INTO ai_runs (id, case_id, kind, state, base_case_revision,'
        ' context_manifest_json, prompt_version, provider_config_json, proposal_ids_json,'
        ' last_event_sequence, error_json, lease_until, created_by, created_at, updated_at)'
        ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, ?, ?)',
        (
            run_id,
            case_id,
            kind,
            'queued',
            expected_case_revision,
            _json(context_manifest),
            prompt_version,
            _json(provider_config),
            _json([]),
            actor_id,
            timestamp,
            timestamp,
        ),
    )
    conn.execute(
        'INSERT INTO jobs (id, case_id, run_id, kind, input_refs_json, state, attempt,'
        ' lease_until, error_json, created_at, updated_at)'
        ' VALUES (?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, ?)',
        (job_id, case_id, run_id, job_kind, _json(input_refs), 'queued', timestamp, timestamp),
    )
    return {**get_run(conn, case_id=case_id, actor_id=actor_id, run_id=run_id),
            'job_id': job_id}


def get_run(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    run_id: str,
) -> dict[str, Any]:
    return _serialize_run(
        _require_run(conn, case_id=case_id, actor_id=actor_id, run_id=run_id)
    )


def start_run(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    run_id: str,
    lease_until: str,
) -> dict[str, Any]:
    row = _require_run(conn, case_id=case_id, actor_id=actor_id, run_id=run_id)
    if row['state'] != 'queued':
        raise revision_conflict('只有 queued run 可以開始', {'state': row['state']})
    timestamp = now_iso()
    conn.execute(
        'UPDATE ai_runs SET state = ?, lease_until = ?, updated_at = ? WHERE id = ?',
        ('running', lease_until, timestamp, run_id),
    )
    cursor = conn.execute(
        'UPDATE jobs SET state = ?, attempt = attempt + 1, lease_until = ?, updated_at = ?'
        ' WHERE run_id = ? AND state = ?',
        ('running', lease_until, timestamp, run_id, 'queued'),
    )
    if cursor.rowcount != 1:
        raise revision_conflict('run 沒有可 claim 的 queued job')
    append_event(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        run_id=run_id,
        event_type='run.started',
        tool_call_id=None,
        payload={},
    )
    return get_run(conn, case_id=case_id, actor_id=actor_id, run_id=run_id)


def append_event(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    run_id: str,
    event_type: str,
    tool_call_id: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ValueError('invalid event type')
    row = _require_run(conn, case_id=case_id, actor_id=actor_id, run_id=run_id)
    sequence = row['last_event_sequence'] + 1
    timestamp = now_iso()
    conn.execute(
        'INSERT INTO run_events (run_id, sequence, event_type, tool_call_id, payload_json,'
        ' created_at) VALUES (?, ?, ?, ?, ?, ?)',
        (run_id, sequence, event_type, tool_call_id, _json(payload), timestamp),
    )
    cursor = conn.execute(
        'UPDATE ai_runs SET last_event_sequence = ?, updated_at = ?'
        ' WHERE id = ? AND last_event_sequence = ?',
        (sequence, timestamp, run_id, row['last_event_sequence']),
    )
    if cursor.rowcount != 1:
        raise revision_conflict('run 事件序號已被其他寫入推進')
    return {
        'id': sequence,
        'run_id': run_id,
        'sequence': sequence,
        'event_type': event_type,
        'tool_call_id': tool_call_id,
        'timestamp': timestamp,
        'payload': dict(payload),
    }


def complete_run(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    run_id: str,
    proposal_ids: list[str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    row = _require_run(conn, case_id=case_id, actor_id=actor_id, run_id=run_id)
    if row['state'] != 'running':
        raise revision_conflict('只有 running run 可以完成', {'state': row['state']})
    timestamp = now_iso()
    conn.execute(
        'UPDATE ai_runs SET state = ?, proposal_ids_json = ?, lease_until = NULL,'
        ' error_json = NULL, updated_at = ? WHERE id = ?',
        ('completed', _json(proposal_ids), timestamp, run_id),
    )
    conn.execute(
        'UPDATE jobs SET state = ?, lease_until = NULL, updated_at = ?'
        ' WHERE run_id = ? AND state = ?',
        ('completed', timestamp, run_id, 'running'),
    )
    append_event(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        run_id=run_id,
        event_type='run.completed',
        tool_call_id=None,
        payload={**payload, 'proposal_ids': list(proposal_ids)},
    )
    return get_run(conn, case_id=case_id, actor_id=actor_id, run_id=run_id)


def cancel_run(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    run_id: str,
    reason: str | None,
) -> dict[str, Any]:
    row = _require_run(conn, case_id=case_id, actor_id=actor_id, run_id=run_id)
    if row['state'] in TERMINAL_STATES:
        raise run_not_cancellable(row['state'])
    timestamp = now_iso()
    conn.execute(
        'UPDATE ai_runs SET state = ?, lease_until = NULL, updated_at = ? WHERE id = ?',
        ('cancelled', timestamp, run_id),
    )
    conn.execute(
        'UPDATE jobs SET state = ?, lease_until = NULL, updated_at = ?'
        ' WHERE run_id = ? AND state IN (?, ?)',
        ('cancelled', timestamp, run_id, 'queued', 'running'),
    )
    append_event(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        run_id=run_id,
        event_type='run.cancelled',
        tool_call_id=None,
        payload={'reason': reason},
    )
    return get_run(conn, case_id=case_id, actor_id=actor_id, run_id=run_id)


def list_events(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    run_id: str,
    after_sequence: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int | None]:
    _require_run(conn, case_id=case_id, actor_id=actor_id, run_id=run_id)
    rows = conn.execute(
        'SELECT * FROM run_events WHERE run_id = ? AND sequence > ?'
        ' ORDER BY sequence ASC LIMIT ?',
        (run_id, after_sequence, limit + 1),
    ).fetchall()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_sequence = page[-1]['sequence'] if has_more and page else None
    return [_serialize_event(row) for row in page], next_sequence


def _serialize_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        'run_id': row['id'],
        'case_id': row['case_id'],
        'kind': row['kind'],
        'state': row['state'],
        'base_case_revision': row['base_case_revision'],
        'context_manifest': json.loads(row['context_manifest_json']),
        'prompt_version': row['prompt_version'],
        'provider_config': json.loads(row['provider_config_json']),
        'proposal_ids': json.loads(row['proposal_ids_json']),
        'last_event_sequence': row['last_event_sequence'],
        'error': json.loads(row['error_json']) if row['error_json'] else None,
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }


def _serialize_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        'id': row['sequence'],
        'run_id': row['run_id'],
        'sequence': row['sequence'],
        'event_type': row['event_type'],
        'tool_call_id': row['tool_call_id'],
        'timestamp': row['created_at'],
        'payload': json.loads(row['payload_json']),
    }
