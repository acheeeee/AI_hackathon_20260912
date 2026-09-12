"""三方合併預覽。

設計 03 §6：base 是提案開始時的版本，current 是現在的正式版本，candidate 是
提案內容。diff 只是展示，merge 產生候選結果，apply 才是正式保存。同一區塊
被人改過時 v1 保守視為衝突，不做字元級自動合併。
"""

import hashlib
import json
import sqlite3
from typing import Any

from caseapi.clock import now_iso
from caseapi.errors import invalid_field, resource_not_found
from caseapi.ids import new_id
from caseapi.schemas.proposal import MergePreviewRequest, ResolutionRequest
from caseapi.services import case_repository as repo
from caseapi.services import proposal_service, resource_service
from caseapi.services.facts_service import FACTS_RESOURCE_ID

CONFLICT_SAME_BLOCK = 'SAME_BLOCK_CHANGED'
CONFLICT_SAME_FACT = 'SAME_FACT_CHANGED'
CONFLICT_SAME_DOCUMENT = 'SAME_DOCUMENT_CHANGED'
CONFLICT_TARGET_MOVED = 'TARGET_MOVED'
CONFLICT_DEPENDENCY_STALE = 'DEPENDENCY_STALE'

# 設計 03 §6.1 規則 6：純 wording 且宣告依賴未變，可在新 current 上預覽。
_DEPENDENCY_EXEMPT_CLASSES = frozenset({'wording'})


def build_preview(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    proposal_id: str,
    request: MergePreviewRequest,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    repo.assert_case_revision(case_row, request.expected_case_revision)
    proposal_row = proposal_service.require_proposal(
        conn, case_id=case_id, proposal_id=proposal_id
    )
    candidate = json.loads(proposal_row['candidate_json'])
    groups = _select_groups(candidate, request.selected_group_ids)

    merger = _Merger(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        heads=repo.load_heads(case_row),
        candidate=candidate,
    )
    merged = merger.run(groups)
    applied = set(proposal_service.applied_group_ids(conn, proposal_id=proposal_id))
    missing = _missing_group_dependencies(groups, request.selected_group_ids, applied)

    return _store_preview(
        conn,
        case_id=case_id,
        proposal_id=proposal_id,
        parent_preview_id=None,
        current_case_revision=case_row['case_revision'],
        selected_group_ids=request.selected_group_ids,
        merged=merged,
        missing=missing,
        unverified=_unverified_evidence_ids(conn, case_id=case_id, groups=groups),
    )


def resolve_preview(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    proposal_id: str,
    preview_id: str,
    request: ResolutionRequest,
) -> dict[str, Any]:
    """人工整合衝突後建立新的不可變預覽；舊的預覽不變。"""
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    repo.assert_case_revision(case_row, request.expected_case_revision)
    parent = require_preview(
        conn, case_id=case_id, proposal_id=proposal_id, preview_id=preview_id
    )
    proposal_row = proposal_service.require_proposal(
        conn, case_id=case_id, proposal_id=proposal_id
    )
    candidate = json.loads(proposal_row['candidate_json'])
    selected = json.loads(parent['selected_groups_json'])
    groups = _select_groups(candidate, selected)

    merger = _Merger(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        heads=repo.load_heads(case_row),
        candidate=candidate,
    )
    merged = _apply_resolutions(merger.run(groups), request)
    applied = set(proposal_service.applied_group_ids(conn, proposal_id=proposal_id))

    return _store_preview(
        conn,
        case_id=case_id,
        proposal_id=proposal_id,
        parent_preview_id=preview_id,
        current_case_revision=case_row['case_revision'],
        selected_group_ids=selected,
        merged=merged,
        missing=_missing_group_dependencies(groups, selected, applied),
        unverified=_unverified_evidence_ids(conn, case_id=case_id, groups=groups),
    )


def require_preview(
    conn: sqlite3.Connection, *, case_id: str, proposal_id: str, preview_id: str
) -> sqlite3.Row:
    row = conn.execute(
        'SELECT * FROM merge_previews WHERE id = ? AND proposal_id = ? AND case_id = ?',
        (preview_id, proposal_id, case_id),
    ).fetchone()
    if row is None:
        raise resource_not_found()
    return row


def preview_payload(row: sqlite3.Row) -> dict[str, Any]:
    conflict = json.loads(row['conflict_json'])
    return {
        'preview_id': row['id'],
        'proposal_id': row['proposal_id'],
        'parent_preview_id': row['parent_preview_id'],
        'current_case_revision': row['current_case_revision'],
        'selected_group_ids': json.loads(row['selected_groups_json']),
        'preview_hash': row['preview_hash'],
        'created_at': row['created_at'],
        **conflict,
    }


def _store_preview(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    proposal_id: str,
    parent_preview_id: str | None,
    current_case_revision: int,
    selected_group_ids: list[str],
    merged: dict[str, Any],
    missing: list[dict[str, Any]],
    unverified: list[str],
) -> dict[str, Any]:
    conflict = {
        'conflicts': merged['conflicts'],
        'missing_group_dependencies': missing,
        'unverified_evidence_ids': unverified,
        'diffs': merged['diffs'],
        'can_apply': not merged['conflicts'] and not missing,
    }
    preview_hash = _preview_hash(
        proposal_id=proposal_id,
        current_case_revision=current_case_revision,
        selected_group_ids=selected_group_ids,
        resolved=merged['resolved'],
        conflict=conflict,
    )
    preview_id = new_id('preview')
    conn.execute(
        'INSERT INTO merge_previews (id, proposal_id, case_id, parent_preview_id,'
        ' current_case_revision, selected_groups_json, resolved_candidate_json, preview_hash,'
        ' conflict_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            preview_id,
            proposal_id,
            case_id,
            parent_preview_id,
            current_case_revision,
            json.dumps(selected_group_ids, ensure_ascii=False),
            json.dumps(merged['resolved'], ensure_ascii=False),
            preview_hash,
            json.dumps(conflict, ensure_ascii=False),
            now_iso(),
        ),
    )
    return preview_payload(
        require_preview(
            conn, case_id=case_id, proposal_id=proposal_id, preview_id=preview_id
        )
    )


def _preview_hash(
    *,
    proposal_id: str,
    current_case_revision: int,
    selected_group_ids: list[str],
    resolved: dict[str, Any],
    conflict: dict[str, Any],
) -> str:
    payload = {
        'proposal_id': proposal_id,
        'current_case_revision': current_case_revision,
        'selected_group_ids': selected_group_ids,
        'resolved': resolved,
        'conflict': conflict,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _select_groups(candidate: dict[str, Any], selected_ids: list[str]) -> list[dict[str, Any]]:
    by_id = {group['id']: group for group in candidate['change_groups']}
    unknown = sorted(set(selected_ids) - by_id.keys())
    if unknown:
        raise invalid_field('提案沒有這些修改組', {'group_ids': unknown})
    return [by_id[group_id] for group_id in selected_ids]


def _missing_group_dependencies(
    groups: list[dict[str, Any]], selected_ids: list[str], applied: set[str]
) -> list[dict[str, Any]]:
    available = set(selected_ids) | applied
    missing = [
        {
            'group_id': group['id'],
            'requires': sorted(set(group['depends_on_group_ids']) - available),
        }
        for group in groups
        if set(group['depends_on_group_ids']) - available
    ]
    return missing


def _unverified_evidence_ids(
    conn: sqlite3.Connection, *, case_id: str, groups: list[dict[str, Any]]
) -> list[str]:
    referenced: set[str] = set()
    for group in groups:
        referenced.update(group.get('evidence_ids', []))
        for operation in group['operations']:
            if operation['op'] in ('add_citation', 'remove_citation'):
                referenced.add(operation['evidence_id'])
    if not referenced:
        return []

    rows = conn.execute(
        f'SELECT id, verification_json FROM evidence_records WHERE case_id = ?'
        f' AND id IN ({",".join("?" * len(referenced))})',
        (case_id, *sorted(referenced)),
    ).fetchall()
    return sorted(
        row['id']
        for row in rows
        if json.loads(row['verification_json'])['assessed_by'] == 'unverified'
    )


def _apply_resolutions(merged: dict[str, Any], request: ResolutionRequest) -> dict[str, Any]:
    """把人工整合後的文字寫進候選，並移除對應的衝突。"""
    resolved = json.loads(json.dumps(merged['resolved']))
    diffs = [dict(diff) for diff in merged['diffs']]
    settled = {(item.resource_id, item.block_id) for item in request.resolutions}

    for item in request.resolutions:
        content = resolved.get(item.resource_id)
        if content is None:
            raise invalid_field(
                '整合的資源不在這個預覽裡', {'resource_id': item.resource_id}
            )
        block = next(
            (entry for entry in content.get('blocks', []) if entry['block_id'] == item.block_id),
            None,
        )
        if block is None:
            raise invalid_field('整合的區塊不在這個預覽裡', {'block_id': item.block_id})
        block['text'] = item.text
        for diff in diffs:
            if (diff['resource_id'], diff['block_id']) == (item.resource_id, item.block_id):
                diff['candidate'] = item.text

    conflicts = [
        conflict
        for conflict in merged['conflicts']
        if (conflict.get('resource_id'), conflict.get('block_id')) not in settled
    ]
    return {'resolved': resolved, 'diffs': diffs, 'conflicts': conflicts}


class _Merger:
    """把選定修改組套到目前內容上，並記錄三方差異與衝突。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        case_id: str,
        actor_id: str,
        heads: dict[str, dict[str, str]],
        candidate: dict[str, Any],
    ) -> None:
        self._conn = conn
        self._case_id = case_id
        self._actor_id = actor_id
        self._heads = heads
        self._candidate = candidate
        self._current: dict[str, dict[str, Any]] = {}
        self.working: dict[str, dict[str, Any]] = {}
        self.diffs: list[dict[str, Any]] = []
        self.conflicts: list[dict[str, Any]] = []

    def run(self, groups: list[dict[str, Any]]) -> dict[str, Any]:
        self._check_dependencies(groups)
        handlers = {
            'replace_text': self._replace_text,
            'replace_fact': self._replace_fact,
            'add_citation': self._add_citation,
            'remove_citation': self._remove_citation,
            'replace_document': self._replace_document,
        }
        for group in groups:
            for operation in group['operations']:
                handlers[operation['op']](group, operation)
        return {'resolved': self.working, 'diffs': self.diffs, 'conflicts': self.conflicts}

    def _check_dependencies(self, groups: list[dict[str, Any]]) -> None:
        declared = self._candidate['dependencies'].get('facts_revision')
        if declared is None:
            return
        current = self._heads.get(FACTS_RESOURCE_ID, {}).get('revision_id')
        if declared == current:
            return
        for group in groups:
            if group['change_class'] in _DEPENDENCY_EXEMPT_CLASSES:
                continue
            self._add_conflict(
                group,
                code=CONFLICT_DEPENDENCY_STALE,
                resource_id=FACTS_RESOURCE_ID,
                block_id=None,
                message='提案依據的事實版本已變動，需要重新產生候選或人工重新確認',
            )

    def _current_content(self, resource_id: str) -> dict[str, Any]:
        if resource_id in self._current:
            return self._current[resource_id]
        head = self._heads.get(resource_id)
        if head is None:
            content: dict[str, Any] = {'fields': {}} if resource_id == FACTS_RESOURCE_ID else {}
        else:
            row = resource_service.require_version(
                self._conn,
                case_id=self._case_id,
                resource_id=resource_id,
                revision_id=head['revision_id'],
            )
            content = json.loads(row['content_json'])
        self._current[resource_id] = content
        return content

    def _working_content(self, resource_id: str) -> dict[str, Any]:
        if resource_id not in self.working:
            self.working[resource_id] = json.loads(
                json.dumps(self._current_content(resource_id))
            )
        return self.working[resource_id]

    def _base_content(self, resource_id: str, revision_id: str) -> dict[str, Any]:
        row = resource_service.require_version(
            self._conn, case_id=self._case_id, resource_id=resource_id, revision_id=revision_id
        )
        return json.loads(row['content_json'])

    def _replace_text(self, group: dict[str, Any], operation: dict[str, Any]) -> None:
        target = operation['target']
        resource_id = target['resource_id']
        base_block = _find_block(
            self._base_content(resource_id, target['resource_revision']), target['block_id']
        )
        current_block = _find_block(self._current_content(resource_id), target['block_id'])
        if base_block is None or current_block is None:
            self._add_conflict(group, code=CONFLICT_TARGET_MOVED, resource_id=resource_id,
                               block_id=target['block_id'],
                               message='目標區塊已不存在於這個版本')
            return

        candidate_text = (
            base_block['text'][: target['char_start']]
            + operation['after_value']
            + base_block['text'][target['char_end']:]
        )
        working = self._working_content(resource_id)
        if current_block['text'] != base_block['text']:
            self._add_conflict(group, code=CONFLICT_SAME_BLOCK, resource_id=resource_id,
                               block_id=target['block_id'],
                               message='同一區塊已被其他修改變更，需要人工整合')
        else:
            _set_block_text(working, target['block_id'], candidate_text)

        self._add_diff(resource_id, block_id=target['block_id'], field_path=None,
                       base=base_block['text'], current=current_block['text'],
                       candidate=candidate_text)

    def _replace_fact(self, group: dict[str, Any], operation: dict[str, Any]) -> None:
        target = operation['target']
        field_path = target['field_path']
        base_value = _field_value(
            self._base_content(FACTS_RESOURCE_ID, target['resource_revision']), field_path
        )
        current_value = _field_value(self._current_content(FACTS_RESOURCE_ID), field_path)
        content = self._working_content(FACTS_RESOURCE_ID)

        if current_value != base_value:
            self._add_conflict(group, code=CONFLICT_SAME_FACT, resource_id=FACTS_RESOURCE_ID,
                               block_id=None, message='同一個事實欄位已被其他修改變更')
        else:
            content.setdefault('fields', {})[field_path] = {
                'value': operation['after_value'],
                'origin': 'ai',
                'human_asserted': False,
                'reason': group['reason'],
                'source': None,
                'updated_by': self._actor_id,
                'updated_at': now_iso(),
            }

        self._add_diff(FACTS_RESOURCE_ID, block_id=None, field_path=field_path,
                       base=base_value, current=current_value,
                       candidate=operation['after_value'])

    def _add_citation(self, group: dict[str, Any], operation: dict[str, Any]) -> None:
        self._change_citation(group, operation, add=True)

    def _remove_citation(self, group: dict[str, Any], operation: dict[str, Any]) -> None:
        self._change_citation(group, operation, add=False)

    def _change_citation(
        self, group: dict[str, Any], operation: dict[str, Any], *, add: bool
    ) -> None:
        target = operation['target']
        resource_id = target['resource_id']
        base_block = _find_block(
            self._base_content(resource_id, target['resource_revision']), target['block_id']
        )
        current_block = _find_block(self._current_content(resource_id), target['block_id'])
        if base_block is None or current_block is None:
            self._add_conflict(group, code=CONFLICT_TARGET_MOVED, resource_id=resource_id,
                               block_id=target['block_id'],
                               message='目標區塊已不存在於這個版本')
            return

        base_citations = list(base_block.get('citations', []))
        current_citations = list(current_block.get('citations', []))
        candidate_citations = (
            [*base_citations, operation['evidence_id']]
            if add and operation['evidence_id'] not in base_citations
            else [item for item in base_citations if item != operation['evidence_id']]
            if not add
            else base_citations
        )

        working = self._working_content(resource_id)
        if current_citations != base_citations:
            self._add_conflict(group, code=CONFLICT_SAME_BLOCK, resource_id=resource_id,
                               block_id=target['block_id'],
                               message='同一區塊的引用已被其他修改變更')
        else:
            block = _find_block(working, target['block_id'])
            if block is not None:
                block['citations'] = candidate_citations

        self._add_diff(resource_id, block_id=target['block_id'], field_path=None,
                       base=base_citations, current=current_citations,
                       candidate=candidate_citations)

    def _replace_document(self, group: dict[str, Any], operation: dict[str, Any]) -> None:
        resource_id = operation['target']['resource_id']
        base_content = self._base_content(resource_id, operation['target']['resource_revision'])
        current_content = self._current_content(resource_id)
        after_blocks = operation['after_blocks']

        self._working_content(resource_id)
        if resource_service.content_hash(base_content) != resource_service.content_hash(
            current_content
        ):
            self._add_conflict(group, code=CONFLICT_SAME_DOCUMENT, resource_id=resource_id,
                               block_id=None,
                               message='文件已被其他修改變更，完整候選需要重新產生')
        else:
            self.working[resource_id] = {**base_content, 'blocks': after_blocks}

        for block_id in _block_id_order(base_content, current_content, after_blocks):
            self._add_diff(
                resource_id,
                block_id=block_id,
                field_path=None,
                base=_block_text(base_content.get('blocks', []), block_id),
                current=_block_text(current_content.get('blocks', []), block_id),
                candidate=_block_text(after_blocks, block_id),
            )

    def _add_conflict(
        self,
        group: dict[str, Any],
        *,
        code: str,
        resource_id: str,
        block_id: str | None,
        message: str,
    ) -> None:
        self.conflicts.append(
            {
                'group_id': group['id'],
                'code': code,
                'resource_id': resource_id,
                'block_id': block_id,
                'message': message,
            }
        )

    def _add_diff(
        self,
        resource_id: str,
        *,
        block_id: str | None,
        field_path: str | None,
        base: Any,
        current: Any,
        candidate: Any,
    ) -> None:
        self.diffs.append(
            {
                'resource_id': resource_id,
                'block_id': block_id,
                'field_path': field_path,
                'base': base,
                'current': current,
                'candidate': candidate,
            }
        )


def _find_block(content: dict[str, Any], block_id: str | None) -> dict[str, Any] | None:
    return next(
        (item for item in content.get('blocks', []) if item['block_id'] == block_id), None
    )


def _set_block_text(content: dict[str, Any], block_id: str, text: str) -> None:
    block = _find_block(content, block_id)
    if block is not None:
        block['text'] = text


def _field_value(content: dict[str, Any], field_path: str) -> Any:
    return content.get('fields', {}).get(field_path, {}).get('value')


def _block_text(blocks: list[dict[str, Any]], block_id: str) -> str | None:
    block = next((item for item in blocks if item['block_id'] == block_id), None)
    return None if block is None else block['text']


def _block_id_order(
    base_content: dict[str, Any], current_content: dict[str, Any], after_blocks: list[dict]
) -> list[str]:
    order: list[str] = []
    for blocks in (
        base_content.get('blocks', []),
        current_content.get('blocks', []),
        after_blocks,
    ):
        for block in blocks:
            if block['block_id'] not in order:
                order.append(block['block_id'])
    return order
