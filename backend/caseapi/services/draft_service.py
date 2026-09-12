"""草稿建立、區塊編輯與人工覆核。

設計 03 §4：人工文字編輯不自動解除既有 stale；只有留下理由的覆核才可以。
"""

import json
import sqlite3
from typing import Any

from caseapi.audit import append_entry
from caseapi.errors import resource_not_found, revision_conflict, target_moved
from caseapi.ids import new_id
from caseapi.schemas.draft import DraftCreateRequest, DraftPatchRequest, DraftReviewRequest
from caseapi.services import case_repository as repo
from caseapi.services import resource_service
from caseapi.services.facts_service import FACTS_RESOURCE_ID


def create_draft(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    request: DraftCreateRequest,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    repo.assert_case_revision(case_row, request.expected_case_revision)
    heads = repo.load_heads(case_row)

    draft_id = new_id('draft')
    content = {
        'draft_kind': request.draft_kind,
        'title': request.title,
        'blocks': [block.model_dump() for block in request.blocks],
    }
    version = resource_service.save_version(
        conn,
        case_id=case_id,
        resource_id=draft_id,
        resource_kind=repo.KIND_DRAFT,
        content=content,
        parent_id=None,
        origin=resource_service.ORIGIN_HUMAN,
        actor_id=actor_id,
        dependencies=_dependency_snapshot(heads),
    )
    return _commit_draft_state(
        conn,
        case_row=case_row,
        actor_id=actor_id,
        heads=heads,
        draft_id=draft_id,
        version=version,
        freshness=repo.FRESHNESS_CURRENT,
        action='draft.created',
        reason=None,
        expected_revision=request.expected_case_revision,
    )


def patch_draft(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    draft_id: str,
    request: DraftPatchRequest,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    repo.assert_case_revision(case_row, request.expected_case_revision)
    heads = repo.load_heads(case_row)
    head = _require_draft_head(heads, draft_id)
    _assert_base_revision(head, request.base_resource_revision)

    row = resource_service.require_version(
        conn, case_id=case_id, resource_id=draft_id, revision_id=head['revision_id']
    )
    content = json.loads(row['content_json'])
    next_content = {**content, 'blocks': _apply_block_changes(content['blocks'], request)}

    version = resource_service.save_version(
        conn,
        case_id=case_id,
        resource_id=draft_id,
        resource_kind=repo.KIND_DRAFT,
        content=next_content,
        parent_id=head['revision_id'],
        origin=resource_service.ORIGIN_HUMAN,
        actor_id=actor_id,
        dependencies=json.loads(row['dependencies_json']),
    )
    return _commit_draft_state(
        conn,
        case_row=case_row,
        actor_id=actor_id,
        heads=heads,
        draft_id=draft_id,
        version=version,
        freshness=head['freshness'],
        action='draft.updated',
        reason=None,
        expected_revision=request.expected_case_revision,
    )


def review_draft(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    draft_id: str,
    request: DraftReviewRequest,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    repo.assert_case_revision(case_row, request.expected_case_revision)
    heads = repo.load_heads(case_row)
    head = _require_draft_head(heads, draft_id)
    _assert_base_revision(head, request.base_resource_revision)

    row = resource_service.require_version(
        conn, case_id=case_id, resource_id=draft_id, revision_id=head['revision_id']
    )
    version = resource_service.save_version(
        conn,
        case_id=case_id,
        resource_id=draft_id,
        resource_kind=repo.KIND_DRAFT,
        content=json.loads(row['content_json']),
        parent_id=head['revision_id'],
        origin=resource_service.ORIGIN_HUMAN,
        actor_id=actor_id,
        dependencies=_dependency_snapshot(heads),
    )
    return _commit_draft_state(
        conn,
        case_row=case_row,
        actor_id=actor_id,
        heads=heads,
        draft_id=draft_id,
        version=version,
        freshness=repo.FRESHNESS_CURRENT,
        action='draft.reviewed',
        reason=request.reason,
        expected_revision=request.expected_case_revision,
    )


def _commit_draft_state(
    conn: sqlite3.Connection,
    *,
    case_row: sqlite3.Row,
    actor_id: str,
    heads: dict[str, dict[str, str]],
    draft_id: str,
    version: dict[str, Any],
    freshness: str,
    action: str,
    reason: str | None,
    expected_revision: int,
) -> dict[str, Any]:
    next_heads = repo.set_head(
        heads,
        resource_id=draft_id,
        kind=repo.KIND_DRAFT,
        revision_id=version['resource_revision'],
        freshness=freshness,
    )
    mutation_id = new_id('mut')
    case_revision = repo.advance_case(
        conn,
        case_id=case_row['id'],
        expected_revision=expected_revision,
        heads=next_heads,
        actor_id=actor_id,
        mutation_id=mutation_id,
    )
    append_entry(
        conn,
        case_id=case_row['id'],
        actor_id=actor_id,
        action=action,
        mutation_id=mutation_id,
        before_refs={'draft_revision': version['parent_revision']},
        after_refs={'draft_revision': version['resource_revision'], 'freshness': freshness},
        reason=reason,
    )
    return {
        'draft_id': draft_id,
        'resource_revision': version['resource_revision'],
        'parent_revision': version['parent_revision'],
        'case_revision': case_revision,
        'freshness': freshness,
        'blocks': version['content']['blocks'],
    }


def _require_draft_head(heads: dict[str, dict[str, str]], draft_id: str) -> dict[str, str]:
    head = heads.get(draft_id)
    if head is None or head.get('kind') != repo.KIND_DRAFT:
        raise resource_not_found()
    return head


def _assert_base_revision(head: dict[str, str], base_resource_revision: str) -> None:
    if head['revision_id'] != base_resource_revision:
        raise revision_conflict(
            '草稿已有更新的版本，請重新取得後再編輯',
            {'current_resource_revision': head['revision_id'],
             'base_resource_revision': base_resource_revision},
        )


def _apply_block_changes(
    blocks: list[dict[str, Any]], request: DraftPatchRequest
) -> list[dict[str, Any]]:
    """只改指定的 block_id；找不到就回 TARGET_MOVED，不用字串搜尋猜位置。"""
    replacements = {change.block_id: change.text for change in request.block_changes}
    known_ids = {block['block_id'] for block in blocks}
    missing = sorted(replacements.keys() - known_ids)
    if missing:
        raise target_moved('指定的區塊不在這個版本裡', {'missing_block_ids': missing})
    return [
        {**block, 'text': replacements[block['block_id']]}
        if block['block_id'] in replacements
        else block
        for block in blocks
    ]


def _dependency_snapshot(heads: dict[str, dict[str, str]]) -> dict[str, Any]:
    facts_head = heads.get(FACTS_RESOURCE_ID)
    return {'facts_revision': facts_head['revision_id'] if facts_head else None}
