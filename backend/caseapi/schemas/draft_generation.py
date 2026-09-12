"""草稿生成 run 的請求模型。

真正的草稿內容不由呼叫端提供——那是階段 A fixture `POST /drafts` 的做法。
這裡只帶樂觀鎖用的案件版本與一句可選的指示，其餘 context 由伺服器依目前
事實、選定法規與訴願書原文組出來並凍結在 run 裡。
"""

from pydantic import BaseModel, ConfigDict, Field

MAX_INSTRUCTION_LENGTH = 2000


class DraftGenerationCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    instruction: str | None = Field(default=None, min_length=1, max_length=MAX_INSTRUCTION_LENGTH)
