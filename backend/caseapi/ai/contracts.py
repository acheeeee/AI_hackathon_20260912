"""Provider boundary shared by deterministic and future online models."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelRequest:
    case_id: str
    run_id: str
    thread_id: str | None
    message_id: str | None
    content: str
    intent: str
    target: dict[str, Any] | None
    context_manifest: dict[str, Any]
    # 已由伺服器依 context_manifest 的凍結 refs 讀出來的內容（事實／選定法規／
    # 訴願書原文）。provider 拿到的是資料，不是 DB 連線——06 §3 規則 15。
    context: dict[str, Any] | None = None


@dataclass(frozen=True)
class GeneratedBlock:
    """模型產出的草稿區塊；citations 只放已由 open_source 驗證過的 evidence id。"""

    block_id: str
    text: str
    citations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelResult:
    answer: str
    evidence_ids: tuple[str, ...] = ()
    draft_blocks: tuple[GeneratedBlock, ...] = ()


class ToolGatewayLike(Protocol):
    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class ModelProvider(Protocol):
    prompt_version: str

    def descriptor(self) -> dict[str, str]: ...

    def execute(self, request: ModelRequest, tools: ToolGatewayLike) -> ModelResult: ...
