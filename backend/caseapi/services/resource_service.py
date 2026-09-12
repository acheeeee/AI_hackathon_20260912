"""不可變資源版本的讀寫。內容只新增版本，不原地修改。"""

import hashlib
import json
import sqlite3
from typing import Any

from caseapi.clock import now_iso
from caseapi.errors import resource_not_found
from caseapi.ids import new_id

ORIGIN_HUMAN = 'human'
ORIGIN_AI = 'ai'
ORIGIN_MERGED = 'merged'
ORIGIN_PROGRAM = 'program'  # 規則式抽取；沒有模型參與，也不是人工輸入


def content_hash(content: dict[str, Any]) -> str:
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def save_version(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    resource_id: str,
    resource_kind: str,
    content: dict[str, Any],
    parent_id: str | None,
    origin: str,
    actor_id: str,
    dependencies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    version_id = new_id('res')
    created_at = now_iso()
    conn.execute(
        'INSERT INTO resource_versions (id, case_id, resource_id, resource_kind, parent_id,'
        ' content_json, content_hash, origin, dependencies_json, created_by, created_at)'
        ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            version_id,
            case_id,
            resource_id,
            resource_kind,
            parent_id,
            json.dumps(content, ensure_ascii=False),
            content_hash(content),
            origin,
            json.dumps(dependencies or {}, ensure_ascii=False),
            actor_id,
            created_at,
        ),
    )
    return {
        'resource_revision': version_id,
        'resource_id': resource_id,
        'resource_kind': resource_kind,
        'parent_revision': parent_id,
        'origin': origin,
        'content': content,
        'created_by': actor_id,
        'created_at': created_at,
    }


def require_version(
    conn: sqlite3.Connection, *, case_id: str, resource_id: str, revision_id: str
) -> sqlite3.Row:
    row = conn.execute(
        'SELECT * FROM resource_versions WHERE id = ? AND case_id = ? AND resource_id = ?',
        (revision_id, case_id, resource_id),
    ).fetchone()
    if row is None:
        raise resource_not_found()
    return row


def list_versions(
    conn: sqlite3.Connection, *, case_id: str, resource_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        'SELECT * FROM resource_versions WHERE case_id = ? AND resource_id = ?'
        ' ORDER BY rowid DESC',
        (case_id, resource_id),
    ).fetchall()
    if not rows:
        raise resource_not_found()
    return [
        {
            'resource_revision': row['id'],
            'parent_revision': row['parent_id'],
            'resource_kind': row['resource_kind'],
            'origin': row['origin'],
            'content_hash': row['content_hash'],
            'created_by': row['created_by'],
            'created_at': row['created_at'],
        }
        for row in rows
    ]


def row_to_payload(row: sqlite3.Row, *, freshness: str | None, is_head: bool) -> dict[str, Any]:
    return {
        'resource_id': row['resource_id'],
        'resource_kind': row['resource_kind'],
        'resource_revision': row['id'],
        'parent_revision': row['parent_id'],
        'origin': row['origin'],
        'content': json.loads(row['content_json']),
        'content_hash': row['content_hash'],
        'dependencies': json.loads(row['dependencies_json']),
        'is_head': is_head,
        'freshness': freshness if is_head else None,
        'created_by': row['created_by'],
        'created_at': row['created_at'],
    }
