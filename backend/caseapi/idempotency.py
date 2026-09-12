"""冪等鍵。

契約 §1：同 key 同內容重送回原結果；同 key 不同內容回 IDEMPOTENCY_KEY_REUSED。
key 由 actor、案件範圍與端點共同限定。
"""

import hashlib
import json
import sqlite3
from typing import Any

from caseapi.clock import now_iso
from caseapi.errors import idempotency_key_reused

GLOBAL_SCOPE = '-'


def request_fingerprint(body: Any) -> str:
    payload = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def find_stored_response(
    conn: sqlite3.Connection,
    *,
    actor_id: str,
    case_scope: str,
    endpoint: str,
    key: str,
    request_hash: str,
) -> tuple[int, dict[str, Any]] | None:
    """找到同 key 紀錄時回傳原本的狀態碼與回應；內容不同則丟 409。"""
    row = conn.execute(
        'SELECT request_hash, status_code, response_json FROM idempotency_records'
        ' WHERE actor_id = ? AND case_scope = ? AND endpoint = ? AND key = ?',
        (actor_id, case_scope, endpoint, key),
    ).fetchone()
    if row is None:
        return None
    if row['request_hash'] != request_hash:
        raise idempotency_key_reused()
    return row['status_code'], json.loads(row['response_json'])


def remember_response(
    conn: sqlite3.Connection,
    *,
    actor_id: str,
    case_scope: str,
    endpoint: str,
    key: str,
    request_hash: str,
    status_code: int,
    response: dict[str, Any],
) -> None:
    conn.execute(
        'INSERT INTO idempotency_records (actor_id, case_scope, endpoint, key, request_hash,'
        ' status_code, response_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (
            actor_id,
            case_scope,
            endpoint,
            key,
            request_hash,
            status_code,
            json.dumps(response, ensure_ascii=False),
            now_iso(),
        ),
    )
