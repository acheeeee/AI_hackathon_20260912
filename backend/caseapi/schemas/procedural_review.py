"""程序審查讀取回應的邊界模型。"""

from typing import Any, Literal

from pydantic import BaseModel, Field

Article77Outcome = Literal[
    'NOT_TRIGGERED',
    'TRIGGERED',
    'NOT_APPLICABLE',
    'INSUFFICIENT_EVIDENCE',
    'NEEDS_HUMAN',
]
Article77EvaluationMode = Literal['rule', 'mock', 'manual_review']
DeadlineStatus = Literal[
    'insufficient_data',
    'deadline_known_filing_unknown',
    'within_period',
    'overdue',
]
AssessmentInputValue = str | int | bool | None


class Article77ClauseAssessment(BaseModel):
    clause_no: int = Field(ge=1, le=8)
    rule_id: str = Field(min_length=1)
    input: dict[str, AssessmentInputValue]
    status: Article77Outcome
    rule_description: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evaluation_mode: Article77EvaluationMode
    missing_fields: list[str] = Field(default_factory=list)
    input_sources: dict[str, Any] = Field(default_factory=dict)


class ProceduralFieldOption(BaseModel):
    value: str
    label: str


class ProceduralFieldDefinition(BaseModel):
    field_path: str
    label: str
    input_type: Literal['select', 'date', 'text']
    options: list[ProceduralFieldOption] = Field(default_factory=list)
    help_text: str = ''


class ProceduralReviewResponse(BaseModel):
    case_id: str
    case_revision: int = Field(default=1, ge=1)
    field_definitions: list[ProceduralFieldDefinition] = Field(default_factory=list)
    status: DeadlineStatus
    deadline_date: str | None
    days_from_deadline: int | None
    missing_fields: list[str]
    statute_basis: str
    caveats: list[str]
    legal_review_status: Literal['not_reviewed']
    clause_assessments: list[Article77ClauseAssessment] = Field(
        min_length=8,
        max_length=8,
    )
