"""背景執行一次草稿生成 run。

與聊天 run（`runner.execute_chat_run`）共用同一套 run／事件／工具邊界，
差別只有兩個：context 是依 run 凍結的 refs 讀出來的（不是一則使用者訊息），
以及結果不是聊天訊息，而是一筆 `replace_document` 提案。

run 被取消時的行為沿用 06 §3 規則 16：`complete_run` 會因為狀態已非
running 而丟例外，例外處理呼叫 `fail_run`，對終態 run 是 no-op。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from caseapi.ai import draft_context, runner
from caseapi.ai.contracts import ModelProvider, ModelRequest, ModelResult
from caseapi.ai.draft_composition import INTENT_DRAFT
from caseapi.db.connection import connect, transaction
from caseapi.services import draft_generation_service, run_service
from caseapi.tools.evidence_tools import EvidenceRepositoryLike, EvidenceToolAdapter


def execute_draft_run(
    *,
    db_path: Path,
    actor_id: str,
    case_id: str,
    run_id: str,
    provider: ModelProvider,
    repository: EvidenceRepositoryLike,
) -> None:
    started = False
    try:
        runner.start_run(db_path, actor_id, case_id, run_id)
        started = True
        request = _load_request(db_path, actor_id, case_id, run_id)
        adapter = EvidenceToolAdapter(
            db_path=db_path, actor_id=actor_id, repository=repository
        )
        result = provider.execute(
            request,
            runner.ToolGateway(case_id=case_id, run_id=run_id, adapter=adapter),
        )
        _save_result(db_path, actor_id, request, result)
    except Exception as exc:
        if started:
            runner.fail_run(db_path, actor_id, case_id, run_id, exc)


def _load_request(
    db_path: Path, actor_id: str, case_id: str, run_id: str
) -> ModelRequest:
    conn = connect(db_path)
    try:
        run = run_service.get_run(
            conn, case_id=case_id, actor_id=actor_id, run_id=run_id
        )
        manifest = run['context_manifest']
        return ModelRequest(
            case_id=case_id,
            run_id=run_id,
            thread_id=None,
            message_id=None,
            content=manifest['instruction'],
            intent=INTENT_DRAFT,
            target=None,
            context_manifest=manifest,
            context=draft_context.load_draft_context(
                conn, case_id=case_id, manifest=manifest
            ),
        )
    finally:
        conn.close()


def _save_result(
    db_path: Path, actor_id: str, request: ModelRequest, result: ModelResult
) -> None:
    conn = connect(db_path)
    try:
        with transaction(conn):
            run_service.append_event(
                conn,
                case_id=request.case_id,
                actor_id=actor_id,
                run_id=request.run_id,
                event_type='answer.delta',
                tool_call_id=None,
                payload={'delta': result.answer},
            )
            proposal = _save_proposal(conn, actor_id, request, result)
            run_service.complete_run(
                conn,
                case_id=request.case_id,
                actor_id=actor_id,
                run_id=request.run_id,
                proposal_ids=[proposal['proposal_id']] if proposal else [],
                payload=_completion_payload(request, proposal),
            )
    finally:
        conn.close()


def _save_proposal(
    conn, actor_id: str, request: ModelRequest, result: ModelResult
) -> dict[str, Any] | None:
    """沒有生成區塊就不假造提案；run 仍算完成，答覆說明為什麼沒生成。"""
    if not result.draft_blocks:
        return None
    proposal = draft_generation_service.save_generated_proposal(
        conn,
        case_id=request.case_id,
        actor_id=actor_id,
        run_id=request.run_id,
        manifest=request.context_manifest,
        result=result,
    )
    run_service.append_event(
        conn,
        case_id=request.case_id,
        actor_id=actor_id,
        run_id=request.run_id,
        event_type='proposal.ready',
        tool_call_id=None,
        payload={
            'proposal_id': proposal['proposal_id'],
            'group_ids': [group['id'] for group in proposal['change_groups']],
            'evidence_ids': list(result.evidence_ids),
        },
    )
    return proposal


def _completion_payload(
    request: ModelRequest, proposal: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        'draft_id': request.context_manifest['draft_resource_id'],
        'proposal_id': proposal['proposal_id'] if proposal else None,
    }
