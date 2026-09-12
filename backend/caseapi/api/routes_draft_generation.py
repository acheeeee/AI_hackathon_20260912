"""草稿生成端點：202 + 背景 run，結果是提案不是正文。

取代階段 A 的 fixture 入口（`POST /drafts` 直接收整份內容）；前端只送案件
版本與可選指示，草稿內容由 run 依凍結的事實／選定法規／訴願書原文生成。
"""

import json
import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse

from caseapi.ai.draft_runner import execute_draft_run
from caseapi.api.deps import (
    get_actor_id,
    get_db,
    get_evidence_repository,
    get_idempotency_key,
)
from caseapi.api.mutation import execute_mutation
from caseapi.schemas.draft_generation import DraftGenerationCreateRequest
from caseapi.services import draft_generation_service
from caseapi.tools.evidence_tools import EvidenceRepositoryLike

router = APIRouter(prefix='/api/v1/cases', tags=['drafts'])

ENDPOINT = 'POST /api/v1/cases/{case_id}/draft-generations'


@router.post('/{case_id}/draft-generations', status_code=202)
def start_draft_generation(
    request: Request,
    background_tasks: BackgroundTasks,
    case_id: str,
    body: DraftGenerationCreateRequest,
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
        endpoint=ENDPOINT,
        key=idempotency_key,
        request_body=body.model_dump(mode='json'),
        status_code=202,
        operation=lambda db: draft_generation_service.start_generation(
            db,
            case_id=case_id,
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
            execute_draft_run,
            db_path=settings.db_path,
            actor_id=actor_id,
            case_id=case_id,
            run_id=created['run_id'],
            provider=provider,
            repository=repository,
        )
    return response
