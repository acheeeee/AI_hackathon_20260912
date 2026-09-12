"""程序審查（訴願法第14條期間試算）讀取端點。未經法律覆核，只給計算過程。"""

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from caseapi.api.deps import get_actor_id, get_db
from caseapi.envelope import success_response
from caseapi.services import procedural_review_service

router = APIRouter(prefix='/api/v1/cases/{case_id}/procedural-review', tags=['cases'])


@router.get('')
def get_procedural_review(
    request: Request,
    case_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    data = procedural_review_service.get_procedural_review(
        conn, case_id=case_id, actor_id=actor_id
    )
    return success_response(request, data)
