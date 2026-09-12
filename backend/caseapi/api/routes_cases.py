"""案件端點。交易邊界在這一層，服務層只負責單一職責的讀寫。"""

import sqlite3

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from caseapi.api.deps import get_actor_id, get_db, get_idempotency_key
from caseapi.api.mutation import execute_mutation
from caseapi.envelope import success_response
from caseapi.idempotency import GLOBAL_SCOPE
from caseapi.schemas.case import CaseCreateRequest
from caseapi.services import case_service

router = APIRouter(prefix='/api/v1/cases', tags=['cases'])

CREATE_ENDPOINT = 'POST /api/v1/cases'
DEFAULT_LIST_LIMIT = 20


def _location_headers(case_id: str) -> dict[str, str]:
    return {'Location': f'/api/v1/cases/{case_id}'}


@router.post('', status_code=201)
def create_case(
    request: Request,
    body: CaseCreateRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=GLOBAL_SCOPE,
        endpoint=CREATE_ENDPOINT,
        key=idempotency_key,
        request_body=body.model_dump(mode='json'),
        status_code=201,
        operation=lambda db: case_service.create_case(
            db, actor_id=actor_id, request=body
        ).model_dump(mode='json'),
        headers_from_data=lambda data: _location_headers(data['case_id']),
    )


@router.get('')
def list_cases(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=case_service.MAX_PAGE_SIZE),
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    items, next_cursor = case_service.list_cases(
        conn, actor_id=actor_id, cursor=cursor, limit=limit
    )
    return success_response(
        request,
        {'items': [item.model_dump(mode='json') for item in items], 'next_cursor': next_cursor},
    )


@router.get('/{case_id}')
def get_case(
    request: Request,
    case_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    detail = case_service.get_case(conn, case_id=case_id, actor_id=actor_id)
    return success_response(
        request, detail.model_dump(mode='json'), case_revision=detail.case_revision
    )


@router.get('/{case_id}/audit')
def read_audit(
    request: Request,
    case_id: str,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=case_service.MAX_PAGE_SIZE),
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    entries, next_cursor = case_service.read_case_audit(
        conn, case_id=case_id, actor_id=actor_id, cursor=cursor, limit=limit
    )
    return success_response(request, {'items': entries, 'next_cursor': next_cursor})
