"""`revise_selection` intent on both providers: same tool/guard chain, different phrasing step.

Mirrors test_draft_intent_providers.py's pattern -- provider.execute() called
directly against a fake tool gateway (and a fake AgentCore client), no HTTP
or database involved. This is where the safety gate (candidate text must not
smuggle in an authority/outcome conclusion) is proven, since a hand-rolled
fake ModelProvider in the HTTP-level tests would bypass the real guard code
entirely and prove nothing about it.
"""

import json

import pytest

from caseapi.ai.agentcore_provider import AgentCoreModelProvider
from caseapi.ai.contracts import ModelRequest
from caseapi.ai.fixed_provider import FixedModelProvider

from test_agentcore_provider import FakeAgentCoreClient, FakeToolGateway

BLOCK_ID = 'reason-1'
SELECTED_TEXT = '原處分機關認事用法並無違誤'


def _revise_request(content: str = '把這一句改得更正式') -> ModelRequest:
    return ModelRequest(
        case_id='case_1',
        run_id='run_1',
        thread_id='thread_1',
        message_id='msg_1',
        content=content,
        intent='revise_selection',
        target={'kind': 'draft_block', 'block_id': BLOCK_ID},
        context_manifest={},
    )


def _selection_tools(selected_text: str = SELECTED_TEXT) -> FakeToolGateway:
    return FakeToolGateway(
        {'read_selection_context': {'writable_target': {'selected_text': selected_text}}}
    )


def test_fixed_revise_selection_echoes_the_instruction_without_rewriting_the_text() -> None:
    provider = FixedModelProvider()

    result = provider.execute(_revise_request('改得更正式一點'), _selection_tools())

    candidate = result.draft_blocks[0]
    assert candidate.block_id == BLOCK_ID
    assert SELECTED_TEXT in candidate.text
    assert '改得更正式一點' in candidate.text


def test_fixed_revise_selection_without_target_does_not_read_the_selection() -> None:
    provider = FixedModelProvider()
    request = ModelRequest(**{**_revise_request().__dict__, 'target': None})

    result = provider.execute(request, FakeToolGateway({}))

    assert result.draft_blocks == ()
    assert '選取' in result.answer


def test_agentcore_revise_selection_sends_the_instruction_and_selected_text() -> None:
    tools = _selection_tools()
    client = FakeAgentCoreClient(answer='原處分機關之認事用法，核無違誤之處。')
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client
    )

    result = provider.execute(_revise_request('改得更正式一點'), tools)

    sent = json.loads(client.invocations[0]['payload'])
    assert sent['context'] == SELECTED_TEXT
    assert '改得更正式一點' in sent['prompt']
    assert '不得改變原意以外的事實' in sent['prompt']
    assert result.draft_blocks[0].text == '原處分機關之認事用法，核無違誤之處。'


@pytest.mark.parametrize(
    'unsafe_answer',
    [
        '本訴願駁回',
        '本件訴願為有理由，原處分應予撤銷。',
        '訴願不受理',
    ],
)
def test_agentcore_revise_selection_blocks_a_candidate_with_an_unsafe_conclusion(
    unsafe_answer: str,
) -> None:
    tools = _selection_tools()
    client = FakeAgentCoreClient(answer=unsafe_answer)
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client
    )

    result = provider.execute(_revise_request('寫成不受理'), tools)

    candidate = result.draft_blocks[0].text
    assert unsafe_answer not in candidate
    assert '阻擋' in candidate
