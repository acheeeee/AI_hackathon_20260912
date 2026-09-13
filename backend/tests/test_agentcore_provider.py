"""AgentCoreModelProvider: local tools stay authoritative, AgentCore only phrases."""

import json

import pytest

from caseapi.ai.agentcore_provider import AgentCoreModelProvider
from caseapi.ai.contracts import ModelRequest


class FakeToolGateway:
    """Records every tool call and returns canned, adapter-shaped results."""

    def __init__(self, responses: dict[str, dict]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool: str, arguments: dict) -> dict:
        self.calls.append((tool, arguments))
        return self._responses[tool]


class _FakeStreamingBody:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode('utf-8')

    def read(self) -> bytes:
        return self._raw


class FakeAgentCoreClient:
    """Records the invoke_agent_runtime call and returns a canned agent answer."""

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.invocations: list[dict] = []

    def invoke_agent_runtime(self, **kwargs) -> dict:
        self.invocations.append(kwargs)
        return {'response': _FakeStreamingBody({'response': self._answer, 'status': 'success'})}


def _request(*, intent: str, target: dict | None = None, content: str = '訴願期間多久？') -> ModelRequest:
    return ModelRequest(
        case_id='case_1',
        run_id='run_1',
        thread_id='thread_1',
        message_id='msg_1',
        content=content,
        intent=intent,
        target=target,
        context_manifest={},
    )


def test_verify_sends_real_search_result_as_context_and_returns_agent_answer() -> None:
    # Arrange
    tools = FakeToolGateway(
        {
            'search_knowledge': {
                'release_id': 'r3',
                'hits': [{'chunk_id': 'chk_law_14'}],
            },
            'open_source': {
                'quote': '訴願應於三十日內提起。',
                'evidence_id': 'evid_1',
            },
        }
    )
    client = FakeAgentCoreClient(answer='三十日內要提起訴願。')
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/demo', region='us-west-2', client=client
    )

    # Act
    result = provider.execute(_request(intent='verify'), tools)

    # Assert
    assert result.answer == '三十日內要提起訴願。'
    assert result.evidence_ids == ('evid_1',)
    assert [call[0] for call in tools.calls] == ['search_knowledge', 'open_source']
    sent_payload = json.loads(client.invocations[0]['payload'])
    assert sent_payload['prompt'] == '訴願期間多久？'
    assert '訴願應於三十日內提起。' in sent_payload['context']
    assert client.invocations[0]['agentRuntimeArn'].endswith('runtime/demo')
    assert len(client.invocations[0]['runtimeSessionId']) >= 33


def test_verify_with_no_hits_reports_snapshot_gap_without_calling_agentcore() -> None:
    # Arrange
    tools = FakeToolGateway({'search_knowledge': {'release_id': 'r3', 'hits': []}})
    client = FakeAgentCoreClient(answer='should not be used')
    provider = AgentCoreModelProvider(runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client)

    # Act
    result = provider.execute(_request(intent='verify'), tools)

    # Assert
    assert '未找到足夠依據' in result.answer
    assert result.evidence_ids == ()
    assert [call[0] for call in tools.calls] == ['search_knowledge']
    assert client.invocations == []


def test_explain_sends_selected_text_as_context() -> None:
    # Arrange
    tools = FakeToolGateway(
        {
            'read_selection_context': {
                'writable_target': {'selected_text': '本案已逾期'},
            }
        }
    )
    client = FakeAgentCoreClient(answer='這段話是在說明逾期事實。')
    provider = AgentCoreModelProvider(runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client)
    target = {'kind': 'block_range', 'block_id': 'b1'}

    # Act
    result = provider.execute(
        _request(intent='explain', target=target, content='這段在講什麼？'), tools
    )

    # Assert
    assert result.answer == '這段話是在說明逾期事實。'
    sent_payload = json.loads(client.invocations[0]['payload'])
    assert sent_payload['context'] == '本案已逾期'


def test_explain_reads_fact_field_value_when_target_is_a_fact_field() -> None:
    # Arrange: read_selection_context's writable_target for a fact_field target has
    # no selected_text key (only draft_block targets have one) — the actual value
    # lives in context.field, which the provider must know to look for instead.
    tools = FakeToolGateway(
        {
            'read_selection_context': {
                'writable_target': {'kind': 'fact_field', 'field_path': 'appellant.name'},
                'context': {'field': {'value': '絕○○○股份有限公司', 'origin': 'program'}},
            }
        }
    )
    client = FakeAgentCoreClient(answer='這是本案訴願人的名稱。')
    provider = AgentCoreModelProvider(runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client)
    target = {'kind': 'fact_field', 'resource_id': 'facts', 'field_path': 'appellant.name'}

    # Act
    result = provider.execute(
        _request(intent='explain', target=target, content='這個欄位是什麼意思？'), tools
    )

    # Assert
    assert result.answer == '這是本案訴願人的名稱。'
    sent_payload = json.loads(client.invocations[0]['payload'])
    assert '絕○○○股份有限公司' in sent_payload['context']


def test_explain_on_an_unset_fact_field_does_not_call_agentcore() -> None:
    # Arrange
    tools = FakeToolGateway(
        {
            'read_selection_context': {
                'writable_target': {'kind': 'fact_field', 'field_path': 'appellant.address'},
                'context': {'field': None},
            }
        }
    )
    client = FakeAgentCoreClient(answer='should not be used')
    provider = AgentCoreModelProvider(runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client)
    target = {'kind': 'fact_field', 'resource_id': 'facts', 'field_path': 'appellant.address'}

    # Act
    result = provider.execute(_request(intent='explain', target=target), tools)

    # Assert
    assert client.invocations == []
    assert '沒有值' in result.answer or '沒有東西' in result.answer


def test_explain_without_target_does_not_call_agentcore() -> None:
    # Arrange
    tools = FakeToolGateway({})
    client = FakeAgentCoreClient(answer='should not be used')
    provider = AgentCoreModelProvider(runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client)

    # Act
    result = provider.execute(_request(intent='explain', target=None), tools)

    # Assert
    assert '請先指定' in result.answer
    assert tools.calls == []
    assert client.invocations == []


def test_unsupported_intent_raises_without_touching_tools_or_agentcore() -> None:
    tools = FakeToolGateway({})
    client = FakeAgentCoreClient(answer='should not be used')
    provider = AgentCoreModelProvider(runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client)

    with pytest.raises(ValueError, match='unsupported agentcore intent'):
        provider.execute(_request(intent='regenerate'), tools)

    assert tools.calls == []
    assert client.invocations == []


def test_descriptor_exposes_only_non_secret_identifiers() -> None:
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/demo',
        region='us-west-2',
        client=FakeAgentCoreClient(answer='x'),
    )

    descriptor = provider.descriptor()

    assert descriptor == {
        'provider': 'agentcore',
        'model': 'arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/demo',
        'region': 'us-west-2',
    }
    serialized = json.dumps(descriptor)
    for secret_marker in ('AKIA', 'aws_secret', 'session_token'):
        assert secret_marker not in serialized


def test_agentcore_intake_analysis_uses_fixed_json_prompt_and_parses_response() -> None:
    answer = json.dumps(
        {
            'keywords': '洗錢防制登記、虛擬資產服務、不予登記',
            'disposition_summary': '主管機關以申請書件不完備且逾期未完成補正為由不予登記。',
            'statute_query': '洗錢防制法第6條 洗錢防制登記 虛擬資產服務',
        },
        ensure_ascii=False,
    )
    client = FakeAgentCoreClient(answer=answer)
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:...:runtime/demo', region='us-west-2', client=client
    )

    analysis = provider.analyze_intake(
        appeal_text='訴願書案件事實與理由',
        disposition_text='行政處分函主旨與說明',
    )

    assert analysis.keywords.startswith('洗錢防制登記')
    assert analysis.disposition_summary.endswith('不予登記。')
    assert analysis.statute_query.startswith('洗錢防制法第6條')
    sent = json.loads(client.invocations[0]['payload'])
    assert '只輸出一個 JSON' in sent['prompt']
    assert '訴願書案件事實與理由' not in sent['prompt']
    assert '訴願書案件事實與理由' in sent['context']
    assert '行政處分函主旨與說明' in sent['context']


def test_agentcore_intake_analysis_rejects_malformed_model_output() -> None:
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:...:runtime/demo',
        region='us-west-2',
        client=FakeAgentCoreClient(answer='這不是 JSON'),
    )

    with pytest.raises(ValueError, match='intake analysis'):
        provider.analyze_intake(appeal_text='appeal', disposition_text='disposition')


def test_agentcore_intake_analysis_compacts_an_overlong_generated_query() -> None:
    answer = json.dumps(
        {
            'keywords': '洗錢防制登記、虛擬資產服務、不予登記',
            'disposition_summary': '主管機關以申請書件不完備為由不予登記。',
            'statute_query': (
                '提供虛擬資產服務之事業或人員洗錢防制登記辦法第5條 '
                '洗錢防制法第6條 申請書件不完備 限期補正 交易監控 '
                '外部資料庫 資訊系統委外 雲端服務 私鑰保管 比例原則 營業自由'
            ),
        },
        ensure_ascii=False,
    )
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:...:runtime/demo',
        region='us-west-2',
        client=FakeAgentCoreClient(answer=answer),
    )

    analysis = provider.analyze_intake(appeal_text='appeal', disposition_text='disposition')

    assert len(analysis.statute_query) <= 80
    assert analysis.statute_query.startswith(
        '提供虛擬資產服務之事業或人員洗錢防制登記辦法第5條'
    )
    assert '交易監控' in analysis.statute_query
    assert analysis.statute_query.endswith('比例原則')


def test_agentcore_query_compaction_does_not_hide_a_narrative_marker() -> None:
    answer = json.dumps(
        {
            'keywords': '洗錢防制登記、虛擬資產服務、不予登記',
            'disposition_summary': '主管機關以申請書件不完備為由不予登記。',
            'statute_query': f'{"法規查詢詞" * 20} 訴願人於115年提出申請',
        },
        ensure_ascii=False,
    )
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:...:runtime/demo',
        region='us-west-2',
        client=FakeAgentCoreClient(answer=answer),
    )

    with pytest.raises(ValueError, match='narrative'):
        provider.analyze_intake(appeal_text='appeal', disposition_text='disposition')


@pytest.mark.parametrize(
    'outcome_paraphrase',
    [
        '本件訴願應予駁回。',
        '本案訴願為無理由。',
        '應作成不受理決定。',
        '本件應予駁回。',
        '原處分並無違誤，應予維持。',
        '本案欠缺程序要件，應予不受理。',
    ],
)
def test_agentcore_intake_analysis_blocks_final_outcome_paraphrases(
    outcome_paraphrase: str,
) -> None:
    answer = json.dumps(
        {
            'keywords': '洗錢防制登記、虛擬資產服務、不予登記',
            'disposition_summary': outcome_paraphrase,
            'statute_query': '洗錢防制法第6條 洗錢防制登記',
        },
        ensure_ascii=False,
    )
    provider = AgentCoreModelProvider(
        runtime_arn='arn:aws:...:runtime/demo',
        region='us-west-2',
        client=FakeAgentCoreClient(answer=answer),
    )

    with pytest.raises(ValueError, match='appeal outcome'):
        provider.analyze_intake(appeal_text='appeal', disposition_text='disposition')
