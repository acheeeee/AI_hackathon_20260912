"""每案 append-only 稽核鏈。

設計 03 §9：hash chain 能偵測未同步重算雜湊的內容更動，但有整庫寫權限的人
仍可能重寫全鏈。沒有外部錨定前不宣稱絕對防竄改。
"""

import hashlib
import json
import sqlite3
from typing import Any

from caseapi.clock import now_iso

DEFAULT_PAGE_SIZE = 50


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _entry_hash(prev_hash: str | None, core: dict[str, Any]) -> str:
    return hashlib.sha256(f'{prev_hash or ""}{_canonical(core)}'.encode('utf-8')).hexdigest()


def append_entry(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    action: str,
    mutation_id: str | None = None,
    before_refs: dict[str, Any] | None = None,
    after_refs: dict[str, Any] | None = None,
    reason: str | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """追加一筆稽核紀錄，回傳新建的內容。呼叫端必須已在交易中。"""
    previous = conn.execute(
        'SELECT sequence, entry_hash FROM audit_entries'
        ' WHERE case_id = ? ORDER BY sequence DESC LIMIT 1',
        (case_id,),
    ).fetchone()
    prev_hash = previous['entry_hash'] if previous else None
    sequence = previous['sequence'] + 1 if previous else 1

    created_at = now_iso()
    core = {
        'case_id': case_id,
        'sequence': sequence,
        'mutation_id': mutation_id,
        'actor_id': actor_id,
        'action': action,
        'before_refs': before_refs,
        'after_refs': after_refs,
        'reason': reason,
        'evidence_refs': evidence_refs,
        'created_at': created_at,
    }
    entry_hash = _entry_hash(prev_hash, core)

    conn.execute(
        'INSERT INTO audit_entries (case_id, sequence, mutation_id, actor_id, action,'
        ' before_refs_json, after_refs_json, reason, evidence_refs_json, prev_hash,'
        ' entry_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            case_id,
            sequence,
            mutation_id,
            actor_id,
            action,
            json.dumps(before_refs, ensure_ascii=False) if before_refs else None,
            json.dumps(after_refs, ensure_ascii=False) if after_refs else None,
            reason,
            json.dumps(evidence_refs, ensure_ascii=False) if evidence_refs else None,
            prev_hash,
            entry_hash,
            created_at,
        ),
    )
    return {**core, 'prev_hash': prev_hash, 'entry_hash': entry_hash}


def read_entries(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    after_sequence: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        'SELECT * FROM audit_entries WHERE case_id = ? AND sequence > ?'
        ' ORDER BY sequence ASC LIMIT ?',
        (case_id, after_sequence, limit),
    ).fetchall()
    return [_row_to_entry(row) for row in rows]


def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
    return {
        'case_id': row['case_id'],
        'sequence': row['sequence'],
        'mutation_id': row['mutation_id'],
        'actor_id': row['actor_id'],
        'action': row['action'],
        'before_refs': json.loads(row['before_refs_json']) if row['before_refs_json'] else None,
        'after_refs': json.loads(row['after_refs_json']) if row['after_refs_json'] else None,
        'reason': row['reason'],
        'evidence_refs': (
            json.loads(row['evidence_refs_json']) if row['evidence_refs_json'] else None
        ),
        'prev_hash': row['prev_hash'],
        'entry_hash': row['entry_hash'],
        'created_at': row['created_at'],
    }
