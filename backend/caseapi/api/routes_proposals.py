"""提案、合併預覽與採用端點。

POST /proposals 是已記錄在 04 契約的階段 A fixture 入口；正式提案由 run
產生。這個端點只為驗證 Proposal -> merge -> apply 鏈。
"""

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from caseapi.api.deps import get_actor_id, get_db, get_idempotency_key
from caseapi.api.mutation import execute_mutation
from caseapi.envelope import success_response
from caseapi.schemas.proposal import (
    ApplicationRequest,
    MergePreviewRequest,
    ProposalCreateRequest,
    RejectionRequest,
    ResolutionRequest,
)
from caseapi.services import apply_service, merge_service, proposal_service

router = APIRouter(prefix='/api/v1/cases', tags=['proposals'])


@router.post('/{case_id}/proposals', status_code=201)
def create_proposal(
    request: Request,
    case_id: str,
    body: ProposalCreateRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='POST /api/v1/cases/{case_id}/proposals',
        key=idempotency_key,
        request_body=body.model_dump(mode='json'),
        status_code=201,
        operation=lambda db: proposal_service.create_proposal(
            db, case_id=case_id, actor_id=actor_id, request=body
        ),
    )


@router.get('/{case_id}/proposals/{proposal_id}')
def read_proposal(
    request: Request,
    case_id: str,
    proposal_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    return success_response(
        request,
        proposal_service.read_proposal(
            conn, case_id=case_id, actor_id=actor_id, proposal_id=proposal_id
        ),
    )


@router.post('/{case_id}/proposals/{proposal_id}/merge-previews', status_code=201)
def create_merge_preview(
    request: Request,
    case_id: str,
    proposal_id: str,
    body: MergePreviewRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='POST /api/v1/cases/{case_id}/proposals/{proposal_id}/merge-previews',
        key=idempotency_key,
        request_body={'proposal_id': proposal_id, **body.model_dump(mode='json')},
        status_code=201,
        operation=lambda db: merge_service.build_preview(
            db, case_id=case_id, actor_id=actor_id, proposal_id=proposal_id, request=body
        ),
    )


@router.post(
    '/{case_id}/proposals/{proposal_id}/merge-previews/{preview_id}/resolutions',
    status_code=201,
)
def create_resolution(
    request: Request,
    case_id: str,
    proposal_id: str,
    preview_id: str,
    body: ResolutionRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='POST /api/v1/cases/{case_id}/proposals/{proposal_id}'
        '/merge-previews/{preview_id}/resolutions',
        key=idempotency_key,
        request_body={'preview_id': preview_id, **body.model_dump(mode='json')},
        status_code=201,
        operation=lambda db: merge_service.resolve_preview(
            db,
            case_id=case_id,
            actor_id=actor_id,
            proposal_id=proposal_id,
            preview_id=preview_id,
            request=body,
        ),
    )


@router.post('/{case_id}/proposals/{proposal_id}/applications')
def apply_proposal(
    request: Request,
    case_id: str,
    proposal_id: str,
    body: ApplicationRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='POST /api/v1/cases/{case_id}/proposals/{proposal_id}/applications',
        key=idempotency_key,
        request_body={'proposal_id': proposal_id, **body.model_dump(mode='json')},
        status_code=200,
        operation=lambda db: apply_service.apply_proposal(
            db, case_id=case_id, actor_id=actor_id, proposal_id=proposal_id, request=body
        ),
    )


@router.post('/{case_id}/proposals/{proposal_id}/rejections')
def reject_proposal(
    request: Request,
    case_id: str,
    proposal_id: str,
    body: RejectionRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='POST /api/v1/cases/{case_id}/proposals/{proposal_id}/rejections',
        key=idempotency_key,
        request_body={'proposal_id': proposal_id, **body.model_dump(mode='json')},
        status_code=200,
        operation=lambda db: proposal_service.reject_proposal(
            db, case_id=case_id, actor_id=actor_id, proposal_id=proposal_id, request=body
        ),
    )


@router.get('/{case_id}/evidence/{evidence_id}')
def read_evidence(
    request: Request,
    case_id: str,
    evidence_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    return success_response(
        request,
        proposal_service.read_evidence(
            conn, case_id=case_id, actor_id=actor_id, evidence_id=evidence_id
        ),
    )
