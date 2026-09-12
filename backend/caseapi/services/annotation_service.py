"""註記。

01 §4：註記只增加討論材料，不改事實、不解除黃燈，所以不推進 case_revision。
內容每次編修存成一個新的 resource version，舊的說法仍可回查。
"""

import json
import sqlite3
from typing import Any

from caseapi.audit import append_entry
from caseapi.clock import now_iso
from caseapi.errors import invalid_field, resource_not_found, revision_conflict, target_moved
from caseapi.ids import new_id
from caseapi.schemas.annotation import (
    STATUS_OPEN,
    AnnotationCreateRequest,
    AnnotationPatchRequest,
)
from caseapi.services import case_repository as repo
from caseapi.services import resource_service
from caseapi.services.facts_service import FACTS_RESOURCE_ID

# A2 還沒有 analyses 與來源快照表，這兩種目標只驗形狀，不驗存在性。
_TARGET_KINDS_WITHOUT_STORAGE = frozenset({'gate_result', 'source_span'})


def create_annotation(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    request: AnnotationCreateRequest,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    _validate_target(conn, case_id=case_id, target=request.target)

    annotation_id = new_id('note')
    timestamp = now_iso()
    version = resource_service.save_version(
        conn,
        case_id=case_id,
        resource_id=annotation_id,
        resource_kind=repo.KIND_ANNOTATION,
        content={'body': request.body},
        parent_id=None,
        origin=resource_service.ORIGIN_HUMAN,
        actor_id=actor_id,
    )
    conn.execute(
        'INSERT INTO annotations (id, case_id, target_json, status, current_revision_id,'
        ' created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (
            annotation_id,
            case_id,
            json.dumps(request.target.model_dump(), ensure_ascii=False),
            STATUS_OPEN,
            version['resource_revision'],
            actor_id,
            timestamp,
            timestamp,
        ),
    )
    append_entry(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action='annotation.created',
        after_refs={'annotation_id': annotation_id,
                    'annotation_revision': version['resource_revision']},
    )
    return _payload(
        annotation_id=annotation_id,
        target=request.target.model_dump(),
        status=STATUS_OPEN,
        revision_id=version['resource_revision'],
        body=request.body,
        case_revision=case_row['case_revision'],
        created_at=timestamp,
        updated_at=timestamp,
    )


def patch_annotation(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    annotation_id: str,
    request: AnnotationPatchRequest,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    row = _require_annotation(conn, case_id=case_id, annotation_id=annotation_id)

    if row['current_revision_id'] != request.expected_annotation_revision:
        raise revision_conflict(
            '註記已被更新，請重新取得目前版本',
            {'current_annotation_revision': row['current_revision_id'],
             'expected_annotation_revision': request.expected_annotation_revision},
        )

    current = resource_service.require_version(
        conn,
        case_id=case_id,
        resource_id=annotation_id,
        revision_id=row['current_revision_id'],
    )
    body = request.body if request.body is not None else json.loads(current['content_json'])['body']
    status = request.status or row['status']
    timestamp = now_iso()

    version = resource_service.save_version(
        conn,
        case_id=case_id,
        resource_id=annotation_id,
        resource_kind=repo.KIND_ANNOTATION,
        content={'body': body},
        parent_id=row['current_revision_id'],
        origin=resource_service.ORIGIN_HUMAN,
        actor_id=actor_id,
    )
    conn.execute(
        'UPDATE annotations SET status = ?, current_revision_id = ?, updated_at = ? WHERE id = ?',
        (status, version['resource_revision'], timestamp, annotation_id),
    )
    append_entry(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action='annotation.updated',
        before_refs={'annotation_revision': row['current_revision_id'], 'status': row['status']},
        after_refs={'annotation_revision': version['resource_revision'], 'status': status},
    )
    return _payload(
        annotation_id=annotation_id,
        target=json.loads(row['target_json']),
        status=status,
        revision_id=version['resource_revision'],
        body=body,
        case_revision=case_row['case_revision'],
        created_at=row['created_at'],
        updated_at=timestamp,
    )


def get_annotation(
    conn: sqlite3.Connection, *, case_id: str, actor_id: str, annotation_id: str
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    row = _require_annotation(conn, case_id=case_id, annotation_id=annotation_id)
    return _row_to_payload(conn, row=row, case_revision=case_row['case_revision'])


def list_annotations(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    resource_id: str | None,
) -> list[dict[str, Any]]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    rows = conn.execute(
        'SELECT * FROM annotations WHERE case_id = ? ORDER BY rowid ASC', (case_id,)
    ).fetchall()
    payloads = [
        _row_to_payload(conn, row=row, case_revision=case_row['case_revision']) for row in rows
    ]
    if resource_id is None:
        return payloads
    return [item for item in payloads if item['target']['resource_id'] == resource_id]


def _require_annotation(
    conn: sqlite3.Connection, *, case_id: str, annotation_id: str
) -> sqlite3.Row:
    row = conn.execute(
        'SELECT * FROM annotations WHERE id = ? AND case_id = ?', (annotation_id, case_id)
    ).fetchone()
    if row is None:
        raise resource_not_found()
    return row


def _row_to_payload(
    conn: sqlite3.Connection, *, row: sqlite3.Row, case_revision: int
) -> dict[str, Any]:
    version = resource_service.require_version(
        conn,
        case_id=row['case_id'],
        resource_id=row['id'],
        revision_id=row['current_revision_id'],
    )
    return _payload(
        annotation_id=row['id'],
        target=json.loads(row['target_json']),
        status=row['status'],
        revision_id=row['current_revision_id'],
        body=json.loads(version['content_json'])['body'],
        case_revision=case_revision,
        created_at=row['created_at'],
        updated_at=row['updated_at'],
    )


def _payload(
    *,
    annotation_id: str,
    target: dict[str, Any],
    status: str,
    revision_id: str,
    body: str,
    case_revision: int,
    created_at: str,
    updated_at: str,
) -> dict[str, Any]:
    return {
        'annotation_id': annotation_id,
        'annotation_revision': revision_id,
        'target': target,
        'status': status,
        'body': body,
        'case_revision': case_revision,
        'created_at': created_at,
        'updated_at': updated_at,
    }


def _validate_target(conn: sqlite3.Connection, *, case_id: str, target: Any) -> None:
    """目標必須屬於本案；草稿選取還要從指定版本重建文字核對。"""
    if target.kind in _TARGET_KINDS_WITHOUT_STORAGE:
        return

    resource_id = FACTS_RESOURCE_ID if target.kind == 'fact_field' else target.resource_id
    if target.kind == 'fact_field' and target.resource_id != FACTS_RESOURCE_ID:
        raise invalid_field(
            'fact_field 目標的 resource_id 必須是 facts', {'field': 'target.resource_id'}
        )

    row = resource_service.require_version(
        conn, case_id=case_id, resource_id=resource_id, revision_id=target.resource_revision
    )
    if target.kind == 'draft_block':
        _assert_selection_matches(json.loads(row['content_json']), target)


def _assert_selection_matches(content: dict[str, Any], target: Any) -> None:
    block = next(
        (item for item in content.get('blocks', []) if item['block_id'] == target.block_id),
        None,
    )
    if block is None:
        raise target_moved('指定的區塊不在這個版本裡', {'block_id': target.block_id})

    actual = block['text'][target.char_start:target.char_end]
    if actual != target.selected_text:
        raise invalid_field(
            '選取範圍與該版本的實際文字不符，請重新選取',
            {'block_id': target.block_id, 'char_start': target.char_start,
             'char_end': target.char_end},
        )
