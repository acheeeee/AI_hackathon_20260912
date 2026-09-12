"""資源版本讀取。省略 revision 時取目前 head。"""

import sqlite3

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from caseapi.api.deps import get_actor_id, get_db
from caseapi.envelope import success_response
from caseapi.errors import resource_not_found
from caseapi.services import case_repository as repo
from caseapi.services import resource_service

router = APIRouter(prefix='/api/v1/cases', tags=['resources'])


@router.get('/{case_id}/resources/{resource_id}')
def read_resource(
    request: Request,
    case_id: str,
    resource_id: str,
    revision: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    head = repo.load_heads(case_row).get(resource_id)
    revision_id = revision or (head['revision_id'] if head else None)
    if revision_id is None:
        raise resource_not_found()

    row = resource_service.require_version(
        conn, case_id=case_id, resource_id=resource_id, revision_id=revision_id
    )
    is_head = head is not None and head['revision_id'] == revision_id
    return success_response(
        request,
        resource_service.row_to_payload(
            row, freshness=head['freshness'] if head else None, is_head=is_head
        ),
        case_revision=case_row['case_revision'],
    )


@router.get('/{case_id}/versions')
def list_versions(
    request: Request,
    case_id: str,
    resource_id: str = Query(min_length=1),
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    items = resource_service.list_versions(conn, case_id=case_id, resource_id=resource_id)
    return success_response(request, {'items': items, 'next_cursor': None})
