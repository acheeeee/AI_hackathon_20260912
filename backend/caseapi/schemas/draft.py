"""草稿的請求模型。

POST /drafts 是 04 契約已記錄的階段 A 暫時入口；沒有初始 draft 就無法驗證
版本／編輯流程，正式流程應改由抽文或 generation run 建立。
"""

from pydantic import BaseModel, ConfigDict, Field

MAX_BLOCK_TEXT_LENGTH = 20000
MAX_REASON_LENGTH = 1000


class DraftBlock(BaseModel):
    model_config = ConfigDict(extra='forbid')

    block_id: str = Field(min_length=1)
    text: str = Field(max_length=MAX_BLOCK_TEXT_LENGTH)
    citations: list[str] = Field(default_factory=list)


class DraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    draft_kind: str = Field(min_length=1)
    title: str | None = None
    blocks: list[DraftBlock] = Field(min_length=1)


class DraftPatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    base_resource_revision: str = Field(min_length=1)
    block_changes: list[DraftBlock] = Field(min_length=1)


class DraftReviewRequest(BaseModel):
    """人工覆核：設計 03 §4 規定不能單改 freshness 旗標，必須留下理由。"""

    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    base_resource_revision: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
