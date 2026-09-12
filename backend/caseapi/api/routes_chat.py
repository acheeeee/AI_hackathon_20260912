"""Case chat endpoints backed by persisted jobs and the fixed model runner."""

import json
import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse

from caseapi.ai.runner import execute_chat_run
from caseapi.api.deps import (
    get_actor_id,
    get_db,
    get_evidence_repository,
    get_idempotency_key,
)
from caseapi.api.mutation import execute_mutation
from caseapi.envelope import success_response
from caseapi.schemas.chat import ChatMessageCreateRequest, ChatThreadCreateRequest
from caseapi.services import chat_service
from caseapi.tools.evidence_tools import EvidenceRepositoryLike

router = APIRouter(prefix='/api/v1/cases/{case_id}/chat-threads', tags=['chat'])


@router.post('')
def create_thread(
    request: Request,
    case_id: str,
    body: ChatThreadCreateRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='POST /api/v1/cases/{case_id}/chat-threads',
        key=idempotency_key,
        request_body=body.model_dump(mode='json'),
        status_code=201,
        operation=lambda db: chat_service.create_thread(
            db, case_id=case_id, actor_id=actor_id, title=body.title
        ),
        headers_from_data=lambda data: {
            'Location': f'/api/v1/cases/{case_id}/chat-threads/{data["thread_id"]}'
        },
    )


@router.get('/{thread_id}/messages')
def list_messages(
    request: Request,
    case_id: str,
    thread_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    items = chat_service.list_messages(
        conn, case_id=case_id, thread_id=thread_id, actor_id=actor_id
    )
    return success_response(request, {'items': items, 'next_cursor': None})


@router.post('/{thread_id}/messages')
def create_message(
    request: Request,
    background_tasks: BackgroundTasks,
    case_id: str,
    thread_id: str,
    body: ChatMessageCreateRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
    repository: EvidenceRepositoryLike = Depends(get_evidence_repository),
) -> JSONResponse:
    provider = request.app.state.model_provider
    response = execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='POST /api/v1/cases/{case_id}/chat-threads/{thread_id}/messages',
        key=idempotency_key,
        request_body={'thread_id': thread_id, **body.model_dump(mode='json')},
        status_code=202,
        operation=lambda db: chat_service.create_message_run(
            db,
            case_id=case_id,
            thread_id=thread_id,
            actor_id=actor_id,
            request=body,
            prompt_version=provider.prompt_version,
            provider_config=provider.descriptor(),
            kb_release_id=repository.release_id,
        ),
    )
    if response.headers['Idempotency-Replayed'] == 'false':
        created = json.loads(response.body)['data']
        settings = request.app.state.settings
        background_tasks.add_task(
            execute_chat_run,
            db_path=settings.db_path,
            actor_id=actor_id,
            case_id=case_id,
            thread_id=thread_id,
            message_id=created['message_id'],
            run_id=created['run_id'],
            provider=provider,
            repository=repository,
        )
    return response
