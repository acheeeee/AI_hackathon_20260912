"""註記端點。註記不推進 case_revision，只增加討論材料。"""

import sqlite3

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from caseapi.api.deps import get_actor_id, get_db, get_idempotency_key
from caseapi.api.mutation import execute_mutation
from caseapi.envelope import success_response
from caseapi.schemas.annotation import AnnotationCreateRequest, AnnotationPatchRequest
from caseapi.services import annotation_service

router = APIRouter(prefix='/api/v1/cases', tags=['annotations'])


@router.post('/{case_id}/annotations', status_code=201)
def create_annotation(
    request: Request,
    case_id: str,
    body: AnnotationCreateRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='POST /api/v1/cases/{case_id}/annotations',
        key=idempotency_key,
        request_body=body.model_dump(mode='json'),
        status_code=201,
        operation=lambda db: annotation_service.create_annotation(
            db, case_id=case_id, actor_id=actor_id, request=body
        ),
    )


@router.patch('/{case_id}/annotations/{annotation_id}')
def patch_annotation(
    request: Request,
    case_id: str,
    annotation_id: str,
    body: AnnotationPatchRequest,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
) -> JSONResponse:
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=case_id,
        endpoint='PATCH /api/v1/cases/{case_id}/annotations/{annotation_id}',
        key=idempotency_key,
        request_body={'annotation_id': annotation_id, **body.model_dump(mode='json')},
        status_code=200,
        operation=lambda db: annotation_service.patch_annotation(
            db,
            case_id=case_id,
            actor_id=actor_id,
            annotation_id=annotation_id,
            request=body,
        ),
    )


@router.get('/{case_id}/annotations')
def list_annotations(
    request: Request,
    case_id: str,
    resource_id: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    items = annotation_service.list_annotations(
        conn, case_id=case_id, actor_id=actor_id, resource_id=resource_id
    )
    return success_response(request, {'items': items, 'next_cursor': None})


@router.get('/{case_id}/annotations/{annotation_id}')
def get_annotation(
    request: Request,
    case_id: str,
    annotation_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    return success_response(
        request,
        annotation_service.get_annotation(
            conn, case_id=case_id, actor_id=actor_id, annotation_id=annotation_id
        ),
    )
