"""Deterministic no-network provider used to prove orchestration contracts."""

from caseapi.ai.contracts import ModelRequest, ModelResult, ToolGatewayLike


class FixedModelProvider:
    prompt_version = 'fixed-chat-v1'

    def descriptor(self) -> dict[str, str]:
        return {'provider': 'fixed', 'model': 'deterministic-v1'}

    def execute(self, request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        if request.intent == 'verify':
            return self._verify(request, tools)
        if request.intent == 'explain':
            return self._explain(request, tools)
        raise ValueError(f'unsupported fixed intent: {request.intent}')

    @staticmethod
    def _verify(request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        search = tools.call(
            'search_knowledge',
            {'query': request.content, 'top_k': 3, 'document_types': {'statute'}},
        )
        if not search['hits']:
            return ModelResult(
                '本地 r3 快照未找到足夠依據；尚未確認最新法規。'
            )
        opened = tools.call(
            'open_source',
            {
                'release_id': search['release_id'],
                'chunk_id': search['hits'][0]['chunk_id'],
            },
        )
        answer = (
            f'已查閱 {search["release_id"]} 原文：「{opened["quote"]}」；'
            '此來源僅證明引文存在且一致，是否支持本案主張仍待判斷。'
        )
        return ModelResult(answer, (opened['evidence_id'],))

    @staticmethod
    def _explain(request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        if request.target is None:
            return ModelResult('請先指定要解釋的案件內容。')
        context = tools.call(
            'read_selection_context',
            {'target': request.target, 'adjacent_blocks': 1},
        )
        target = context['writable_target']
        selected = target.get('selected_text', '')
        return ModelResult(
            f'選取內容：「{selected}」。'
            '固定模型只確認上下文讀取鏈，未作法律判斷。'
        )
