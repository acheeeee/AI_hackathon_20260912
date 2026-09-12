"""`draft` intent on both providers: same tool chain, different phrasing step.

Neither provider may invent a statute. Every block it cites has to come from
an `open_source` call on a chunk the user actually selected (06 §3 規則 14),
and the resulting evidence ids are what the proposal will reference.
"""

import json

import pytest

from caseapi.ai.agentcore_provider import AgentCoreModelProvider
from caseapi.ai.contracts import ModelRequest
from caseapi.ai.fixed_provider import FixedModelProvider

from test_agentcore_provider import FakeAgentCoreClient, FakeToolGateway

CONTEXT = {
    'release_id': 'r3',
    'facts': {'appellant.name': '絕○○○股份有限公司', 'disposition.date': '114-03-01'},
    'statutes': [
        {
            'chunk_id': 'chk_law_14',
            'document_id': 'doc_law',
            'section_id': 'sec_law_14',
            'statute_name': '訴願法',
            'article_key': '14',
            'excerpt': '訴願之提起，應自行政處分達到之次日起三十日內為之。',
        }
    ],
    'appeal_text': '事實：訴願人申請洗錢防制服務業登記遭否准。',
}


def _draft_request(context: dict | None = None) -> ModelRequest:
    return ModelRequest(
        case_id='case_1',
        run_id='run_1',
        thread_id='thread_1',
        message_id='msg_1',
        content='依目前事實與選定法規生成訴願決定書草稿',
        intent='draft',
        target=None,
        context_manifest={},
        context=CONTEXT if context is None else context,
    )


def _opened_tools() -> FakeToolGateway:
    return FakeToolGateway(
        {
            'open_source': {
                'evidence_id': 'evid_1',
                'quote': '訴願之提起，應自行政處分達到之次日起三十日內為之。',
            }
        }
    )


def test_fixed_draft_opens_every_selected_statute_and_returns_blocks() -> None:
    # Arrange
    tools = _opened_tools()
    provider = FixedModelProvider()

    # Act
    result = provider.execute(_draft_request(), tools)

    # Assert
    assert [call[0] for call in tools.calls] == ['open_source']
    assert tools.calls[0][1] == {'release_id': 'r3', 'chunk_id': 'chk_law_14'}
    assert result.evidence_ids == ('evid_1',)
    text = ''.join(block.text for block in result.draft_blocks)
    assert '絕○○○股份有限公司' in text
    assert '訴願法' in text
    assert '訴願之提起' in text
    assert any('evid_1' in block.citations for block in result.draft_blocks)


def test_fixed_draft_without_selected_statutes_returns_no_blocks() -> None:
    tools = FakeToolGateway({})
    provider = FixedModelProvider()

    result = provider.execute(_draft_request({**CONTEXT, 'statutes': []}), tools)

    assert result.draft_blocks == ()
    assert result.evidence_ids == ()
    assert tools.calls == []
    assert '尚未選定法規' in result.answer


def test_agentcore_draft_sends_facts_statutes_and_appeal_text_as_context() -> None:
    # Arrange
    tools = _opened_tools()
    client = FakeAgentCoreClient(answer='本件訴願為有理由，爰依法撤銷原處分。')
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client
    )

    # Act
    result = provider.execute(_draft_request(), tools)

    # Assert
    sent = json.loads(client.invocations[0]['payload'])
    assert '絕○○○股份有限公司' in sent['context']
    assert '訴願法' in sent['context']
    assert '洗錢防制服務業登記' in sent['context']
    assert '訴願之提起' in sent['context']
    reasoning = ''.join(
        block.text for block in result.draft_blocks if block.block_id.startswith('reason')
    )
    assert '本件訴願為有理由' in reasoning
    assert result.evidence_ids == ('evid_1',)


def test_agentcore_draft_without_selected_statutes_does_not_call_agentcore() -> None:
    tools = FakeToolGateway({})
    client = FakeAgentCoreClient(answer='should not be used')
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client
    )

    result = provider.execute(_draft_request({**CONTEXT, 'statutes': []}), tools)

    assert client.invocations == []
    assert result.draft_blocks == ()
    assert '尚未選定法規' in result.answer


@pytest.mark.parametrize(
    'provider',
    [
        FixedModelProvider(),
        AgentCoreModelProvider(
            runtime_arn='arn:aws:...:runtime/demo',
            region='us-west-2',
            client=FakeAgentCoreClient(answer='x'),
        ),
    ],
)
def test_draft_intent_without_context_does_not_invent_one(provider) -> None:
    tools = FakeToolGateway({})

    result = provider.execute(_draft_request({}), tools)

    assert result.draft_blocks == ()
    assert tools.calls == []
