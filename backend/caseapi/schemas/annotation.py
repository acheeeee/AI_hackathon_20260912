"""註記的請求模型。註記是討論材料，不是已確認事實。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseapi.schemas.target import TargetRef

MAX_BODY_LENGTH = 5000
STATUS_OPEN = 'open'
STATUS_RESOLVED = 'resolved'


class AnnotationCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    target: TargetRef
    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)


class AnnotationPatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_annotation_revision: str = Field(min_length=1)
    body: str | None = Field(default=None, min_length=1, max_length=MAX_BODY_LENGTH)
    status: Literal['open', 'resolved'] | None = None

    @model_validator(mode='after')
    def require_a_change(self) -> 'AnnotationPatchRequest':
        if self.body is None and self.status is None:
            raise ValueError('body 與 status 至少要提供一項')
        return self
