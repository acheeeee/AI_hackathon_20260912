"""契約第 7 節的錯誤物件。details 只放使用者可讀資訊，不含 SQL 或其他案件內容。"""

from typing import Any


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        http_status: int,
        message: str,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message = message
        self.details = dict(details or {})
        self.retryable = retryable

    def to_payload(self) -> dict[str, Any]:
        return {
            'code': self.code,
            'message': self.message,
            'details': self.details,
            'retryable': self.retryable,
        }


def malformed_request(message: str = '請求格式無法解析') -> ApiError:
    return ApiError('MALFORMED_REQUEST', 400, message)


def resource_not_found(message: str = '找不到資源，或沒有讀取權限') -> ApiError:
    """跨案與不存在一律同樣回應，不讓呼叫端從錯誤訊息推敲其他案件是否存在。"""
    return ApiError('RESOURCE_NOT_FOUND', 404, message)


def invalid_field(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError('INVALID_FIELD', 422, message, details)


def idempotency_key_reused() -> ApiError:
    return ApiError(
        'IDEMPOTENCY_KEY_REUSED',
        409,
        '同一個 Idempotency-Key 已用於不同的請求內容',
    )


def revision_conflict(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError('REVISION_CONFLICT', 409, message, details)


def database_busy() -> ApiError:
    return ApiError('DATABASE_BUSY', 503, '資料庫忙碌，請稍後重試', retryable=True)


def target_moved(message: str, details: dict[str, Any] | None = None) -> ApiError:
    """目標區塊／範圍已不在原位。禁止猜測替換，交回前端重新定位。"""
    return ApiError('TARGET_MOVED', 409, message, details)


def dependency_stale(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError('DEPENDENCY_STALE', 409, message, details)


def out_of_scope_patch(message: str, details: dict[str, Any] | None = None) -> ApiError:
    """候選動到核准範圍以外的內容，或基底與已凍結版本不符。"""
    return ApiError('OUT_OF_SCOPE_PATCH', 422, message, details)


def invalid_citation(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError('INVALID_CITATION', 422, message, details)


def proposal_already_applied(details: dict[str, Any] | None = None) -> ApiError:
    return ApiError('PROPOSAL_ALREADY_APPLIED', 409, '這些修改組已經套用過，不再重複變更', details)


def run_not_cancellable(state: str) -> ApiError:
    return ApiError(
        'RUN_NOT_CANCELLABLE',
        409,
        '這個 run 已經結束，不能再取消',
        {'state': state},
    )
