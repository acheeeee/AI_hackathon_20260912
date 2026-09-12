"""統一回應 envelope：{success, data, error, meta}。

契約 §1：成功的 error 為 null，失敗的 data 為 null，HTTP 狀態仍反映錯誤。
二進位回應（例如 DOCX）不包 envelope，由該端點自行處理。
"""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from caseapi.errors import ApiError


def request_id_of(request: Request) -> str:
    return getattr(request.state, 'request_id', 'req_unknown')


def build_success(
    data: Any,
    *,
    request_id: str,
    case_revision: int | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {'request_id': request_id}
    if case_revision is not None:
        meta['case_revision'] = case_revision
    return {'success': True, 'data': data, 'error': None, 'meta': meta}


def build_failure(error: ApiError, *, request_id: str) -> dict[str, Any]:
    return {
        'success': False,
        'data': None,
        'error': error.to_payload(),
        'meta': {'request_id': request_id},
    }


def success_response(
    request: Request,
    data: Any,
    *,
    status_code: int = 200,
    case_revision: int | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = build_success(data, request_id=request_id_of(request), case_revision=case_revision)
    return JSONResponse(payload, status_code=status_code, headers=headers)


def error_response(request: Request, error: ApiError) -> JSONResponse:
    payload = build_failure(error, request_id=request_id_of(request))
    return JSONResponse(payload, status_code=error.http_status)
