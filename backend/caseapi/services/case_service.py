"""案件服務。

寫入函式假設呼叫端已開啟交易（見 db.connection.transaction）；交易邊界留在
路由層，才能把案件寫入、稽核與冪等紀錄放進同一筆交易。
"""

import json
import sqlite3

from caseapi.audit import DEFAULT_PAGE_SIZE, append_entry, read_entries
from caseapi.clock import now_iso
from caseapi.errors import invalid_field
from caseapi.ids import new_id
from caseapi.schemas.case import CaseCreateRequest, CaseDetail, CaseSummary
from caseapi.services.case_repository import require_case

FIRST_REVISION = 1
MAX_PAGE_SIZE = 100

# 新案件還沒有事實與分析，依 01 的分流表落在「無法明確判別」這一列，保守走人工。
INITIAL_WORKFLOW_STATE = 'human_review'


def create_case(
    conn: sqlite3.Connection,
    *,
    actor_id: str,
    request: CaseCreateRequest,
) -> CaseDetail:
    case_id = new_id('case')
    mutation_id = new_id('mut')
    timestamp = now_iso()
    heads: dict[str, str] = {}

    conn.execute(
        'INSERT INTO cases (id, owner_id, case_revision, workflow_state, active_heads_json,'
        ' title, official_case_no, created_at, updated_at)'
        ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            case_id,
            actor_id,
            FIRST_REVISION,
            INITIAL_WORKFLOW_STATE,
            json.dumps(heads, ensure_ascii=False),
            request.title,
            request.official_case_no,
            timestamp,
            timestamp,
        ),
    )
    conn.execute(
        'INSERT INTO case_snapshots (case_id, revision, heads_json, parent_revision,'
        ' mutation_id, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (case_id, FIRST_REVISION, json.dumps(heads, ensure_ascii=False), None,
         mutation_id, actor_id, timestamp),
    )
    append_entry(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action='case.created',
        mutation_id=mutation_id,
        after_refs={'case_revision': FIRST_REVISION},
    )
    return _row_to_detail(require_case(conn, case_id=case_id, actor_id=actor_id))


def get_case(conn: sqlite3.Connection, *, case_id: str, actor_id: str) -> CaseDetail:
    return _row_to_detail(require_case(conn, case_id=case_id, actor_id=actor_id))


def list_cases(
    conn: sqlite3.Connection,
    *,
    actor_id: str,
    cursor: str | None,
    limit: int,
) -> tuple[list[CaseSummary], str | None]:
    """以 rowid 由新到舊分頁。cursor 對呼叫端是不透明字串。"""
    after_row = _decode_cursor(cursor)
    rows = conn.execute(
        'SELECT rowid AS row_seq, * FROM cases WHERE owner_id = ? AND rowid < ?'
        ' ORDER BY rowid DESC LIMIT ?',
        (actor_id, after_row, limit + 1),
    ).fetchall()

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = str(page[-1]['row_seq']) if has_more and page else None
    return [_row_to_summary(row) for row in page], next_cursor


def read_case_audit(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    cursor: str | None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[dict], str | None]:
    require_case(conn, case_id=case_id, actor_id=actor_id)
    after_sequence = 0 if cursor is None else _decode_sequence_cursor(cursor)
    entries = read_entries(conn, case_id=case_id, after_sequence=after_sequence, limit=limit + 1)

    has_more = len(entries) > limit
    page = entries[:limit]
    next_cursor = str(page[-1]['sequence']) if has_more and page else None
    return page, next_cursor


def _row_to_summary(row: sqlite3.Row) -> CaseSummary:
    return CaseSummary(
        case_id=row['id'],
        title=row['title'],
        official_case_no=row['official_case_no'],
        workflow_state=row['workflow_state'],
        case_revision=row['case_revision'],
        created_at=row['created_at'],
        updated_at=row['updated_at'],
    )


def _row_to_detail(row: sqlite3.Row) -> CaseDetail:
    return CaseDetail(
        **_row_to_summary(row).model_dump(),
        active_heads=json.loads(row['active_heads_json']),
    )


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 2**63 - 1
    return _decode_sequence_cursor(cursor)


def _decode_sequence_cursor(cursor: str) -> int:
    if not cursor.isdigit():
        raise invalid_field('cursor 格式不正確', {'field': 'cursor'})
    return int(cursor)
