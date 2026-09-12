"""Read program-verified or fixture evidence within one case."""

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from caseapi.api.deps import get_actor_id, get_db
from caseapi.envelope import success_response
from caseapi.services.proposal_service import read_evidence

router = APIRouter(prefix='/api/v1/cases/{case_id}/evidence', tags=['evidence'])


@router.get('/{evidence_id}')
def get_evidence(
    request: Request,
    case_id: str,
    evidence_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
) -> JSONResponse:
    return success_response(
        request,
        read_evidence(
            conn,
            case_id=case_id,
            actor_id=actor_id,
            evidence_id=evidence_id,
        ),
    )
