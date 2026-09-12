"""草稿生成：開一個 regenerate run，結果走 proposal_service 變成正式提案。

兩件事刻意分開：
1. `start_generation` 在路由的單一交易裡凍結這次生成的基底——要改哪份草稿
   （沒有就先建一個空殼，讓 `replace_document` 有 target 可指），以及事實／
   選法規／訴願書的版本 refs。之後 run 讀到的 context 只認這些 refs。
2. `save_generated_proposal` 在背景工作結束時把模型產出的區塊寫成提案。
   走的是既有的 `proposal_service.create_proposal`，所以範圍驗證、evidence
   必須存在、稽核紀錄全部沿用同一條路徑；生成不直接改正文，正文只會在
   人工採用（merge preview → application）之後才變。
"""

import sqlite3
from typing import Any

from caseapi.audit import append_entry
from caseapi.ai.contracts import ModelResult
from caseapi.ids import new_id
from caseapi.schemas.draft import DraftBlock
from caseapi.schemas.draft_generation import DraftGenerationCreateRequest
from caseapi.schemas.proposal import (
    ChangeGroup,
    ProposalCreateRequest,
    ProposalDependencies,
    ReplaceDocumentOperation,
)
from caseapi.schemas.target import DocumentTarget
from caseapi.services import case_repository as repo
from caseapi.services import proposal_service, resource_service, run_service
from caseapi.services.facts_service import FACTS_RESOURCE_ID
from caseapi.services.statute_selection_service import STATUTE_SELECTION_RESOURCE_ID

DEFAULT_INSTRUCTION = '依目前事實與選定法規生成訴願決定書草稿'
DRAFT_KIND = 'decision'
DRAFT_TITLE = '訴願決定書草稿'
PLACEHOLDER_BLOCK = {
    'block_id': 'placeholder',
    'text': '（尚未生成內容）',
    'citations': [],
}
GROUP_ID = 'draft_full_1'
GROUP_REASON = '依目前事實與已核對原文的選定法規生成完整草稿'
RUN_KIND = 'regenerate'
JOB_KIND = 'draft.run'
_APPEAL_ROLE = 'appeal'


def start_generation(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    request: DraftGenerationCreateRequest,
    prompt_version: str,
    provider_config: dict[str, Any],
    kb_release_id: str,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    repo.assert_case_revision(case_row, request.expected_case_revision)
    heads = repo.load_heads(case_row)

    draft_id, draft_revision, case_revision, mutation_id = _ensure_draft_target(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        heads=heads,
        expected_revision=request.expected_case_revision,
    )
    manifest = {
        'case_revision': case_revision,
        'kb_release_id': kb_release_id,
        'instruction': request.instruction or DEFAULT_INSTRUCTION,
        'draft_resource_id': draft_id,
        'draft_resource_revision': draft_revision,
        'facts_revision': _head_revision(heads, FACTS_RESOURCE_ID),
        'statute_selection_revision': _head_revision(heads, STATUTE_SELECTION_RESOURCE_ID),
        'appeal_document_id': _appeal_document_id(conn, case_id=case_id),
    }
    run = run_service.create_run(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        kind=RUN_KIND,
        expected_case_revision=case_revision,
        context_manifest=manifest,
        prompt_version=prompt_version,
        provider_config=provider_config,
        job_kind=JOB_KIND,
        input_refs={'draft_id': draft_id, 'draft_resource_revision': draft_revision},
    )
    append_entry(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action='draft.generation_started',
        mutation_id=mutation_id,
        after_refs={
            'run_id': run['run_id'],
            'draft_id': draft_id,
            'draft_resource_revision': draft_revision,
            'facts_revision': manifest['facts_revision'],
            'statute_selection_revision': manifest['statute_selection_revision'],
        },
    )
    return {
        'run_id': run['run_id'],
        'state': run['state'],
        'draft_id': draft_id,
        'draft_resource_revision': draft_revision,
        'case_revision': case_revision,
    }


def save_generated_proposal(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    run_id: str,
    manifest: dict[str, Any],
    result: ModelResult,
) -> dict[str, Any]:
    """把模型產出的區塊寫成一筆 replace_document 提案（不改正文）。"""
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    target = DocumentTarget(
        kind='document',
        resource_id=manifest['draft_resource_id'],
        resource_revision=manifest['draft_resource_revision'],
    )
    proposal_request = ProposalCreateRequest(
        expected_case_revision=case_row['case_revision'],
        origin='ai',
        mode='full',
        run_id=run_id,
        target=target,
        dependencies=ProposalDependencies(
            facts_revision=manifest.get('facts_revision'),
            kb_release_id=manifest.get('kb_release_id'),
        ),
        evidence=[],
        change_groups=[
            ChangeGroup(
                id=GROUP_ID,
                change_class='structure',
                reason=GROUP_REASON,
                evidence_ids=list(result.evidence_ids),
                operations=[
                    ReplaceDocumentOperation(
                        op='replace_document',
                        target=target,
                        after_blocks=[
                            DraftBlock(
                                block_id=block.block_id,
                                text=block.text,
                                citations=list(block.citations),
                            )
                            for block in result.draft_blocks
                        ],
                    )
                ],
            )
        ],
    )
    return proposal_service.create_proposal(
        conn, case_id=case_id, actor_id=actor_id, request=proposal_request
    )


def _ensure_draft_target(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    heads: dict[str, dict[str, str]],
    expected_revision: int,
) -> tuple[str, str, int, str | None]:
    """已有草稿就重生它；沒有就先建一個空殼，讓提案有可替換的目標。"""
    existing = repo.resource_ids_of_kind(heads, repo.KIND_DRAFT)
    if existing:
        draft_id = existing[0]
        return draft_id, heads[draft_id]['revision_id'], expected_revision, None

    draft_id = new_id('draft')
    version = resource_service.save_version(
        conn,
        case_id=case_id,
        resource_id=draft_id,
        resource_kind=repo.KIND_DRAFT,
        content={
            'draft_kind': DRAFT_KIND,
            'title': DRAFT_TITLE,
            'blocks': [dict(PLACEHOLDER_BLOCK)],
        },
        parent_id=None,
        origin=resource_service.ORIGIN_PROGRAM,
        actor_id=actor_id,
        dependencies={'facts_revision': _head_revision(heads, FACTS_RESOURCE_ID)},
    )
    next_heads = repo.set_head(
        heads,
        resource_id=draft_id,
        kind=repo.KIND_DRAFT,
        revision_id=version['resource_revision'],
        freshness=repo.FRESHNESS_STALE,
    )
    mutation_id = new_id('mut')
    case_revision = repo.advance_case(
        conn,
        case_id=case_id,
        expected_revision=expected_revision,
        heads=next_heads,
        actor_id=actor_id,
        mutation_id=mutation_id,
    )
    return draft_id, version['resource_revision'], case_revision, mutation_id


def _head_revision(heads: dict[str, dict[str, str]], resource_id: str) -> str | None:
    head = heads.get(resource_id)
    return head['revision_id'] if head else None


def _appeal_document_id(conn: sqlite3.Connection, *, case_id: str) -> str | None:
    row = conn.execute(
        'SELECT id FROM case_documents WHERE case_id = ? AND document_role = ?'
        ' ORDER BY created_at ASC LIMIT 1',
        (case_id, _APPEAL_ROLE),
    ).fetchone()
    return row['id'] if row else None
