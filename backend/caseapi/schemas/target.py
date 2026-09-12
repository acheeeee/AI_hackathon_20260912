"""TargetRef：契約 §2 的選取目標。

每個 kind 帶自己的必要欄位，用 discriminator 分派，缺欄位就是 422，不是靜默忽略。
case_id 由路由取得並驗證，不從請求裡讀。
"""

import hashlib
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseapi.domain.fact_fields import is_allowed_field_path


class _TargetBase(BaseModel):
    model_config = ConfigDict(extra='forbid')

    resource_id: str = Field(min_length=1)
    resource_revision: str = Field(min_length=1)


class DraftBlockTarget(_TargetBase):
    kind: Literal['draft_block']
    block_id: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    selected_text: str
    selected_text_sha256: str

    @model_validator(mode='after')
    def check_range_and_hash(self) -> 'DraftBlockTarget':
        if self.char_end <= self.char_start:
            raise ValueError('char_end 必須大於 char_start，範圍左含右不含')
        if self.char_end - self.char_start != len(self.selected_text):
            raise ValueError('選取範圍長度與 selected_text 不符')
        expected = hashlib.sha256(self.selected_text.encode('utf-8')).hexdigest()
        if self.selected_text_sha256.lower() != expected:
            raise ValueError('selected_text_sha256 與 selected_text 不符')
        return self


class FactFieldTarget(_TargetBase):
    kind: Literal['fact_field']
    field_path: str

    @model_validator(mode='after')
    def check_allowlist(self) -> 'FactFieldTarget':
        if not is_allowed_field_path(self.field_path):
            raise ValueError(f'field_path 不在允許清單內：{self.field_path}')
        return self


class GateResultTarget(_TargetBase):
    kind: Literal['gate_result']
    analysis_id: str = Field(min_length=1)
    gate_id: str = Field(min_length=1)
    issue_scope_id: str | None = None


class SourceSpanTarget(_TargetBase):
    kind: Literal['source_span']
    source_ref: dict[str, Any]


class AnnotationTarget(_TargetBase):
    kind: Literal['annotation']


class DocumentTarget(_TargetBase):
    kind: Literal['document']


TargetRef = Annotated[
    Union[
        DraftBlockTarget,
        FactFieldTarget,
        GateResultTarget,
        SourceSpanTarget,
        AnnotationTarget,
        DocumentTarget,
    ],
    Field(discriminator='kind'),
]
