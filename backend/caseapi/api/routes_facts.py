"""事實編輯端點。"""

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from caseapi.api.deps import get_actor_id, get_db, get_idempotency_key
from caseapi.api.mutation import execute_mutation
from caseapi.envelope import success_response
from caseapi.schemas.facts import FactsPatchRequest
from caseapi.services import facts_service

router = APIRouter(prefix='/api/v1/cases', tags=['facts'])

PATCH_FACTS_ENDPOINT = 'PATCH /api/v1/cases/{case_id}/facts'


@router.get('/{case_id}/facts')
def get_facts(
    request: Request,
    case_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    data = facts_service.get_facts(conn, case_id=case_id, actor_id=actor_id)
    return success_response(request, data, case_revision=data['case_revision'])


@router.patch('/{case_id}/facts')
def patch_facts(
    request: Request,
    case_id: str,
    body: FactsPatchRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint=PATCH_FACTS_ENDPOINT,
        key=idempotency_key,
        request_body=body.model_dump(mode='json'),
        status_code=200,
        operation=lambda db: facts_service.patch_facts(
            db, case_id=case_id, actor_id=actor_id, request=body
        ),
    )
