"""Online ModelProvider backed by AWS Bedrock AgentCore Runtime.

Retrieval stays local and real: this provider only ever calls the four
allowlisted tools through `ToolGatewayLike`, exactly like `FixedModelProvider`.
The only difference is the last step — instead of building the answer text
itself, it hands the already-verified search/open result to a small agent
deployed on AgentCore Runtime (see `backend/agentcore_app/agent.py` and
`backend/scripts/deploy_agentcore.py`) and asks it to phrase the answer.
AgentCore never sees the case database, never chooses what to search, and
never gets network access to anything but Bedrock — it only turns a fixed
context string into prose.

Credentials are read from the environment by boto3's default chain (the
same AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN already
used by the deploy script); nothing here writes them anywhere.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from botocore.config import Config

from caseapi.ai import draft_composition, revise_selection
from caseapi.ai.contracts import ModelRequest, ModelResult, ToolGatewayLike
from caseapi.ai.selection_text import selection_text_from_context

MAX_SEARCH_HITS = 3
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 30


class AgentCoreClientLike:
    """The one boto3 method this provider needs; lets tests inject a fake."""

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]: ...


def _default_client(region: str) -> AgentCoreClientLike:
    import boto3

    return boto3.client(
        'bedrock-agentcore',
        region_name=region,
        config=Config(connect_timeout=CONNECT_TIMEOUT_SECONDS, read_timeout=READ_TIMEOUT_SECONDS),
    )


class AgentCoreModelProvider:
    """Delegates only answer phrasing to a deployed AgentCore Runtime agent."""

    prompt_version = 'agentcore-chat-v2'

    def __init__(
        self,
        *,
        runtime_arn: str,
        region: str,
        client: AgentCoreClientLike | None = None,
    ) -> None:
        self._runtime_arn = runtime_arn
        self._region = region
        self._client = client or _default_client(region)

    def descriptor(self) -> dict[str, str]:
        return {'provider': 'agentcore', 'model': self._runtime_arn, 'region': self._region}

    def execute(self, request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        if request.intent == 'verify':
            return self._verify(request, tools)
        if request.intent == 'explain':
            return self._explain(request, tools)
        if request.intent == draft_composition.INTENT_DRAFT:
            return self._draft(request, tools)
        if request.intent == revise_selection.INTENT_REVISE:
            return self._revise_selection(request, tools)
        raise ValueError(f'unsupported agentcore intent: {request.intent}')

    def _draft(self, request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        """AgentCore 只寫理由段落；事實與法規原文都由本機已驗證的內容組成。"""
        if not draft_composition.selected_statutes(request):
            return ModelResult(draft_composition.NO_STATUTE_ANSWER)
        opened, evidence_ids = draft_composition.open_selected_statutes(request, tools)
        reasoning = draft_composition.guard_model_reasoning(
            self._invoke(
                draft_composition.AGENTCORE_DRAFT_PROMPT,
                draft_composition.prompt_context(request, opened),
            )
        )
        return ModelResult(
            draft_composition.summary_answer(opened),
            evidence_ids,
            draft_composition.build_blocks(request, opened, reasoning),
        )

    def _verify(self, request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        search = tools.call(
            'search_knowledge',
            {'query': request.content, 'top_k': MAX_SEARCH_HITS, 'document_types': {'statute'}},
        )
        if not search['hits']:
            return ModelResult('本地 r3 快照未找到足夠依據；尚未確認最新法規。')
        opened = tools.call(
            'open_source',
            {'release_id': search['release_id'], 'chunk_id': search['hits'][0]['chunk_id']},
        )
        context = f'{search["release_id"]} 原文：「{opened["quote"]}」'
        answer = self._invoke(request.content, context)
        return ModelResult(answer, (opened['evidence_id'],))

    def _revise_selection(self, request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        selection = revise_selection.read_selection(request, tools)
        if isinstance(selection, ModelResult):
            return selection
        selected, block_id = selection
        candidate = revise_selection.guard_candidate_text(
            self._invoke(
                revise_selection.AGENTCORE_REVISE_PROMPT_PREFIX + request.content, selected
            )
        )
        reasoning = 'AI 已依指示改寫選取範圍，內容尚未經法律覆核，請人工確認後再採用。'
        return revise_selection.build_result(reasoning, candidate, block_id)

    def _explain(self, request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        if request.target is None:
            return ModelResult('請先指定要解釋的案件內容。')
        context_result = tools.call(
            'read_selection_context', {'target': request.target, 'adjacent_blocks': 1}
        )
        selected = selection_text_from_context(context_result)
        if not selected:
            return ModelResult('選取的內容目前沒有值，沒有東西可以解釋。')
        answer = self._invoke(request.content, selected)
        return ModelResult(answer)

    def _invoke(self, prompt: str, context: str) -> str:
        payload = json.dumps({'prompt': prompt, 'context': context}).encode('utf-8')
        response = self._client.invoke_agent_runtime(
            agentRuntimeArn=self._runtime_arn,
            runtimeSessionId=str(uuid.uuid4()) + '-agentcore-session',
            payload=payload,
            qualifier='DEFAULT',
        )
        body = json.loads(response['response'].read())
        return body['response']
