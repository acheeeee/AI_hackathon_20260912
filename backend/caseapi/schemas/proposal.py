"""Proposal、修改組與 allowlist 操作。

契約 §2：不接受任意 JSON Patch。每個操作都要 typed target、before 值／hash
與 after 值；未知操作或未知 path 一律拒絕。
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseapi.domain.procedural_fields import validate_procedural_field_value

from caseapi.schemas.draft import DraftBlock
from caseapi.schemas.evidence import EvidenceInput
from caseapi.schemas.target import DocumentTarget, DraftBlockTarget, FactFieldTarget, TargetRef

CHANGE_CLASSES = ('wording', 'fact', 'legal_assessment', 'citation', 'structure')
STATE_READY = 'ready'
STATE_PARTIALLY_APPLIED = 'partially_applied'
STATE_APPLIED = 'applied'
STATE_REJECTED = 'rejected'

MAX_REASON_LENGTH = 1000


class BlockRef(BaseModel):
    """引用操作只需要定位到區塊，不需要字元範圍。"""

    model_config = ConfigDict(extra='forbid')

    resource_id: str = Field(min_length=1)
    resource_revision: str = Field(min_length=1)
    block_id: str = Field(min_length=1)


class ReplaceTextOperation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    op: Literal['replace_text']
    target: DraftBlockTarget
    after_value: str


class ReplaceFactOperation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    op: Literal['replace_fact']
    target: FactFieldTarget
    before_value: str | None
    after_value: str | None

    @model_validator(mode='after')
    def validate_procedural_value(self) -> 'ReplaceFactOperation':
        validate_procedural_field_value(self.target.field_path, self.after_value)
        return self


class AddCitationOperation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    op: Literal['add_citation']
    target: BlockRef
    evidence_id: str = Field(min_length=1)


class RemoveCitationOperation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    op: Literal['remove_citation']
    target: BlockRef
    evidence_id: str = Field(min_length=1)


class ReplaceDocumentOperation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    op: Literal['replace_document']
    target: DocumentTarget
    after_blocks: list[DraftBlock] = Field(min_length=1)


Operation = Annotated[
    Union[
        ReplaceTextOperation,
        ReplaceFactOperation,
        AddCitationOperation,
        RemoveCitationOperation,
        ReplaceDocumentOperation,
    ],
    Field(discriminator='op'),
]


class ChangeGroup(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str = Field(min_length=1)
    change_class: Literal['wording', 'fact', 'legal_assessment', 'citation', 'structure']
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    depends_on_group_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    operations: list[Operation] = Field(min_length=1)


class ProposalDependencies(BaseModel):
    model_config = ConfigDict(extra='forbid')

    facts_revision: str | None = None
    kb_release_id: str | None = None
    ruleset_version: str | None = None


class ProposalCreateRequest(BaseModel):
    """fixture 端點的請求。階段 B 之後由 run 產生提案，改走 chat／generation 端點。"""

    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    origin: Literal['ai', 'reversion']
    mode: Literal['local', 'full']
    run_id: str | None = None
    target: TargetRef
    dependencies: ProposalDependencies = Field(default_factory=ProposalDependencies)
    evidence: list[EvidenceInput] = Field(default_factory=list)
    change_groups: list[ChangeGroup] = Field(min_length=1)


class MergePreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    selected_group_ids: list[str] = Field(min_length=1)


class BlockResolution(BaseModel):
    model_config = ConfigDict(extra='forbid')

    resource_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    text: str


class ResolutionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    resolutions: list[BlockResolution] = Field(min_length=1)


class ApplicationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expected_case_revision: int = Field(ge=1)
    preview_id: str = Field(min_length=1)
    preview_hash: str = Field(min_length=1)
    accepted_group_ids: list[str] = Field(min_length=1)


class RejectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
