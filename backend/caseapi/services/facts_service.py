"""人工修改事實。

設計 03 §5：一個交易內保存新事實版本、推進 case revision、追加稽核、
標記依賴失效。A2 還沒有分析引擎，所以依「依賴不足以精確判別時保守標記」，
任何事實變動都把草稿標 stale，不假裝只有某幾段受影響。
"""

import json
import sqlite3
from typing import Any

from caseapi.audit import append_entry
from caseapi.clock import now_iso
from caseapi.ids import new_id
from caseapi.schemas.facts import FactsPatchRequest
from caseapi.services import case_repository as repo
from caseapi.services import resource_service

FACTS_RESOURCE_ID = 'facts'


def read_current_fields(
    conn: sqlite3.Connection, *, case_id: str, heads: dict[str, dict[str, str]]
) -> dict[str, Any]:
    head = heads.get(FACTS_RESOURCE_ID)
    if head is None:
        return {}
    row = resource_service.require_version(
        conn, case_id=case_id, resource_id=FACTS_RESOURCE_ID, revision_id=head['revision_id']
    )
    return json.loads(row['content_json']).get('fields', {})


def get_facts(conn: sqlite3.Connection, *, case_id: str, actor_id: str) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    heads = repo.load_heads(case_row)
    return {
        'case_id': case_id,
        'case_revision': case_row['case_revision'],
        'fields': read_current_fields(conn, case_id=case_id, heads=heads),
    }


def patch_facts(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    request: FactsPatchRequest,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    repo.assert_case_revision(case_row, request.expected_case_revision)

    heads = repo.load_heads(case_row)
    parent_head = heads.get(FACTS_RESOURCE_ID)
    fields = _apply_changes(
        read_current_fields(conn, case_id=case_id, heads=heads),
        request=request,
        actor_id=actor_id,
    )

    version = resource_service.save_version(
        conn,
        case_id=case_id,
        resource_id=FACTS_RESOURCE_ID,
        resource_kind=repo.KIND_FACTS,
        content={'fields': fields},
        parent_id=parent_head['revision_id'] if parent_head else None,
        origin=resource_service.ORIGIN_HUMAN,
        actor_id=actor_id,
    )

    stale_resources = repo.resource_ids_of_kind(heads, repo.KIND_DRAFT)
    next_heads = repo.mark_stale(
        repo.set_head(
            heads,
            resource_id=FACTS_RESOURCE_ID,
            kind=repo.KIND_FACTS,
            revision_id=version['resource_revision'],
            freshness=repo.FRESHNESS_CURRENT,
        ),
        stale_resources,
    )

    mutation_id = new_id('mut')
    case_revision = repo.advance_case(
        conn,
        case_id=case_id,
        expected_revision=request.expected_case_revision,
        heads=next_heads,
        actor_id=actor_id,
        mutation_id=mutation_id,
    )
    changed_paths = [change.field_path for change in request.field_changes]
    append_entry(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action='facts.updated',
        mutation_id=mutation_id,
        before_refs={'facts_revision': parent_head['revision_id'] if parent_head else None},
        after_refs={
            'facts_revision': version['resource_revision'],
            'changed_field_paths': changed_paths,
            'stale_resources': stale_resources,
        },
        reason=request.reason,
    )

    return {
        'resource_id': FACTS_RESOURCE_ID,
        'resource_revision': version['resource_revision'],
        'parent_revision': version['parent_revision'],
        'case_revision': case_revision,
        'stale_resources': stale_resources,
        'fields': fields,
    }


def _apply_changes(
    current_fields: dict[str, Any], *, request: FactsPatchRequest, actor_id: str
) -> dict[str, Any]:
    """回傳新的欄位字典；原本的內容不被就地修改。"""
    timestamp = now_iso()
    updates: dict[str, Any] = {}
    for change in request.field_changes:
        previous = current_fields.get(change.field_path) or {}
        updated = {
            'value': change.value,
            'origin': resource_service.ORIGIN_HUMAN,
            'human_asserted': change.human_asserted,
            'reason': change.reason,
            'source': change.source,
            'updated_by': actor_id,
            'updated_at': timestamp,
        }
        # Editing wording is not a legal-review action.  Preserve the explicit
        # review state until a separate, auditable review workflow changes it.
        if 'legal_review_status' in previous:
            updated['legal_review_status'] = previous['legal_review_status']
        updates[change.field_path] = updated
    return {**current_fields, **updates}
