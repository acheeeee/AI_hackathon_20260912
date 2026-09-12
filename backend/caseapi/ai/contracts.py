"""Provider boundary shared by deterministic and future online models."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelRequest:
    case_id: str
    run_id: str
    thread_id: str
    message_id: str
    content: str
    intent: str
    target: dict[str, Any] | None
    context_manifest: dict[str, Any]


@dataclass(frozen=True)
class ModelResult:
    answer: str
    evidence_ids: tuple[str, ...] = ()


class ToolGatewayLike(Protocol):
    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class ModelProvider(Protocol):
    prompt_version: str

    def descriptor(self) -> dict[str, str]: ...

    def execute(self, request: ModelRequest, tools: ToolGatewayLike) -> ModelResult: ...
