"""`draft` intent 中兩個 provider 共用的部分。

只有「理由段落怎麼寫」由各自的模型決定（固定模型給一句誠實的佔位說明，
AgentCore 才真的生成文字）；要開哪些法規、開出來的原文怎麼排進區塊、
citations 放哪些 evidence id，兩邊必須一模一樣，否則換 provider 就等於
換了一份草稿的依據，那是 06 §3 規則 15 想擋掉的事。

法規來源只有一個：人工在「選法規」面板挑選並儲存的 chunk。這裡不另外
搜尋、不補法規，也不把沒開過原文的法條寫進草稿——沒選法規就明說不生成
（見 06 §3 規則 14：搜尋是候選，open_source 才是證據）。
"""

from __future__ import annotations

from typing import Any

from caseapi.ai.contracts import GeneratedBlock, ModelRequest, ToolGatewayLike
from caseapi.domain.fact_fields import fact_field_label

INTENT_DRAFT = 'draft'
NO_STATUTE_ANSWER = (
    '尚未選定法規，因此沒有生成草稿。請先在「選法規」挑選並儲存要引用的條文，'
    '再重新產生草稿。'
)
FACT_BLOCK_ID = 'fact-1'
STATUTE_BLOCK_ID = 'statute-1'
REASON_BLOCK_ID = 'reason-1'
MAX_APPEAL_TEXT_CHARS = 2000


def selected_statutes(request: ModelRequest) -> list[dict[str, Any]]:
    return list((request.context or {}).get('statutes') or [])


def open_selected_statutes(
    request: ModelRequest, tools: ToolGatewayLike
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """逐一開啟已選法規的原文；quote 與 evidence id 都由工具層產生。"""
    release_id = (request.context or {}).get('release_id')
    opened = [
        {
            **statute,
            **_open_one(tools, release_id=release_id, chunk_id=statute['chunk_id']),
        }
        for statute in selected_statutes(request)
    ]
    return opened, tuple(item['evidence_id'] for item in opened)


def build_blocks(
    request: ModelRequest, opened: list[dict[str, Any]], reasoning: str
) -> tuple[GeneratedBlock, ...]:
    evidence_ids = tuple(item['evidence_id'] for item in opened)
    return (
        GeneratedBlock(FACT_BLOCK_ID, _fact_block_text(request)),
        GeneratedBlock(STATUTE_BLOCK_ID, _statute_block_text(opened), evidence_ids),
        GeneratedBlock(REASON_BLOCK_ID, reasoning, evidence_ids),
    )


def summary_answer(opened: list[dict[str, Any]]) -> str:
    names = '、'.join(_statute_title(item) for item in opened)
    return (
        f'已依 {len(opened)} 項選定法規（{names}）與目前事實生成草稿提案；'
        '提案尚未採用，正文不會因此改變。'
    )


def prompt_context(request: ModelRequest, opened: list[dict[str, Any]]) -> str:
    """送給線上模型的 context：全部是本機已驗證過的內容，不含案件 DB 連線。"""
    sections = [
        f'【目前事實】\n{_fact_block_text(request)}',
        f'【已選定並核對原文的法規】\n{_statute_block_text(opened)}',
    ]
    appeal_text = _appeal_text(request)
    if appeal_text:
        sections.append(f'【訴願書原文（節錄）】\n{appeal_text}')
    return '\n\n'.join(sections)


def _open_one(
    tools: ToolGatewayLike, *, release_id: str | None, chunk_id: str
) -> dict[str, Any]:
    opened = tools.call('open_source', {'release_id': release_id, 'chunk_id': chunk_id})
    return {'quote': opened['quote'], 'evidence_id': opened['evidence_id']}


def _fact_block_text(request: ModelRequest) -> str:
    facts = (request.context or {}).get('facts') or {}
    lines = [
        f'{fact_field_label(path)}：{value}'
        for path, value in sorted(facts.items())
        if value is not None
    ]
    if not lines:
        return '事實：目前沒有已確認的事實欄位，待人工補充。'
    return '事實：\n' + '\n'.join(lines)


def _statute_block_text(opened: list[dict[str, Any]]) -> str:
    lines = [f'{_statute_title(item)}：「{item["quote"]}」' for item in opened]
    return '依據：\n' + '\n'.join(lines)


def _statute_title(statute: dict[str, Any]) -> str:
    return f'{statute.get("statute_name")}第{statute.get("article_key")}條'


def _appeal_text(request: ModelRequest) -> str:
    text = (request.context or {}).get('appeal_text') or ''
    return text[:MAX_APPEAL_TEXT_CHARS]
