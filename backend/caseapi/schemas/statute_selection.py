"""選法規：人工從 BM25 搜尋結果挑選要用的法規，存成一個資源版本。"""

from pydantic import BaseModel, ConfigDict, Field

MAX_REASON_LENGTH = 1000
MAX_SELECTED_ITEMS = 30


class SelectedStatute(BaseModel):
    model_config = ConfigDict(extra='forbid')

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    statute_name: str = Field(min_length=1)
    article_key: str = Field(min_length=1)
    excerpt: str


class StatuteSelectionSaveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    selected: list[SelectedStatute] = Field(max_length=MAX_SELECTED_ITEMS)
