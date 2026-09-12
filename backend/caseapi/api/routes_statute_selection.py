"""選法規：BM25 搜尋候選（唯讀）與人工挑選結果的讀寫。"""

import sqlite3

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from caseapi.api.deps import (
    get_actor_id,
    get_db,
    get_evidence_repository,
    get_idempotency_key,
)
from caseapi.api.mutation import execute_mutation
from caseapi.envelope import success_response
from caseapi.schemas.statute_selection import StatuteSelectionSaveRequest
from caseapi.services import statute_selection_service
from caseapi.services.statute_selection_service import StatuteRepositoryLike

router = APIRouter(prefix='/api/v1/cases/{case_id}', tags=['cases'])

SAVE_SELECTION_ENDPOINT = 'PUT /api/v1/cases/{case_id}/statute-selection'


@router.get('/statute-search')
def search_statutes(
    request: Request,
    case_id: str,
    q: str | None = Query(default=None),
    top_k: int = Query(default=statute_selection_service.DEFAULT_TOP_K, ge=1, le=20),
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    repository: StatuteRepositoryLike = Depends(get_evidence_repository),
) -> JSONResponse:
    data = statute_selection_service.search_statutes(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        repository=repository,
        query=q,
        top_k=top_k,
    )
    return success_response(request, data)


@router.get('/statute-selection')
def get_statute_selection(
    request: Request,
    case_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    data = statute_selection_service.get_selection(conn, case_id=case_id, actor_id=actor_id)
    return success_response(request, data)


@router.put('/statute-selection')
def save_statute_selection(
    request: Request,
    case_id: str,
    body: StatuteSelectionSaveRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint=SAVE_SELECTION_ENDPOINT,
        key=idempotency_key,
        request_body=body.model_dump(mode='json'),
        status_code=200,
        operation=lambda db: statute_selection_service.save_selection(
            db, case_id=case_id, actor_id=actor_id, request=body
        ),
    )
