"""Case-scoped model tools with server-generated activity and evidence records.

Tool execution never trusts a model to report what happened. Each call writes
its own start/result/failure events. Search results remain candidates; only a
successful ``open_source`` creates a verified evidence record.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from pydantic import TypeAdapter

from caseapi.clock import now_iso
from caseapi.db.connection import connect, transaction
from caseapi.evidence.repository import OpenedSource, SearchHit
from caseapi.errors import revision_conflict
from caseapi.ids import new_id
from caseapi.schemas.evidence import ASSESSED_BY_PROGRAM, SUPPORT_UNKNOWN
from caseapi.schemas.target import DraftBlockTarget, FactFieldTarget, TargetRef
from caseapi.services import case_repository, resource_service, run_service

MAX_ADJACENT_BLOCKS = 5
MAX_SEARCH_RESULTS = 20
_TARGET_ADAPTER = TypeAdapter(TargetRef)


class EvidenceRepositoryLike(Protocol):
    release_id: str

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        document_types: set[str] | None = None,
        exclude_case_family_id: str | None = None,
    ) -> list[SearchHit]: ...

    def open_source(self, chunk_id: str) -> OpenedSource: ...


class EvidenceToolAdapter:
    """Execute the four B2 tools against one actor and one immutable release."""

    def __init__(
        self,
        *,
        db_path: Path,
        actor_id: str,
        repository: EvidenceRepositoryLike,
        id_factory: Callable[[str], str] = new_id,
    ) -> None:
        self._db_path = db_path
        self._actor_id = actor_id
        self._repository = repository
        self._id_factory = id_factory

    def read_case_resource(
        self,
        *,
        case_id: str,
        run_id: str,
        resource_id: str,
        resource_revision: str,
    ) -> dict[str, Any]:
        tool = 'read_case_resource'
        inputs = {
            'resource_id': resource_id,
            'resource_revision': resource_revision,
        }
        with self._activity(case_id, run_id, tool, inputs) as activity:
            conn = connect(self._db_path)
            try:
                with transaction(conn):
                    result = _read_resource_payload(
                        conn,
                        case_id=case_id,
                        actor_id=self._actor_id,
                        resource_id=resource_id,
                        resource_revision=resource_revision,
                    )
                    self._complete_in_transaction(
                        conn,
                        case_id=case_id,
                        run_id=run_id,
                        tool=tool,
                        tool_call_id=activity[0],
                        started=activity[1],
                        payload=inputs,
                    )
                return result
            finally:
                conn.close()

    def read_selection_context(
        self,
        *,
        case_id: str,
        run_id: str,
        target: dict[str, Any],
        adjacent_blocks: int = 1,
    ) -> dict[str, Any]:
        tool = 'read_selection_context'
        inputs = {
            'resource_id': target.get('resource_id'),
            'resource_revision': target.get('resource_revision'),
            'adjacent_blocks': adjacent_blocks,
        }
        with self._activity(case_id, run_id, tool, inputs) as activity:
            if not isinstance(adjacent_blocks, int) or not (
                0 <= adjacent_blocks <= MAX_ADJACENT_BLOCKS
            ):
                raise ValueError(
                    f'adjacent_blocks must be between 0 and {MAX_ADJACENT_BLOCKS}'
                )
            parsed = _TARGET_ADAPTER.validate_python(target)
            conn = connect(self._db_path)
            try:
                with transaction(conn):
                    result = _read_selection_payload(
                        conn,
                        case_id=case_id,
                        actor_id=self._actor_id,
                        target=parsed,
                        adjacent_blocks=adjacent_blocks,
                    )
                    self._complete_in_transaction(
                        conn,
                        case_id=case_id,
                        run_id=run_id,
                        tool=tool,
                        tool_call_id=activity[0],
                        started=activity[1],
                        payload={
                            'context_item_count': _context_item_count(result['context'])
                        },
                    )
                return result
            finally:
                conn.close()

    def search_knowledge(
        self,
        *,
        case_id: str,
        run_id: str,
        query: str,
        top_k: int = 5,
        document_types: set[str] | None = None,
        exclude_case_family_id: str | None = None,
    ) -> dict[str, Any]:
        tool = 'search_knowledge'
        inputs = {
            'query': query,
            'top_k': top_k,
            'document_types': sorted(document_types) if document_types else None,
            'exclude_case_family_id': exclude_case_family_id,
            'release_id': self._repository.release_id,
        }
        with self._activity(case_id, run_id, tool, inputs) as activity:
            if not isinstance(top_k, int) or not 1 <= top_k <= MAX_SEARCH_RESULTS:
                raise ValueError(f'top_k must be between 1 and {MAX_SEARCH_RESULTS}')
            hits = self._repository.search(
                query,
                top_k=top_k,
                document_types=document_types,
                exclude_case_family_id=exclude_case_family_id,
            )
            result = {
                'classification': 'search_hit',
                'release_id': self._repository.release_id,
                'hit_count': len(hits),
                'hits': [_search_hit_payload(hit) for hit in hits],
                'gap': None if hits else 'no_matches_in_snapshot',
                'temporal_status': 'snapshot_only',
            }
            self._complete(
                case_id=case_id,
                run_id=run_id,
                tool=tool,
                tool_call_id=activity[0],
                started=activity[1],
                payload={
                    'classification': 'search_hit',
                    'release_id': self._repository.release_id,
                    'hit_count': len(hits),
                },
            )
            return result

    def open_source(
        self,
        *,
        case_id: str,
        run_id: str,
        release_id: str,
        chunk_id: str,
    ) -> dict[str, Any]:
        tool = 'open_source'
        inputs = {'release_id': release_id, 'chunk_id': chunk_id}
        with self._activity(case_id, run_id, tool, inputs) as activity:
            source, expected_hash = _verified_source(
                self._repository, release_id=release_id, chunk_id=chunk_id
            )
            evidence_id = self._id_factory('evid')
            source_ref = _source_ref(source)
            conn = connect(self._db_path)
            try:
                with transaction(conn):
                    opened_event_id, verification = _store_opened_evidence(
                        conn,
                        case_id=case_id,
                        actor_id=self._actor_id,
                        run_id=run_id,
                        tool_call_id=activity[0],
                        evidence_id=evidence_id,
                        source=source,
                        source_ref=source_ref,
                        quote_hash=expected_hash,
                    )
                    self._complete_in_transaction(
                        conn,
                        case_id=case_id,
                        run_id=run_id,
                        tool=tool,
                        tool_call_id=activity[0],
                        started=activity[1],
                        payload={
                            'classification': 'opened_source',
                            'evidence_id': evidence_id,
                            'opened_event_id': opened_event_id,
                        },
                    )
                return _opened_source_payload(
                    source, evidence_id, source_ref, verification
                )
            finally:
                conn.close()

    @contextmanager
    def _activity(
        self,
        case_id: str,
        run_id: str,
        tool: str,
        inputs: dict[str, Any],
    ) -> Iterator[tuple[str, float]]:
        tool_call_id, started = self._start(
            case_id=case_id, run_id=run_id, tool=tool, inputs=inputs
        )
        try:
            yield tool_call_id, started
        except Exception as exc:
            self._fail(case_id, run_id, tool, tool_call_id, started, exc)
            raise

    def _start(
        self,
        *,
        case_id: str,
        run_id: str,
        tool: str,
        inputs: dict[str, Any],
    ) -> tuple[str, float]:
        tool_call_id = self._id_factory('tool')
        started = time.monotonic()
        conn = connect(self._db_path)
        try:
            with transaction(conn):
                run = run_service.get_run(
                    conn,
                    case_id=case_id,
                    actor_id=self._actor_id,
                    run_id=run_id,
                )
                if run['state'] != 'running':
                    raise revision_conflict(
                        '只有 running run 可以執行工具', {'state': run['state']}
                    )
                run_service.append_event(
                    conn,
                    case_id=case_id,
                    actor_id=self._actor_id,
                    run_id=run_id,
                    event_type='tool.started',
                    tool_call_id=tool_call_id,
                    payload={'tool': tool, 'inputs': inputs},
                )
        finally:
            conn.close()
        return tool_call_id, started

    def _complete(
        self,
        *,
        case_id: str,
        run_id: str,
        tool: str,
        tool_call_id: str,
        started: float,
        payload: dict[str, Any],
    ) -> None:
        conn = connect(self._db_path)
        try:
            with transaction(conn):
                self._complete_in_transaction(
                    conn,
                    case_id=case_id,
                    run_id=run_id,
                    tool=tool,
                    tool_call_id=tool_call_id,
                    started=started,
                    payload=payload,
                )
        finally:
            conn.close()

    def _complete_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        case_id: str,
        run_id: str,
        tool: str,
        tool_call_id: str,
        started: float,
        payload: dict[str, Any],
    ) -> None:
        run_service.append_event(
            conn,
            case_id=case_id,
            actor_id=self._actor_id,
            run_id=run_id,
            event_type='tool.completed',
            tool_call_id=tool_call_id,
            payload={
                'tool': tool,
                'duration_ms': _duration_ms(started),
                **payload,
            },
        )

    def _fail(
        self,
        case_id: str,
        run_id: str,
        tool: str,
        tool_call_id: str,
        started: float,
        exc: Exception,
    ) -> None:
        conn = connect(self._db_path)
        try:
            with transaction(conn):
                run_service.append_event(
                    conn,
                    case_id=case_id,
                    actor_id=self._actor_id,
                    run_id=run_id,
                    event_type='tool.failed',
                    tool_call_id=tool_call_id,
                    payload={
                        'tool': tool,
                        'duration_ms': _duration_ms(started),
                        'error_type': type(exc).__name__,
                    },
                )
        finally:
            conn.close()


def _read_resource_payload(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    resource_id: str,
    resource_revision: str,
) -> dict[str, Any]:
    case = case_repository.require_case(conn, case_id=case_id, actor_id=actor_id)
    row = resource_service.require_version(
        conn,
        case_id=case_id,
        resource_id=resource_id,
        revision_id=resource_revision,
    )
    head = case_repository.load_heads(case).get(resource_id)
    is_head = bool(head and head['revision_id'] == resource_revision)
    return {
        'classification': 'case_resource',
        **resource_service.row_to_payload(
            row,
            freshness=head.get('freshness') if is_head else None,
            is_head=is_head,
        ),
    }


def _read_selection_payload(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    target: Any,
    adjacent_blocks: int,
) -> dict[str, Any]:
    case_repository.require_case(conn, case_id=case_id, actor_id=actor_id)
    row = resource_service.require_version(
        conn,
        case_id=case_id,
        resource_id=target.resource_id,
        revision_id=target.resource_revision,
    )
    context = _selection_context(
        json.loads(row['content_json']),
        target=target,
        adjacent_blocks=adjacent_blocks,
    )
    return {
        'classification': 'selection_context',
        'resource_id': target.resource_id,
        'resource_revision': target.resource_revision,
        'writable_target': target.model_dump(),
        'context': context,
    }


def _verified_source(
    repository: EvidenceRepositoryLike, *, release_id: str, chunk_id: str
) -> tuple[OpenedSource, str]:
    if release_id != repository.release_id:
        raise ValueError('requested release does not match the configured release')
    source = repository.open_source(chunk_id)
    if (
        source.release_id != release_id
        or source.source_exists is not True
        or source.quote_matches is not True
    ):
        raise ValueError('opened source was not verified by the repository')
    expected_hash = hashlib.sha256(source.quote_text.encode('utf-8')).hexdigest()
    if source.content_hash != expected_hash:
        raise ValueError('opened source content hash does not match its quote')
    return source, expected_hash


def _store_opened_evidence(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    run_id: str,
    tool_call_id: str,
    evidence_id: str,
    source: OpenedSource,
    source_ref: dict[str, Any],
    quote_hash: str,
) -> tuple[str, dict[str, Any]]:
    event = run_service.append_event(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        run_id=run_id,
        event_type='source.opened',
        tool_call_id=tool_call_id,
        payload=_opened_event_payload(source, evidence_id),
    )
    opened_event_id = f'{run_id}:{event["sequence"]}'
    verification = _verification_payload(source, opened_event_id)
    _insert_evidence(
        conn,
        case_id=case_id,
        run_id=run_id,
        evidence_id=evidence_id,
        source_ref=source_ref,
        source=source,
        quote_hash=quote_hash,
        verification=verification,
    )
    return opened_event_id, verification


def _insert_evidence(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    run_id: str,
    evidence_id: str,
    source_ref: dict[str, Any],
    source: OpenedSource,
    quote_hash: str,
    verification: dict[str, Any],
) -> None:
    conn.execute(
        'INSERT INTO evidence_records (id, case_id, run_id, source_ref_json, quote,'
        ' quote_hash, verification_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (
            evidence_id,
            case_id,
            run_id,
            _json(source_ref),
            source.quote_text,
            quote_hash,
            _json(verification),
            now_iso(),
        ),
    )


def _opened_event_payload(source: OpenedSource, evidence_id: str) -> dict[str, Any]:
    return {
        'classification': 'opened_source',
        'evidence_id': evidence_id,
        'release_id': source.release_id,
        'chunk_id': source.chunk_id,
        'document_id': source.document_id,
        'section_id': source.section_id,
    }


def _verification_payload(
    source: OpenedSource, opened_event_id: str
) -> dict[str, Any]:
    return {
        'source_exists': source.source_exists,
        'quote_matches': source.quote_matches,
        'support_status': SUPPORT_UNKNOWN,
        'assessed_by': ASSESSED_BY_PROGRAM,
        'temporal_status': source.temporal_status,
        'opened_event_id': opened_event_id,
    }


def _opened_source_payload(
    source: OpenedSource,
    evidence_id: str,
    source_ref: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    return {
        'classification': 'opened_source',
        'evidence_id': evidence_id,
        'source_ref': source_ref,
        'quote': source.quote_text,
        **verification,
        'source_file': source.source_file,
        'source_sha256': source.source_sha256,
        'section_id': source.section_id,
        'metadata': dict(source.metadata),
    }


def _selection_context(
    content: dict[str, Any], *, target: Any, adjacent_blocks: int
) -> dict[str, Any]:
    if isinstance(target, DraftBlockTarget):
        blocks = content.get('blocks', [])
        selected_index = next(
            (
                index
                for index, block in enumerate(blocks)
                if block.get('block_id') == target.block_id
            ),
            None,
        )
        if selected_index is None:
            raise ValueError('selected block does not exist in the frozen resource')
        selected = blocks[selected_index]
        actual = selected.get('text', '')[target.char_start:target.char_end]
        if actual != target.selected_text:
            raise ValueError('selection does not match the frozen resource')
        start = max(0, selected_index - adjacent_blocks)
        end = min(len(blocks), selected_index + adjacent_blocks + 1)
        return {'blocks': blocks[start:end]}
    if isinstance(target, FactFieldTarget):
        return {'field': content.get('fields', {}).get(target.field_path)}
    return {'resource': content}


def _context_item_count(context: dict[str, Any]) -> int:
    if 'blocks' in context:
        return len(context['blocks'])
    return 1


def _search_hit_payload(hit: SearchHit) -> dict[str, Any]:
    return {
        'release_id': hit.release_id,
        'chunk_id': hit.chunk_id,
        'document_id': hit.document_id,
        'section_id': hit.section_id,
        'document_type': hit.document_type,
        'case_family_id': hit.case_family_id,
        'excerpt': hit.excerpt,
        'source_spans': [dict(span) for span in hit.source_spans],
        'metadata': dict(hit.metadata),
        'score': hit.score,
        'index_eligible': hit.index_eligible,
    }


def _source_ref(source: OpenedSource) -> dict[str, Any]:
    extraction_versions = {
        str(span.get('extraction_version'))
        for span in source.source_spans
        if span.get('extraction_version') is not None
    }
    if len(extraction_versions) != 1:
        raise ValueError('opened source must use exactly one extraction version')
    spans = [
        {
            'page': span['page'],
            'line': span['line'],
            'char_start': span['char_start'],
            'char_end': span['char_end'],
        }
        for span in source.source_spans
    ]
    return {
        'kb_release_id': source.release_id,
        'document_id': source.document_id,
        'extraction_version': extraction_versions.pop(),
        'source_spans': spans,
        'url': None,
        'retrieved_at': None,
        'snapshot_id': None,
        'content_hash': source.content_hash,
    }


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
