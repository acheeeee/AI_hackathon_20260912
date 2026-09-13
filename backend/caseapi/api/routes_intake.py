"""上傳建案端點：訴願書＋選填的行政處分函，建立案件並種下規則式抽取事實。"""

import hashlib
import sqlite3

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from caseapi.ai.contracts import ModelProvider
from caseapi.api.deps import get_actor_id, get_db, get_idempotency_key, get_model_provider
from caseapi.api.mutation import execute_mutation
from caseapi.errors import invalid_field
from caseapi.idempotency import GLOBAL_SCOPE, find_stored_response, request_fingerprint
from caseapi.services import intake_service

router = APIRouter(prefix='/api/v1/cases', tags=['cases'])

INTAKE_ENDPOINT = 'POST /api/v1/cases/intake'
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _read_pdf(upload: UploadFile, *, field_name: str) -> bytes:
    content = upload.file.read()
    if not content:
        raise invalid_field(f'{field_name} 是空檔案', {'field': field_name})
    if len(content) > MAX_UPLOAD_BYTES:
        raise invalid_field(f'{field_name} 超過大小上限', {'field': field_name})
    if not content.startswith(b'%PDF'):
        raise invalid_field(f'{field_name} 不是有效的 PDF', {'field': field_name})
    return content


@router.post('/intake', status_code=201)
def intake_case(
    request: Request,
    appeal_pdf: UploadFile = File(...),
    disposition_pdf: UploadFile | None = File(default=None),
    title: str | None = Form(default=None),
    consent_to_online_analysis: bool = Form(default=False),
    conn: sqlite3.Connection = Depends(get_db),
    actor_id: str = Depends(get_actor_id),
    idempotency_key: str = Depends(get_idempotency_key),
    model_provider: ModelProvider = Depends(get_model_provider),
) -> JSONResponse:
    appeal_bytes = _read_pdf(appeal_pdf, field_name='appeal_pdf')
    disposition_bytes = (
        _read_pdf(disposition_pdf, field_name='disposition_pdf')
        if disposition_pdf is not None
        else None
    )
    fingerprint = {
        'title': title,
        'appeal_filename': appeal_pdf.filename,
        'appeal_sha256': hashlib.sha256(appeal_bytes).hexdigest(),
        'disposition_filename': disposition_pdf.filename if disposition_pdf else None,
        'disposition_sha256': (
            hashlib.sha256(disposition_bytes).hexdigest() if disposition_bytes else None
        ),
        'consent_to_online_analysis': consent_to_online_analysis,
    }
    stored = find_stored_response(
        conn,
        actor_id=actor_id,
        case_scope=GLOBAL_SCOPE,
        endpoint=INTAKE_ENDPOINT,
        key=idempotency_key,
        request_hash=request_fingerprint(fingerprint),
    )
    if stored is not None:
        stored_status, stored_payload = stored
        return JSONResponse(
            stored_payload,
            status_code=stored_status,
            headers={
                'Location': f'/api/v1/cases/{stored_payload["data"]["case_id"]}',
                'Idempotency-Replayed': 'true',
            },
        )

    prepared = intake_service.prepare_intake(
        appeal_bytes=appeal_bytes,
        disposition_bytes=disposition_bytes,
        configured_provider=model_provider,
        consent_to_online_analysis=consent_to_online_analysis,
    )
    return execute_mutation(
        request,
        conn,
        actor_id=actor_id,
        case_scope=GLOBAL_SCOPE,
        endpoint=INTAKE_ENDPOINT,
        key=idempotency_key,
        request_body=fingerprint,
        status_code=201,
        operation=lambda db: intake_service.intake_case(
            db,
            actor_id=actor_id,
            title=title,
            appeal_filename=appeal_pdf.filename or 'appeal.pdf',
            appeal_bytes=appeal_bytes,
            disposition_filename=disposition_pdf.filename if disposition_pdf else None,
            disposition_bytes=disposition_bytes,
            prepared=prepared,
        ),
        headers_from_data=lambda data: {'Location': f'/api/v1/cases/{data["case_id"]}'},
    )
