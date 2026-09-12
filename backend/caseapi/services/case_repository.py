"""案件列讀取、heads 操作與正式版本推進。

heads 的形狀：{resource_id: {'revision_id': ..., 'kind': ..., 'freshness': ...}}。
freshness 是「目前指標」的屬性，不是版本內容的屬性，所以放在這裡而不是
resource_versions。所有 heads 操作都回傳新的 dict，不就地修改。
"""

import json
import sqlite3
from typing import Any

from caseapi.clock import now_iso
from caseapi.errors import resource_not_found, revision_conflict

FRESHNESS_CURRENT = 'current'
FRESHNESS_STALE = 'stale'
KIND_FACTS = 'facts'
KIND_DRAFT = 'draft'
KIND_ANNOTATION = 'annotation'


def require_case(conn: sqlite3.Connection, *, case_id: str, actor_id: str) -> sqlite3.Row:
    row = conn.execute(
        'SELECT rowid AS row_seq, * FROM cases WHERE id = ? AND owner_id = ?',
        (case_id, actor_id),
    ).fetchone()
    if row is None:
        raise resource_not_found()
    return row


def load_heads(row: sqlite3.Row) -> dict[str, dict[str, str]]:
    return json.loads(row['active_heads_json'])


def assert_case_revision(row: sqlite3.Row, expected_revision: int) -> None:
    if row['case_revision'] != expected_revision:
        raise revision_conflict(
            '案件已被其他變更推進，請重新取得目前版本',
            {'current_case_revision': row['case_revision'],
             'expected_case_revision': expected_revision},
        )


def set_head(
    heads: dict[str, dict[str, str]],
    *,
    resource_id: str,
    kind: str,
    revision_id: str,
    freshness: str,
) -> dict[str, dict[str, str]]:
    return {
        **heads,
        resource_id: {'revision_id': revision_id, 'kind': kind, 'freshness': freshness},
    }


def mark_stale(
    heads: dict[str, dict[str, str]], resource_ids: list[str]
) -> dict[str, dict[str, str]]:
    targets = set(resource_ids)
    return {
        resource_id: (
            {**head, 'freshness': FRESHNESS_STALE} if resource_id in targets else head
        )
        for resource_id, head in heads.items()
    }


def resource_ids_of_kind(heads: dict[str, dict[str, str]], kind: str) -> list[str]:
    return [
        resource_id for resource_id, head in heads.items() if head.get('kind') == kind
    ]


def advance_case(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    expected_revision: int,
    heads: dict[str, Any],
    actor_id: str,
    mutation_id: str,
) -> int:
    """以 WHERE case_revision = expected 推進案件；必須恰好更新一筆。"""
    new_revision = expected_revision + 1
    heads_json = json.dumps(heads, ensure_ascii=False)
    timestamp = now_iso()

    cursor = conn.execute(
        'UPDATE cases SET case_revision = ?, active_heads_json = ?, updated_at = ?'
        ' WHERE id = ? AND case_revision = ?',
        (new_revision, heads_json, timestamp, case_id, expected_revision),
    )
    if cursor.rowcount != 1:
        current = conn.execute(
            'SELECT case_revision FROM cases WHERE id = ?', (case_id,)
        ).fetchone()
        raise revision_conflict(
            '案件版本在寫入前已變動',
            {'current_case_revision': current['case_revision'] if current else None,
             'expected_case_revision': expected_revision},
        )

    conn.execute(
        'INSERT INTO case_snapshots (case_id, revision, heads_json, parent_revision,'
        ' mutation_id, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (case_id, new_revision, heads_json, expected_revision, mutation_id, actor_id, timestamp),
    )
    return new_revision
