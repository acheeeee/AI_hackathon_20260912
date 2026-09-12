"""會改變狀態的請求共用流程：冪等檢查 → 單一交易 → 記住回應。

設計 03 §7：交易內只做必要的版本／hash／權限複核；冪等成功回應與內容變更
必須同進同出，不能先改資料再補寫紀錄。
"""

import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from caseapi.db.connection import transaction
from caseapi.envelope import build_success, request_id_of
from caseapi.idempotency import find_stored_response, remember_response, request_fingerprint

Operation = Callable[[sqlite3.Connection], dict[str, Any]]
HeadersFromData = Callable[[dict[str, Any]], dict[str, str]]


def execute_mutation(
    request: Request,
    conn: sqlite3.Connection,
    *,
    actor_id: str,
    case_scope: str,
    endpoint: str,
    key: str,
    request_body: Any,
    status_code: int,
    operation: Operation,
    headers_from_data: HeadersFromData | None = None,
) -> JSONResponse:
    fingerprint = request_fingerprint(request_body)
    stored = find_stored_response(
        conn,
        actor_id=actor_id,
        case_scope=case_scope,
        endpoint=endpoint,
        key=key,
        request_hash=fingerprint,
    )
    if stored is not None:
        stored_status, stored_payload = stored
        headers = _headers(stored_payload, headers_from_data) or {}
        headers['Idempotency-Replayed'] = 'true'
        return JSONResponse(
            stored_payload,
            status_code=stored_status,
            headers=headers,
        )

    with transaction(conn):
        data = operation(conn)
        payload = build_success(
            data,
            request_id=request_id_of(request),
            case_revision=data.get('case_revision'),
        )
        remember_response(
            conn,
            actor_id=actor_id,
            case_scope=case_scope,
            endpoint=endpoint,
            key=key,
            request_hash=fingerprint,
            status_code=status_code,
            response=payload,
        )
    headers = _headers(payload, headers_from_data) or {}
    headers['Idempotency-Replayed'] = 'false'
    return JSONResponse(payload, status_code=status_code, headers=headers)


def _headers(
    payload: dict[str, Any], headers_from_data: HeadersFromData | None
) -> dict[str, str] | None:
    if headers_from_data is None:
        return None
    return headers_from_data(payload['data'])
