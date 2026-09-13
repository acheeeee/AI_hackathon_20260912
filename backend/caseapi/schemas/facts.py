"""事實編輯的請求模型。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from caseapi.domain.fact_fields import ANALYSIS_FIELD_VALUE_MAX_LENGTHS, is_allowed_field_path

MAX_REASON_LENGTH = 1000


class FactFieldChange(BaseModel):
    model_config = ConfigDict(extra='forbid')

    field_path: str
    value: str | None
    human_asserted: bool = False
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    source: dict[str, Any] | None = None

    @field_validator('field_path')
    @classmethod
    def check_allowlist(cls, value: str) -> str:
        if not is_allowed_field_path(value):
            raise ValueError(f'field_path 不在允許清單內：{value}')
        return value

    @model_validator(mode='after')
    def check_field_specific_value_limit(self) -> 'FactFieldChange':
        limit = ANALYSIS_FIELD_VALUE_MAX_LENGTHS.get(self.field_path)
        if self.value is not None and limit is not None and len(self.value) > limit:
            raise ValueError(f'{self.field_path} 不得超過 {limit} 字')
        return self


class FactsPatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    field_changes: list[FactFieldChange] = Field(min_length=1)
