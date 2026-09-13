"""選法規：對 r3 語料做 BM25 搜尋供人工瀏覽，並保存人工挑選的結果。

搜尋本身不寫 evidence／run 事件——這是人工瀏覽候選，不是 AI 工具呼叫
（見 06 §3 規則 14 對 search 與 open 的區分）。之後如果这些法規真的被
拿去當草稿依據，還是要走 `EvidenceToolAdapter.open_source` 才能取得
program-verified 的 evidence，這裡的搜尋結果只是候選，不是證據。

預設 BM25 查詢仍來自訴願書的事實／理由段落；該長字串只留在伺服器內部。
回應中的 query_used／suggested_query 是 intake 產生的精簡人工查詢詞。
"""

import json
import re
import sqlite3
from typing import Any, Protocol
from urllib.parse import urlencode

from caseapi.audit import append_entry
from caseapi.domain.appeal_extraction import extract_case_narrative
from caseapi.ids import new_id
from caseapi.schemas.statute_selection import StatuteSelectionSaveRequest
from caseapi.services import case_repository as repo
from caseapi.services import facts_service
from caseapi.services import resource_service

STATUTE_SELECTION_RESOURCE_ID = 'statute_selection'
DEFAULT_TOP_K = 8
_APPEAL_ROLE = 'appeal'
_STATUTE_QUERY_FIELD = 'analysis.statute_query'
_OFFICIAL_LAW_BASE = 'https://law.moj.gov.tw/LawClass/LawSingle.aspx'
_OFFICIAL_PCODE_BY_STATUTE = {
    '訴願法': 'A0030020',
    '行政院及各級行政機關訴願審議委員會審議規則': 'A0030022',
    '行政執行法': 'A0030023',
    '行政程序法': 'A0030055',
    '行政罰法': 'A0030210',
    '民法': 'B0000001',
    '建築法': 'D0070109',
    '洗錢防制法': 'G0380131',
    '噪音管制法': 'O0030001',
    '空氣污染防制法': 'O0020001',
    '廢棄物清理法': 'O0050001',
}


class SearchHitLike(Protocol):
    release_id: str
    chunk_id: str
    document_id: str
    section_id: str
    excerpt: str
    metadata: dict[str, Any]
    score: float


class StatuteRepositoryLike(Protocol):
    def search(
        self, query: str, *, top_k: int, document_types: set[str] | None
    ) -> list[SearchHitLike]: ...

    def open_section_text(self, section_id: str) -> str: ...


def _default_query(conn: sqlite3.Connection, *, case_id: str) -> str | None:
    row = conn.execute(
        'SELECT extracted_text FROM case_documents WHERE case_id = ? AND document_role = ?'
        ' ORDER BY created_at ASC LIMIT 1',
        (case_id, _APPEAL_ROLE),
    ).fetchone()
    if row is None or not row['extracted_text']:
        return None
    return extract_case_narrative(row['extracted_text'])


def _suggested_query(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    heads: dict[str, dict[str, str]],
) -> str | None:
    fields = facts_service.read_current_fields(conn, case_id=case_id, heads=heads)
    field = fields.get(_STATUTE_QUERY_FIELD) or {}
    value = field.get('value')
    return value.strip() if isinstance(value, str) and value.strip() else None


def search_statutes(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    repository: StatuteRepositoryLike,
    query: str | None,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    explicit_query = query.strip() if query and query.strip() else None
    suggested_query = explicit_query or _suggested_query(
        conn,
        case_id=case_id,
        heads=repo.load_heads(case_row),
    )
    background_query = _default_query(conn, case_id=case_id)
    search_query = explicit_query or background_query or suggested_query
    if not search_query:
        return {'query_used': None, 'suggested_query': None, 'hits': []}

    hits = repository.search(search_query, top_k=top_k, document_types={'statute'})
    return {
        'query_used': suggested_query,
        'suggested_query': suggested_query,
        'hits': [
            _search_hit_payload(
                hit,
                repository=repository,
                human_query=suggested_query,
            )
            for hit in hits
        ],
    }


def _search_hit_payload(
    hit: SearchHitLike,
    *,
    repository: StatuteRepositoryLike,
    human_query: str | None,
) -> dict[str, Any]:
    statute_name = hit.metadata.get('statute_name')
    article_key = hit.metadata.get('article_key')
    full_text = repository.open_section_text(hit.section_id)
    return {
        'chunk_id': hit.chunk_id,
        'document_id': hit.document_id,
        'section_id': hit.section_id,
        'statute_name': statute_name,
        'article_key': article_key,
        'excerpt': hit.excerpt,
        'full_text': full_text,
        'score': hit.score,
        'why_relevant': _why_relevant(
            statute_name=statute_name,
            article_key=article_key,
            human_query=human_query,
            full_text=full_text,
        ),
        'why_relevant_origin': 'rule',
        'why_relevant_provider': None,
        'official_url': _official_url(statute_name, article_key),
        'legal_review_status': 'not_reviewed',
    }


def _why_relevant(
    *,
    statute_name: object,
    article_key: object,
    human_query: str | None,
    full_text: str,
) -> str:
    title = f'{statute_name or "此法規"}第{article_key or "未明"}條'
    matched = _matched_query_terms(human_query, title=title, full_text=full_text)
    if matched:
        terms = '、'.join(f'「{term}」' for term in matched)
        direct_title_match = isinstance(statute_name, str) and statute_name in (human_query or '')
        if direct_title_match:
            return (
                f'查詢中的{terms}與{title}的法規名稱或條文文字直接相符，'
                '因此由 BM25 排入候選；是否適用仍須人工覆核。'
            )
        return (
            f'{title}因與查詢共有{terms}而由 BM25 排入候選；'
            '共同用語不等於法律上相關，請人工核對條文主題後決定是否排除。'
        )
    return (
        f'{title}由 BM25 依完整案件背景排入候選，但在精簡查詢中未辨識到'
        '可直接說明的共同詞；請人工核對或排除，不應只依排名判定適用。'
    )


_RELEVANCE_TERMS = (
    '洗錢防制',
    '虛擬資產服務',
    '登記',
    '補正',
    '比例原則',
    '營業自由',
    '交易監控',
    '資訊系統',
    '逾期',
    '送達',
)


def _matched_query_terms(
    query: str | None, *, title: str, full_text: str
) -> list[str]:
    if not query:
        return []
    candidates = [
        part
        for part in re.split(r'[\s、，,；;：:]+', query)
        if len(part) >= 2
    ]
    candidates.extend(term for term in _RELEVANCE_TERMS if term in query)
    haystack = title + full_text
    matched: list[str] = []
    for term in candidates:
        if term in haystack and term not in matched:
            matched.append(term)
        if len(matched) == 4:
            break
    return matched


def _official_url(statute_name: object, article_key: object) -> str | None:
    if not isinstance(statute_name, str) or not isinstance(article_key, str):
        return None
    pcode = _OFFICIAL_PCODE_BY_STATUTE.get(statute_name)
    if pcode is None or not article_key:
        return None
    return f'{_OFFICIAL_LAW_BASE}?{urlencode({"pcode": pcode, "flno": article_key})}'


def get_selection(
    conn: sqlite3.Connection, *, case_id: str, actor_id: str
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    heads = repo.load_heads(case_row)
    head = heads.get(STATUTE_SELECTION_RESOURCE_ID)
    if head is None:
        return {'selected': []}
    row = resource_service.require_version(
        conn,
        case_id=case_id,
        resource_id=STATUTE_SELECTION_RESOURCE_ID,
        revision_id=head['revision_id'],
    )
    return json.loads(row['content_json'])


def save_selection(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    request: StatuteSelectionSaveRequest,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    repo.assert_case_revision(case_row, request.expected_case_revision)
    heads = repo.load_heads(case_row)
    parent_head = heads.get(STATUTE_SELECTION_RESOURCE_ID)

    content = {'selected': [item.model_dump() for item in request.selected]}
    version = resource_service.save_version(
        conn,
        case_id=case_id,
        resource_id=STATUTE_SELECTION_RESOURCE_ID,
        resource_kind=repo.KIND_STATUTE_SELECTION,
        content=content,
        parent_id=parent_head['revision_id'] if parent_head else None,
        origin=resource_service.ORIGIN_HUMAN,
        actor_id=actor_id,
    )
    next_heads = repo.set_head(
        heads,
        resource_id=STATUTE_SELECTION_RESOURCE_ID,
        kind=repo.KIND_STATUTE_SELECTION,
        revision_id=version['resource_revision'],
        freshness=repo.FRESHNESS_CURRENT,
    )
    mutation_id = new_id('mut')
    case_revision = repo.advance_case(
        conn,
        case_id=case_id,
        expected_revision=request.expected_case_revision,
        heads=next_heads,
        actor_id=actor_id,
        mutation_id=mutation_id,
    )
    append_entry(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action='statute_selection.saved',
        mutation_id=mutation_id,
        after_refs={
            'resource_revision': version['resource_revision'],
            'selected_count': len(content['selected']),
        },
        reason=request.reason,
    )
    return {'case_revision': case_revision, **content}
