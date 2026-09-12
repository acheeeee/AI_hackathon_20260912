"""Run 狀態、已保存事件 JSON replay 與取消端點。"""

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from caseapi.api.deps import get_actor_id, get_db, get_idempotency_key
from caseapi.api.mutation import execute_mutation
from caseapi.envelope import success_response
from caseapi.schemas.run import RunCancelRequest
from caseapi.services import run_service

router = APIRouter(prefix='/api/v1/cases/{case_id}/runs', tags=['runs'])
MAX_EVENT_PAGE_SIZE = 200


@router.get('/{run_id}')
def get_run(
    request: Request,
    case_id: str,
    run_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    data = run_service.get_run(
        conn, case_id=case_id, actor_id=actor_id, run_id=run_id
    )
    return success_response(request, data)


@router.get('/{run_id}/events')
def get_run_events(
    request: Request,
    case_id: str,
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=MAX_EVENT_PAGE_SIZE),
    response_format: Literal['json'] = Query(default='json', alias='format'),
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    del response_format
    events, next_sequence = run_service.list_events(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        run_id=run_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return success_response(
        request,
        {'items': events, 'next_after_sequence': next_sequence},
    )


@router.post('/{run_id}/cancellations')
def cancel_run(
    request: Request,
    case_id: str,
    run_id: str,
    body: RunCancelRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    endpoint = 'POST /api/v1/cases/{case_id}/runs/{run_id}/cancellations'
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint=endpoint,
        key=idempotency_key,
        request_body={'run_id': run_id, **body.model_dump(mode='json')},
        status_code=200,
        operation=lambda db: run_service.cancel_run(
            db,
            case_id=case_id,
            actor_id=actor_id,
            run_id=run_id,
            reason=body.reason,
        ),
    )
