"""選法規：對 r3 語料做 BM25 搜尋供人工瀏覽，並保存人工挑選的結果。

搜尋本身不寫 evidence／run 事件——這是人工瀏覽候選，不是 AI 工具呼叫
（見 06 §3 規則 14 對 search 與 open 的區分）。之後如果这些法規真的被
拿去當草稿依據，還是要走 `EvidenceToolAdapter.open_source` 才能取得
program-verified 的 evidence，這裡的搜尋結果只是候選，不是證據。

預設查詢字串來自訴願書的事實／理由段落，不是整份文件、也不是憑空生成；
沒有訴願書全文就沒有預設查詢，回傳空結果，不亂猜。
"""

import json
import sqlite3
from typing import Any, Protocol

from caseapi.audit import append_entry
from caseapi.domain.appeal_extraction import extract_case_narrative
from caseapi.ids import new_id
from caseapi.schemas.statute_selection import StatuteSelectionSaveRequest
from caseapi.services import case_repository as repo
from caseapi.services import resource_service

STATUTE_SELECTION_RESOURCE_ID = 'statute_selection'
DEFAULT_TOP_K = 8
_APPEAL_ROLE = 'appeal'


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


def _default_query(conn: sqlite3.Connection, *, case_id: str) -> str | None:
    row = conn.execute(
        'SELECT extracted_text FROM case_documents WHERE case_id = ? AND document_role = ?'
        ' ORDER BY created_at ASC LIMIT 1',
        (case_id, _APPEAL_ROLE),
    ).fetchone()
    if row is None or not row['extracted_text']:
        return None
    return extract_case_narrative(row['extracted_text'])


def search_statutes(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    repository: StatuteRepositoryLike,
    query: str | None,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    query_used = query if query else _default_query(conn, case_id=case_id)
    if not query_used:
        return {'query_used': None, 'hits': []}

    hits = repository.search(query_used, top_k=top_k, document_types={'statute'})
    return {
        'query_used': query_used,
        'hits': [
            {
                'chunk_id': hit.chunk_id,
                'document_id': hit.document_id,
                'section_id': hit.section_id,
                'statute_name': hit.metadata.get('statute_name'),
                'article_key': hit.metadata.get('article_key'),
                'excerpt': hit.excerpt,
                'score': hit.score,
            }
            for hit in hits
        ],
    }


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
