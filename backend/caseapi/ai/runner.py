"""Execute one persisted chat job through an allowlisted tool gateway."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from caseapi.ai import revise_selection
from caseapi.ai.contracts import ModelProvider, ModelRequest, ModelResult
from caseapi.db.connection import connect, transaction
from caseapi.evidence.repository import EvidenceRepository
from caseapi.schemas.target import DraftBlockTarget
from caseapi.services import chat_service, revise_selection_service, run_service
from caseapi.tools.evidence_tools import EvidenceRepositoryLike, EvidenceToolAdapter


class ToolGateway:
    """Bind case/run identity so a provider cannot choose another case."""

    def __init__(
        self, *, case_id: str, run_id: str, adapter: EvidenceToolAdapter
    ) -> None:
        self._case_id = case_id
        self._run_id = run_id
        self._adapter = adapter

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        methods = {
            'read_case_resource': self._adapter.read_case_resource,
            'read_selection_context': self._adapter.read_selection_context,
            'search_knowledge': self._adapter.search_knowledge,
            'open_source': self._adapter.open_source,
        }
        method = methods.get(tool)
        if method is None:
            raise ValueError(f'tool is not allowlisted: {tool}')
        return method(case_id=self._case_id, run_id=self._run_id, **arguments)


def execute_chat_run(
    *,
    db_path: Path,
    actor_id: str,
    case_id: str,
    thread_id: str,
    message_id: str,
    run_id: str,
    provider: ModelProvider,
    repository: EvidenceRepositoryLike,
) -> None:
    started = False
    try:
        start_run(db_path, actor_id, case_id, run_id)
        started = True
        request = _load_request(
            db_path, actor_id, case_id, thread_id, message_id, run_id
        )
        adapter = EvidenceToolAdapter(
            db_path=db_path, actor_id=actor_id, repository=repository
        )
        result = provider.execute(
            request,
            ToolGateway(case_id=case_id, run_id=run_id, adapter=adapter),
        )
        _save_result(db_path, actor_id, request, result)
    except Exception as exc:
        if started:
            fail_run(db_path, actor_id, case_id, run_id, exc)


def build_repository(release_dir: Path, release_id: str) -> EvidenceRepository:
    return EvidenceRepository(release_dir, expected_release_id=release_id)


def start_run(db_path: Path, actor_id: str, case_id: str, run_id: str) -> None:
    lease_until = (
        datetime.now(timezone.utc) + timedelta(minutes=5)
    ).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    conn = connect(db_path)
    try:
        with transaction(conn):
            run_service.start_run(
                conn,
                case_id=case_id,
                actor_id=actor_id,
                run_id=run_id,
                lease_until=lease_until,
            )
    finally:
        conn.close()


def _load_request(
    db_path: Path,
    actor_id: str,
    case_id: str,
    thread_id: str,
    message_id: str,
    run_id: str,
) -> ModelRequest:
    conn = connect(db_path)
    try:
        run = run_service.get_run(
            conn, case_id=case_id, actor_id=actor_id, run_id=run_id
        )
        message = chat_service.load_user_message(
            conn,
            case_id=case_id,
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
        )
        return ModelRequest(
            case_id=case_id,
            run_id=run_id,
            thread_id=thread_id,
            message_id=message_id,
            content=message['content'],
            intent=message['intent'],
            target=message['target'],
            context_manifest=run['context_manifest'],
        )
    finally:
        conn.close()
def _save_result(
    db_path: Path,
    actor_id: str,
    request: ModelRequest,
    result: ModelResult,
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
            message = chat_service.save_assistant_message(
                conn,
                case_id=request.case_id,
                thread_id=request.thread_id,
                run_id=request.run_id,
                content=result.answer,
            )
            proposal_ids = _save_revision_proposal_if_any(conn, actor_id, request, result)
            run_service.complete_run(
                conn,
                case_id=request.case_id,
                actor_id=actor_id,
                run_id=request.run_id,
                proposal_ids=proposal_ids,
                payload={
                    'message_id': message['message_id'],
                    'evidence_ids': list(result.evidence_ids),
                },
            )
    finally:
        conn.close()


def _save_revision_proposal_if_any(
    conn, actor_id: str, request: ModelRequest, result: ModelResult
) -> list[str]:
    """`explain`／`verify` 維持只回聊天訊息；`revise_selection` 另外寫一筆提案。"""
    if request.intent != revise_selection.INTENT_REVISE or not result.draft_blocks:
        return []
    target = DraftBlockTarget.model_validate(request.target)
    proposal = revise_selection_service.save_revision_proposal(
        conn,
        case_id=request.case_id,
        actor_id=actor_id,
        run_id=request.run_id,
        target=target,
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
    return [proposal['proposal_id']]


def fail_run(
    db_path: Path,
    actor_id: str,
    case_id: str,
    run_id: str,
    exc: Exception,
) -> None:
    conn = connect(db_path)
    try:
        with transaction(conn):
            run_service.fail_run(
                conn,
                case_id=case_id,
                actor_id=actor_id,
                run_id=run_id,
                error_code='MODEL_RUN_FAILED',
                error_type=type(exc).__name__,
            )
    finally:
        conn.close()
