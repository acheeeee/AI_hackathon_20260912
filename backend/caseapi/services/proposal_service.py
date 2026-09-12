"""提案建立、讀取與拒絕。

契約 §2 與設計 02 §6：候選只能用 allowlist 操作，必須落在核准範圍內，
基底文字要與已凍結版本一致。提案不碰正式內容，也不推進 case_revision。
"""

import hashlib
import json
import sqlite3
from typing import Any

from caseapi.audit import append_entry
from caseapi.clock import now_iso
from caseapi.errors import (
    invalid_citation,
    invalid_field,
    out_of_scope_patch,
    resource_not_found,
)
from caseapi.ids import new_id
from caseapi.schemas.evidence import (
    ASSESSED_BY_UNVERIFIED,
    SUPPORT_UNKNOWN,
    TEMPORAL_UNKNOWN,
    EvidenceInput,
)
from caseapi.schemas.proposal import (
    STATE_APPLIED,
    STATE_PARTIALLY_APPLIED,
    STATE_READY,
    STATE_REJECTED,
    ChangeGroup,
    ProposalCreateRequest,
    RejectionRequest,
)
from caseapi.services import case_repository as repo
from caseapi.services import resource_service
from caseapi.services.facts_service import FACTS_RESOURCE_ID

CITATION_OPS = frozenset({'add_citation', 'remove_citation'})


def create_proposal(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    request: ProposalCreateRequest,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    repo.assert_case_revision(case_row, request.expected_case_revision)

    _assert_document_group_is_indivisible(request)
    for group in request.change_groups:
        for operation in group.operations:
            _assert_within_scope(request, operation)
            _assert_base_matches(conn, case_id=case_id, operation=operation)

    _store_evidence(conn, case_id=case_id, evidence=request.evidence)
    _assert_evidence_exists(conn, case_id=case_id, request=request)

    proposal_id = new_id('prop')
    candidate = {
        'target': request.target.model_dump(),
        'dependencies': request.dependencies.model_dump(),
        'change_groups': [group.model_dump() for group in request.change_groups],
    }
    dependencies_json = json.dumps(
        request.dependencies.model_dump(), sort_keys=True, ensure_ascii=False
    )
    created_at = now_iso()

    conn.execute(
        'INSERT INTO proposals (id, case_id, origin, run_id, reverts_mutation_id, mode,'
        ' base_case_revision, target_json, dependencies_json, candidate_json, dependency_hash,'
        ' state, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            proposal_id,
            case_id,
            request.origin,
            request.run_id,
            None,
            request.mode,
            request.expected_case_revision,
            json.dumps(request.target.model_dump(), ensure_ascii=False),
            dependencies_json,
            json.dumps(candidate, ensure_ascii=False),
            hashlib.sha256(dependencies_json.encode('utf-8')).hexdigest(),
            STATE_READY,
            actor_id,
            created_at,
        ),
    )
    append_entry(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action='proposal.created',
        after_refs={
            'proposal_id': proposal_id,
            'group_ids': [group.id for group in request.change_groups],
        },
    )
    return read_proposal(conn, case_id=case_id, actor_id=actor_id, proposal_id=proposal_id)


def read_proposal(
    conn: sqlite3.Connection, *, case_id: str, actor_id: str, proposal_id: str
) -> dict[str, Any]:
    repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    row = require_proposal(conn, case_id=case_id, proposal_id=proposal_id)
    return row_to_payload(conn, row=row)


def reject_proposal(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    proposal_id: str,
    request: RejectionRequest,
) -> dict[str, Any]:
    repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    row = require_proposal(conn, case_id=case_id, proposal_id=proposal_id)
    conn.execute('UPDATE proposals SET state = ? WHERE id = ?', (STATE_REJECTED, proposal_id))
    append_entry(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action='proposal.rejected',
        before_refs={'state': row['state']},
        after_refs={'proposal_id': proposal_id, 'state': STATE_REJECTED},
        reason=request.reason,
    )
    return row_to_payload(
        conn, row=require_proposal(conn, case_id=case_id, proposal_id=proposal_id)
    )


def require_proposal(
    conn: sqlite3.Connection, *, case_id: str, proposal_id: str
) -> sqlite3.Row:
    row = conn.execute(
        'SELECT * FROM proposals WHERE id = ? AND case_id = ?', (proposal_id, case_id)
    ).fetchone()
    if row is None:
        raise resource_not_found()
    return row


def applied_group_ids(conn: sqlite3.Connection, *, proposal_id: str) -> list[str]:
    rows = conn.execute(
        'SELECT group_id FROM proposal_applications WHERE proposal_id = ? ORDER BY rowid ASC',
        (proposal_id,),
    ).fetchall()
    return [row['group_id'] for row in rows]


def next_state(*, group_count: int, applied_count: int) -> str:
    if applied_count >= group_count:
        return STATE_APPLIED
    return STATE_PARTIALLY_APPLIED


def row_to_payload(conn: sqlite3.Connection, *, row: sqlite3.Row) -> dict[str, Any]:
    candidate = json.loads(row['candidate_json'])
    return {
        'proposal_id': row['id'],
        'case_id': row['case_id'],
        'origin': row['origin'],
        'run_id': row['run_id'],
        'mode': row['mode'],
        'base_case_revision': row['base_case_revision'],
        'target': candidate['target'],
        'dependencies': candidate['dependencies'],
        'change_groups': candidate['change_groups'],
        'state': row['state'],
        'applied_group_ids': applied_group_ids(conn, proposal_id=row['id']),
        'created_at': row['created_at'],
    }


def _assert_document_group_is_indivisible(request: ProposalCreateRequest) -> None:
    """replace_document 不可拆組，也不能與同文件的局部操作混用。"""
    has_document_op = any(
        operation.op == 'replace_document'
        for group in request.change_groups
        for operation in group.operations
    )
    if not has_document_op:
        return

    operation_count = sum(len(group.operations) for group in request.change_groups)
    if len(request.change_groups) != 1 or operation_count != 1:
        raise invalid_field(
            'replace_document 必須是唯一的修改組與唯一的操作',
            {'field': 'change_groups'},
        )
    if request.mode != 'full':
        raise invalid_field('replace_document 只能用在 mode=full 的提案', {'field': 'mode'})


def _assert_within_scope(request: ProposalCreateRequest, operation: Any) -> None:
    target = request.target
    if operation.op == 'replace_fact':
        if target.kind != 'fact_field' or target.field_path != operation.target.field_path:
            raise out_of_scope_patch(
                '事實修改超出核准的目標欄位', {'field_path': operation.target.field_path}
            )
        return

    if target.kind == 'fact_field':
        raise out_of_scope_patch('事實目標的提案不能改草稿內容', {'op': operation.op})

    if operation.target.resource_id != target.resource_id:
        raise out_of_scope_patch(
            '操作指向其他資源', {'resource_id': operation.target.resource_id}
        )

    if target.kind == 'document':
        return

    block_id = getattr(operation.target, 'block_id', None)
    if block_id != target.block_id:
        raise out_of_scope_patch('操作指向未選取的區塊', {'block_id': block_id})
    if operation.op == 'replace_text' and not (
        target.char_start <= operation.target.char_start
        and operation.target.char_end <= target.char_end
    ):
        raise out_of_scope_patch(
            '修改範圍超出使用者選取的字元範圍',
            {'char_start': operation.target.char_start,
             'char_end': operation.target.char_end},
        )


def _assert_base_matches(
    conn: sqlite3.Connection, *, case_id: str, operation: Any
) -> None:
    resource_id = (
        FACTS_RESOURCE_ID if operation.op == 'replace_fact' else operation.target.resource_id
    )
    row = resource_service.require_version(
        conn,
        case_id=case_id,
        resource_id=resource_id,
        revision_id=operation.target.resource_revision,
    )
    content = json.loads(row['content_json'])

    if operation.op == 'replace_fact':
        actual = content.get('fields', {}).get(operation.target.field_path, {}).get('value')
        if actual != operation.before_value:
            raise out_of_scope_patch(
                '候選的原始事實值與已凍結版本不符',
                {'field_path': operation.target.field_path},
            )
        return

    if operation.op == 'replace_document':
        return

    block = _find_block(content, getattr(operation.target, 'block_id', None))
    if block is None:
        raise out_of_scope_patch(
            '指定的區塊不在已凍結版本裡', {'block_id': operation.target.block_id}
        )
    if operation.op == 'replace_text':
        actual = block['text'][operation.target.char_start:operation.target.char_end]
        if actual != operation.target.selected_text:
            raise out_of_scope_patch(
                '候選的原始文字與已凍結版本不符', {'block_id': operation.target.block_id}
            )


def _find_block(content: dict[str, Any], block_id: str | None) -> dict[str, Any] | None:
    return next(
        (item for item in content.get('blocks', []) if item['block_id'] == block_id), None
    )


def _store_evidence(
    conn: sqlite3.Connection, *, case_id: str, evidence: list[EvidenceInput]
) -> None:
    """fixture 提供的來源一律存成未查證；沒有語料儲存可比對就不冒充已查證。"""
    verification = {
        'source_exists': None,
        'quote_matches': None,
        'support_status': SUPPORT_UNKNOWN,
        'assessed_by': ASSESSED_BY_UNVERIFIED,
        'temporal_status': TEMPORAL_UNKNOWN,
        'opened_event_id': None,
    }
    for item in evidence:
        existing = conn.execute(
            'SELECT id FROM evidence_records WHERE id = ? AND case_id = ?',
            (item.evidence_id, case_id),
        ).fetchone()
        if existing is not None:
            continue
        quote_hash = (
            hashlib.sha256(item.quote.encode('utf-8')).hexdigest() if item.quote else None
        )
        conn.execute(
            'INSERT INTO evidence_records (id, case_id, run_id, source_ref_json, quote,'
            ' quote_hash, verification_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                item.evidence_id,
                case_id,
                None,
                json.dumps(item.source_ref.model_dump(), ensure_ascii=False),
                item.quote,
                quote_hash,
                json.dumps(verification, ensure_ascii=False),
                now_iso(),
            ),
        )


def _assert_evidence_exists(
    conn: sqlite3.Connection, *, case_id: str, request: ProposalCreateRequest
) -> None:
    referenced = _referenced_evidence_ids(request.change_groups)
    if not referenced:
        return
    rows = conn.execute(
        f'SELECT id FROM evidence_records WHERE case_id = ?'
        f' AND id IN ({",".join("?" * len(referenced))})',
        (case_id, *sorted(referenced)),
    ).fetchall()
    missing = sorted(referenced - {row['id'] for row in rows})
    if missing:
        raise invalid_citation('引用了不存在的來源紀錄', {'evidence_ids': missing})


def _referenced_evidence_ids(change_groups: list[ChangeGroup]) -> set[str]:
    ids: set[str] = set()
    for group in change_groups:
        ids.update(group.evidence_ids)
        for operation in group.operations:
            if operation.op in CITATION_OPS:
                ids.add(operation.evidence_id)
    return ids


def read_evidence(
    conn: sqlite3.Connection, *, case_id: str, actor_id: str, evidence_id: str
) -> dict[str, Any]:
    repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    row = conn.execute(
        'SELECT * FROM evidence_records WHERE id = ? AND case_id = ?', (evidence_id, case_id)
    ).fetchone()
    if row is None:
        raise resource_not_found()
    return {
        'evidence_id': row['id'],
        'source_ref': json.loads(row['source_ref_json']),
        'quote': row['quote'],
        **json.loads(row['verification_json']),
    }
