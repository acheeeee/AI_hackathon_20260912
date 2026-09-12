"""EvidenceRef。

契約 §5.1：source_exists 與 quote_matches 是程式檢查的結果，不是模型自稱。
fixture 提案仍保存 unverified；B2 ``open_source`` 才能保存 program 查證結果。
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ASSESSED_BY_UNVERIFIED = 'unverified'
ASSESSED_BY_PROGRAM = 'program'
SUPPORT_UNKNOWN = 'unknown'
TEMPORAL_UNKNOWN = 'unknown'


class SourceSpan(BaseModel):
    model_config = ConfigDict(extra='forbid')

    page: int = Field(ge=1)
    line: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)


class SourceRef(BaseModel):
    model_config = ConfigDict(extra='forbid')

    kb_release_id: str | None = None
    document_id: str = Field(min_length=1)
    extraction_version: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list)
    url: str | None = None
    retrieved_at: str | None = None
    snapshot_id: str | None = None
    content_hash: str | None = None


class EvidenceInput(BaseModel):
    """由 fixture 端點提供的來源引用。驗證欄位一律由伺服器填入。"""

    model_config = ConfigDict(extra='forbid')

    evidence_id: str = Field(min_length=1)
    source_ref: SourceRef
    quote: str | None = None


class EvidenceRef(BaseModel):
    evidence_id: str
    source_ref: dict[str, Any]
    quote: str | None
    source_exists: bool | None
    quote_matches: bool | None
    support_status: Literal['supported', 'partial', 'contradicted', 'unknown']
    assessed_by: str
    temporal_status: Literal['verified_for_date', 'snapshot_only', 'unknown']
    opened_event_id: str | None
