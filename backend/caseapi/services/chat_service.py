"""Case-scoped chat threads, immutable messages and run creation."""

import json
import sqlite3
from typing import Any

from caseapi.clock import now_iso
from caseapi.errors import resource_not_found
from caseapi.ids import new_id
from caseapi.schemas.chat import ChatMessageCreateRequest
from caseapi.services import case_repository, run_service


def create_thread(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    title: str | None,
) -> dict[str, Any]:
    case = case_repository.require_case(conn, case_id=case_id, actor_id=actor_id)
    thread_id = new_id('thread')
    created_at = now_iso()
    conn.execute(
        'INSERT INTO chat_threads (id, case_id, title, created_by, created_at)'
        ' VALUES (?, ?, ?, ?, ?)',
        (thread_id, case_id, title, actor_id, created_at),
    )
    return {
        'thread_id': thread_id,
        'case_id': case_id,
        'title': title,
        'case_revision': case['case_revision'],
        'created_at': created_at,
    }


def create_message_run(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    thread_id: str,
    actor_id: str,
    request: ChatMessageCreateRequest,
    prompt_version: str,
    provider_config: dict[str, Any],
    kb_release_id: str,
) -> dict[str, Any]:
    case = case_repository.require_case(conn, case_id=case_id, actor_id=actor_id)
    case_repository.assert_case_revision(case, request.expected_case_revision)
    require_thread(conn, case_id=case_id, thread_id=thread_id)
    target = request.target.model_dump() if request.target else None
    message_id = _save_user_message(
        conn,
        case_id=case_id,
        thread_id=thread_id,
        request=request,
        target=target,
    )
    run = run_service.create_run(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        kind='chat',
        expected_case_revision=request.expected_case_revision,
        context_manifest={
            'case_revision': request.expected_case_revision,
            'kb_release_id': kb_release_id,
            'thread_id': thread_id,
            'user_message_id': message_id,
            'target': target,
            'annotation_refs': [item.model_dump() for item in request.annotation_refs],
        },
        prompt_version=prompt_version,
        provider_config=provider_config,
        job_kind='chat.run',
        input_refs={'thread_id': thread_id, 'message_id': message_id},
    )
    conn.execute('UPDATE messages SET run_id = ? WHERE id = ?', (run['run_id'], message_id))
    return {
        'message_id': message_id,
        'run_id': run['run_id'],
        'state': run['state'],
        'case_revision': case['case_revision'],
    }


def _save_user_message(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    thread_id: str,
    request: ChatMessageCreateRequest,
    target: dict[str, Any] | None,
) -> str:
    message_id = new_id('msg')
    conn.execute(
        'INSERT INTO messages (id, case_id, thread_id, role, content, intent,'
        ' target_json, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)',
        (
            message_id,
            case_id,
            thread_id,
            'user',
            request.content,
            request.intent,
            _json_or_none(target),
            now_iso(),
        ),
    )
    return message_id


def list_messages(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    thread_id: str,
    actor_id: str,
) -> list[dict[str, Any]]:
    case_repository.require_case(conn, case_id=case_id, actor_id=actor_id)
    require_thread(conn, case_id=case_id, thread_id=thread_id)
    rows = conn.execute(
        'SELECT * FROM messages WHERE case_id = ? AND thread_id = ? ORDER BY rowid ASC',
        (case_id, thread_id),
    ).fetchall()
    return [_message_payload(row) for row in rows]


def load_user_message(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    thread_id: str,
    message_id: str,
    run_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        'SELECT * FROM messages WHERE id = ? AND case_id = ? AND thread_id = ?'
        ' AND run_id = ? AND role = ?',
        (message_id, case_id, thread_id, run_id, 'user'),
    ).fetchone()
    if row is None:
        raise resource_not_found()
    return _message_payload(row)


def save_assistant_message(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    thread_id: str,
    run_id: str,
    content: str,
) -> dict[str, Any]:
    message_id = new_id('msg')
    created_at = now_iso()
    conn.execute(
        'INSERT INTO messages (id, case_id, thread_id, role, content, intent,'
        ' target_json, run_id, created_at) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)',
        (message_id, case_id, thread_id, 'assistant', content, run_id, created_at),
    )
    return {'message_id': message_id, 'content': content, 'created_at': created_at}


def require_thread(
    conn: sqlite3.Connection, *, case_id: str, thread_id: str
) -> sqlite3.Row:
    row = conn.execute(
        'SELECT * FROM chat_threads WHERE id = ? AND case_id = ?',
        (thread_id, case_id),
    ).fetchone()
    if row is None:
        raise resource_not_found()
    return row


def _message_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        'message_id': row['id'],
        'case_id': row['case_id'],
        'thread_id': row['thread_id'],
        'role': row['role'],
        'content': row['content'],
        'intent': row['intent'],
        'target': json.loads(row['target_json']) if row['target_json'] else None,
        'run_id': row['run_id'],
        'created_at': row['created_at'],
    }


def _json_or_none(value: Any) -> str | None:
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else None
