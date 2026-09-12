"""讀回上傳建案時保存的原始 PDF：列表與內容，供案件詳情頁「原檔展開」使用。"""

import sqlite3

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from caseapi.api.deps import get_actor_id, get_db
from caseapi.envelope import success_response
from caseapi.services import document_service

router = APIRouter(prefix='/api/v1/cases/{case_id}/documents', tags=['cases'])


@router.get('')
def list_documents(
    request: Request,
    case_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    items = document_service.list_documents(conn, case_id=case_id, actor_id=actor_id)
    return success_response(request, {'items': items})


@router.get('/{document_id}/content')
def get_document_content(
    case_id: str,
    document_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> Response:
    content = document_service.get_document_content(
        conn, case_id=case_id, actor_id=actor_id, document_id=document_id
    )
    return Response(content=content, media_type='application/pdf')
