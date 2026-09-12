"""草稿端點。

POST /drafts 是已記錄在 04 契約的階段 A 暫時入口；正式流程應改由抽文或
generation run 建立，現階段保留以驗證版本與合併。
"""

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from caseapi.api.deps import get_actor_id, get_db, get_idempotency_key
from caseapi.api.mutation import execute_mutation
from caseapi.schemas.draft import DraftCreateRequest, DraftPatchRequest, DraftReviewRequest
from caseapi.services import draft_service

router = APIRouter(prefix='/api/v1/cases', tags=['drafts'])


@router.post('/{case_id}/drafts', status_code=201)
def create_draft(
    request: Request,
    case_id: str,
    body: DraftCreateRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='POST /api/v1/cases/{case_id}/drafts',
        key=idempotency_key,
        request_body=body.model_dump(mode='json'),
        status_code=201,
        operation=lambda db: draft_service.create_draft(
            db, case_id=case_id, actor_id=actor_id, request=body
        ),
        headers_from_data=lambda data: {
            'Location': f'/api/v1/cases/{case_id}/resources/{data["draft_id"]}'
        },
    )


@router.patch('/{case_id}/drafts/{draft_id}')
def patch_draft(
    request: Request,
    case_id: str,
    draft_id: str,
    body: DraftPatchRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='PATCH /api/v1/cases/{case_id}/drafts/{draft_id}',
        key=idempotency_key,
        request_body={'draft_id': draft_id, **body.model_dump(mode='json')},
        status_code=200,
        operation=lambda db: draft_service.patch_draft(
            db, case_id=case_id, actor_id=actor_id, draft_id=draft_id, request=body
        ),
    )


@router.post('/{case_id}/drafts/{draft_id}/reviews', status_code=201)
def review_draft(
    request: Request,
    case_id: str,
    draft_id: str,
    body: DraftReviewRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='POST /api/v1/cases/{case_id}/drafts/{draft_id}/reviews',
        key=idempotency_key,
        request_body={'draft_id': draft_id, **body.model_dump(mode='json')},
        status_code=201,
        operation=lambda db: draft_service.review_draft(
            db, case_id=case_id, actor_id=actor_id, draft_id=draft_id, request=body
        ),
    )
