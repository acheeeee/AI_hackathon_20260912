"""案件的請求與回應模型。驗證在系統邊界做，服務層可假設欄位已合法。"""

from pydantic import BaseModel, ConfigDict, Field

MAX_TITLE_LENGTH = 200
MAX_CASE_NO_LENGTH = 100


class CaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    official_case_no: str | None = Field(default=None, max_length=MAX_CASE_NO_LENGTH)


class CaseSummary(BaseModel):
    case_id: str
    title: str | None
    official_case_no: str | None
    workflow_state: str
    case_revision: int
    created_at: str
    updated_at: str


class CaseDetail(CaseSummary):
    active_heads: dict[str, dict[str, str]]


class CaseListPage(BaseModel):
    items: list[CaseSummary]
    next_cursor: str | None
