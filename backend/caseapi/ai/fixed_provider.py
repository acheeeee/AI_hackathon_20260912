"""Deterministic no-network provider used to prove orchestration contracts."""

from caseapi.ai import draft_composition, intake_analysis, revise_selection
from caseapi.ai.contracts import ModelRequest, ModelResult, ToolGatewayLike
from caseapi.ai.selection_text import selection_text_from_context

FIXED_REASONING = (
    '固定模型只依上列事實與已核對原文的法規排版生成本草稿，未作任何法律判斷，'
    '也未認定本件應否受理或有無理由；請人工覆核並改寫後再採用。'
)


class FixedModelProvider:
    prompt_version = 'fixed-chat-v1'

    def descriptor(self) -> dict[str, str]:
        return {'provider': 'fixed', 'model': 'deterministic-v1'}

    def analyze_intake(
        self, *, appeal_text: str, disposition_text: str | None
    ) -> intake_analysis.IntakeAnalysis | None:
        return intake_analysis.fixed_intake_analysis(
            appeal_text=appeal_text, disposition_text=disposition_text
        )

    def execute(self, request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        if request.intent == 'verify':
            return self._verify(request, tools)
        if request.intent == 'explain':
            return self._explain(request, tools)
        if request.intent == draft_composition.INTENT_DRAFT:
            return self._draft(request, tools)
        if request.intent == revise_selection.INTENT_REVISE:
            return self._revise_selection(request, tools)
        raise ValueError(f'unsupported fixed intent: {request.intent}')

    @staticmethod
    def _draft(request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        if not draft_composition.selected_statutes(request):
            return ModelResult(draft_composition.NO_STATUTE_ANSWER)
        opened, evidence_ids = draft_composition.open_selected_statutes(request, tools)
        return ModelResult(
            draft_composition.summary_answer(opened),
            evidence_ids,
            draft_composition.build_blocks(request, opened, FIXED_REASONING),
        )

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
    def _revise_selection(request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        selection = revise_selection.read_selection(request, tools)
        if isinstance(selection, ModelResult):
            return selection
        selected, block_id = selection
        candidate = revise_selection.guard_candidate_text(
            f'{selected}（固定模型收到指示「{request.content}」，'
            '僅示範選取→候選→提案鏈路，未做實際文字修改）'
        )
        reasoning = (
            '固定模型只證明選取內容可讀回並轉成候選提案，未作任何用語或法律判斷；'
            '請人工覆核後再採用。'
        )
        return revise_selection.build_result(reasoning, candidate, block_id)

    @staticmethod
    def _explain(request: ModelRequest, tools: ToolGatewayLike) -> ModelResult:
        if request.target is None:
            return ModelResult('請先指定要解釋的案件內容。')
        context = tools.call(
            'read_selection_context',
            {'target': request.target, 'adjacent_blocks': 1},
        )
        selected = selection_text_from_context(context)
        if not selected:
            return ModelResult('選取的內容目前沒有值，沒有東西可以解釋。')
        return ModelResult(
            f'選取內容：「{selected}」。'
            '固定模型只確認上下文讀取鏈，未作法律判斷。'
        )
