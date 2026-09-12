"""AI run 讀取與取消邊界模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RunState = Literal[
    'queued',
    'running',
    'completed',
    'failed',
    'cancelled',
    'needs_input',
]
RunKind = Literal['chat', 'regenerate', 'analysis']


class RunCancelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    reason: str | None = Field(default=None, max_length=1000)
