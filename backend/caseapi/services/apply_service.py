"""正式採用。

設計 03 §7：合併與昂貴驗證都在交易外完成（預覽階段），交易內只做版本、
hash、權限複核與寫入。任何一步失敗全部 rollback。
"""

import json
import sqlite3
from typing import Any

from caseapi.audit import append_entry
from caseapi.clock import now_iso
from caseapi.errors import (
    ApiError,
    invalid_citation,
    invalid_field,
    proposal_already_applied,
    revision_conflict,
)
from caseapi.ids import new_id
from caseapi.schemas.proposal import STATE_APPLIED, STATE_REJECTED, ApplicationRequest
from caseapi.services import case_repository as repo
from caseapi.services import merge_service, proposal_service, resource_service
from caseapi.services.facts_service import FACTS_RESOURCE_ID


def apply_proposal(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    proposal_id: str,
    request: ApplicationRequest,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    repo.assert_case_revision(case_row, request.expected_case_revision)

    proposal_row = proposal_service.require_proposal(
        conn, case_id=case_id, proposal_id=proposal_id
    )
    if proposal_row['state'] == STATE_REJECTED:
        raise invalid_field('提案已被拒絕，不能再採用', {'proposal_id': proposal_id})

    preview_row = merge_service.require_preview(
        conn, case_id=case_id, proposal_id=proposal_id, preview_id=request.preview_id
    )
    _assert_preview_is_usable(preview_row, request)

    accepted = list(request.accepted_group_ids)
    already = sorted(
        set(accepted) & set(proposal_service.applied_group_ids(conn, proposal_id=proposal_id))
    )
    if already:
        raise proposal_already_applied({'group_ids': already})

    conflict = json.loads(preview_row['conflict_json'])
    candidate = json.loads(proposal_row['candidate_json'])
    _assert_dependencies_complete(conflict, candidate)
    _assert_no_conflicts(conflict)

    resolved = json.loads(preview_row['resolved_candidate_json'])
    return _commit(
        conn,
        case_row=case_row,
        actor_id=actor_id,
        proposal_row=proposal_row,
        candidate=candidate,
        accepted=accepted,
        resolved=resolved,
        unverified=conflict.get('unverified_evidence_ids', []),
        expected_revision=request.expected_case_revision,
    )


def _assert_preview_is_usable(
    preview_row: sqlite3.Row, request: ApplicationRequest
) -> None:
    if preview_row['current_case_revision'] != request.expected_case_revision:
        raise revision_conflict(
            '預覽是依其他案件版本建立的，請重新產生預覽',
            {'preview_case_revision': preview_row['current_case_revision'],
             'expected_case_revision': request.expected_case_revision},
        )
    if preview_row['preview_hash'] != request.preview_hash:
        raise revision_conflict(
            'preview_hash 與伺服器保存的預覽不符', {'preview_id': preview_row['id']}
        )
    selected = json.loads(preview_row['selected_groups_json'])
    if sorted(selected) != sorted(request.accepted_group_ids):
        raise invalid_field(
            '採用的修改組必須與預覽完全一致，不能臨時增刪',
            {'preview_group_ids': selected, 'accepted_group_ids': request.accepted_group_ids},
        )


def _assert_dependencies_complete(
    conflict: dict[str, Any], candidate: dict[str, Any]
) -> None:
    """組間依賴沒有補齊就不能採用，不允許留下斷裂內容。"""
    missing = conflict.get('missing_group_dependencies', [])
    if not missing:
        return
    required = sorted({group_id for item in missing for group_id in item['requires']})
    classes = {
        group['id']: group['change_class'] for group in candidate['change_groups']
    }
    details = {'missing_group_ids': required}
    if any(classes.get(group_id) == 'citation' for group_id in required):
        raise invalid_citation('必要的引用修改組沒有一起採用', details)
    raise invalid_field('修改組的依賴沒有一起採用', details)


def _assert_no_conflicts(conflict: dict[str, Any]) -> None:
    conflicts = conflict.get('conflicts', [])
    if not conflicts:
        return
    first = conflicts[0]
    raise ApiError(
        first['code'],
        409,
        first['message'],
        {'group_id': first['group_id'], 'resource_id': first['resource_id'],
         'block_id': first['block_id']},
    )


def _commit(
    conn: sqlite3.Connection,
    *,
    case_row: sqlite3.Row,
    actor_id: str,
    proposal_row: sqlite3.Row,
    candidate: dict[str, Any],
    accepted: list[str],
    resolved: dict[str, Any],
    unverified: list[str],
    expected_revision: int,
) -> dict[str, Any]:
    case_id = case_row['id']
    heads = repo.load_heads(case_row)
    mutation_id = new_id('mut')

    written: dict[str, str] = {}
    next_heads = heads
    for resource_id, content in resolved.items():
        head = heads.get(resource_id)
        kind = (head or {}).get(
            'kind', repo.KIND_FACTS if resource_id == FACTS_RESOURCE_ID else repo.KIND_DRAFT
        )
        version = resource_service.save_version(
            conn,
            case_id=case_id,
            resource_id=resource_id,
            resource_kind=kind,
            content=content,
            parent_id=(head or {}).get('revision_id'),
            origin=resource_service.ORIGIN_MERGED,
            actor_id=actor_id,
            dependencies=candidate['dependencies'],
        )
        written[resource_id] = version['resource_revision']
        next_heads = repo.set_head(
            next_heads,
            resource_id=resource_id,
            kind=kind,
            revision_id=version['resource_revision'],
            freshness=repo.FRESHNESS_CURRENT,
        )

    invalidated: list[str] = []
    if FACTS_RESOURCE_ID in resolved:
        invalidated = repo.resource_ids_of_kind(next_heads, repo.KIND_DRAFT)
        next_heads = repo.mark_stale(next_heads, invalidated)

    case_revision = repo.advance_case(
        conn,
        case_id=case_id,
        expected_revision=expected_revision,
        heads=next_heads,
        actor_id=actor_id,
        mutation_id=mutation_id,
    )
    _record_applications(
        conn,
        proposal_id=proposal_row['id'],
        accepted=accepted,
        mutation_id=mutation_id,
        case_revision=case_revision,
    )
    state = proposal_service.next_state(
        group_count=len(candidate['change_groups']),
        applied_count=len(
            proposal_service.applied_group_ids(conn, proposal_id=proposal_row['id'])
        ),
    )
    conn.execute('UPDATE proposals SET state = ? WHERE id = ?', (state, proposal_row['id']))

    reasons = [
        group['reason'] for group in candidate['change_groups'] if group['id'] in set(accepted)
    ]
    append_entry(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action='proposal.applied',
        mutation_id=mutation_id,
        before_refs={resource_id: (heads.get(resource_id) or {}).get('revision_id')
                     for resource_id in resolved},
        after_refs={
            'proposal_id': proposal_row['id'],
            'applied_group_ids': accepted,
            'resource_revisions': written,
            'invalidated_resources': invalidated,
            'unverified_evidence_ids': unverified,
        },
        reason='；'.join(reasons) or None,
        evidence_refs=unverified or None,
    )
    return {
        'mutation_id': mutation_id,
        'applied_group_ids': accepted,
        'case_revision': case_revision,
        'resulting_case_revision': case_revision,
        'resource_revisions': written,
        'invalidated_resources': invalidated,
        'analysis_job_ids': [],
        'unverified_evidence_ids': unverified,
        'proposal_state': state,
    }


def _record_applications(
    conn: sqlite3.Connection,
    *,
    proposal_id: str,
    accepted: list[str],
    mutation_id: str,
    case_revision: int,
) -> None:
    created_at = now_iso()
    for group_id in accepted:
        conn.execute(
            'INSERT INTO proposal_applications (proposal_id, group_id, mutation_id,'
            ' resulting_revision, created_at) VALUES (?, ?, ?, ?, ?)',
            (proposal_id, group_id, mutation_id, case_revision, created_at),
        )
