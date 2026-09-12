"""Fixed-model chat request schemas for the first end-to-end path."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from caseapi.schemas.target import TargetRef


class ChatThreadCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    title: str | None = Field(default=None, min_length=1, max_length=200)


class AnnotationRef(BaseModel):
    model_config = ConfigDict(extra='forbid')

    annotation_id: str = Field(min_length=1)
    resource_revision: str = Field(min_length=1)


class ChatMessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=8000)
    intent: Literal['explain', 'verify']
    target: TargetRef | None = None
    annotation_refs: list[AnnotationRef] = Field(default_factory=list, max_length=20)
