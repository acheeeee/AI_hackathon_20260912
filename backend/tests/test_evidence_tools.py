"""B2 server-side tool adapters and the verified evidence write path."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caseapi.db.connection import connect, transaction
from caseapi.evidence.repository import OpenedSource, SearchHit
from caseapi.services import proposal_service, run_service
from caseapi.tools.evidence_tools import EvidenceToolAdapter

from conftest import block_target, create_case, create_draft


class FakeEvidenceRepository:
    release_id = 'r3'

    def __init__(self) -> None:
        self.opened = OpenedSource(
            release_id='r3',
            chunk_id='chk_law_14',
            document_id='doc_law',
            section_id='sec_law_14',
            quote_text='訴願應於三十日內提起。',
            source_spans=(
                {
                    'document_id': 'doc_law',
                    'extraction_version': 'ext-2.0',
                    'page': 1,
                    'line': 1,
                    'char_start': 0,
                    'char_end': 11,
                },
            ),
            source_file='data/raw/相關法規/訴願法.pdf',
            source_sha256='law-sha',
            content_hash=hashlib.sha256(
                '訴願應於三十日內提起。'.encode('utf-8')
            ).hexdigest(),
            source_exists=True,
            quote_matches=True,
            temporal_status='snapshot_only',
            metadata={'statute_name': '訴願法', 'article_key': '14'},
        )

    def search(self, query: str, **_: object) -> list[SearchHit]:
        if query == '沒有結果':
            return []
        return [
            SearchHit(
                release_id='r3',
                chunk_id='chk_law_14',
                document_id='doc_law',
                section_id='sec_law_14',
                document_type='statute',
                case_family_id=None,
                excerpt='訴願應於三十日內提起。',
                source_spans=self.opened.source_spans,
                metadata=self.opened.metadata,
                score=3.5,
                index_eligible=True,
            )
        ]

    def open_source(self, chunk_id: str) -> OpenedSource:
        if chunk_id == 'missing':
            raise KeyError('unknown chunk')
        return replace(self.opened, chunk_id=chunk_id)


def _running_run(db_path: Path, case_id: str) -> str:
    conn = connect(db_path)
    try:
        with transaction(conn):
            case_revision = conn.execute(
                'SELECT case_revision FROM cases WHERE id = ?',
                (case_id,),
            ).fetchone()['case_revision']
            run = run_service.create_run(
                conn,
                case_id=case_id,
                actor_id='actor_test',
                kind='chat',
                expected_case_revision=case_revision,
                context_manifest={
                    'case_revision': case_revision,
                    'kb_release_id': 'r3',
                },
                prompt_version='fake-v1',
                provider_config={'provider': 'fixed', 'model': 'deterministic-v1'},
                job_kind='chat.run',
                input_refs={'message_id': 'msg_test'},
            )
            run_service.start_run(
                conn,
                case_id=case_id,
                actor_id='actor_test',
                run_id=run['run_id'],
                lease_until='2026-09-12T01:00:00.000Z',
            )
        return run['run_id']
    finally:
        conn.close()


def _adapter(settings, *, id_factory=None) -> EvidenceToolAdapter:
    kwargs = {'id_factory': id_factory} if id_factory is not None else {}
    return EvidenceToolAdapter(
        db_path=settings.db_path,
        actor_id=settings.actor_id,
        repository=FakeEvidenceRepository(),
        **kwargs,
    )


def _event_types(db_path: Path, run_id: str) -> list[str]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            'SELECT event_type FROM run_events WHERE run_id = ? ORDER BY sequence',
            (run_id,),
        ).fetchall()
        return [row['event_type'] for row in rows]
    finally:
        conn.close()


def test_search_records_candidates_without_claiming_sources_were_opened(
    client: TestClient, settings
) -> None:
    case_id = create_case(client)
    run_id = _running_run(settings.db_path, case_id)

    result = _adapter(settings).search_knowledge(
        case_id=case_id,
        run_id=run_id,
        query='訴願期限',
        top_k=3,
        document_types={'statute'},
    )

    assert result['classification'] == 'search_hit'
    assert result['hit_count'] == 1
    assert result['hits'][0]['chunk_id'] == 'chk_law_14'
    assert _event_types(settings.db_path, run_id) == [
        'run.started',
        'tool.started',
        'tool.completed',
    ]
    conn = connect(settings.db_path)
    try:
        assert conn.execute('SELECT COUNT(*) FROM evidence_records').fetchone()[0] == 0
    finally:
        conn.close()


def test_open_source_stores_program_verified_evidence_and_open_event(
    client: TestClient, settings
) -> None:
    case_id = create_case(client)
    run_id = _running_run(settings.db_path, case_id)

    result = _adapter(settings).open_source(
        case_id=case_id,
        run_id=run_id,
        release_id='r3',
        chunk_id='chk_law_14',
    )

    assert result['classification'] == 'opened_source'
    conn = connect(settings.db_path)
    try:
        evidence = proposal_service.read_evidence(
            conn,
            case_id=case_id,
            actor_id='actor_test',
            evidence_id=result['evidence_id'],
        )
    finally:
        conn.close()
    assert evidence['source_exists'] is True
    assert evidence['quote_matches'] is True
    assert evidence['assessed_by'] == 'program'
    assert evidence['support_status'] == 'unknown'
    assert evidence['temporal_status'] == 'snapshot_only'
    assert evidence['opened_event_id'] == result['opened_event_id']
    assert evidence['source_ref']['kb_release_id'] == 'r3'
    assert evidence['source_ref']['document_id'] == 'doc_law'
    assert _event_types(settings.db_path, run_id) == [
        'run.started',
        'tool.started',
        'source.opened',
        'tool.completed',
    ]


def test_failed_open_records_tool_failure_without_evidence(
    client: TestClient, settings
) -> None:
    case_id = create_case(client)
    run_id = _running_run(settings.db_path, case_id)

    with pytest.raises(KeyError, match='unknown chunk'):
        _adapter(settings).open_source(
            case_id=case_id,
            run_id=run_id,
            release_id='r3',
            chunk_id='missing',
        )

    assert _event_types(settings.db_path, run_id) == [
        'run.started',
        'tool.started',
        'tool.failed',
    ]
    conn = connect(settings.db_path)
    try:
        assert conn.execute('SELECT COUNT(*) FROM evidence_records').fetchone()[0] == 0
    finally:
        conn.close()


def test_open_source_fails_closed_when_repository_did_not_verify_quote(
    client: TestClient, settings
) -> None:
    case_id = create_case(client)
    run_id = _running_run(settings.db_path, case_id)
    repository = FakeEvidenceRepository()
    repository.opened = replace(repository.opened, quote_matches=False)
    adapter = EvidenceToolAdapter(
        db_path=settings.db_path,
        actor_id=settings.actor_id,
        repository=repository,
    )

    with pytest.raises(ValueError, match='not verified'):
        adapter.open_source(
            case_id=case_id,
            run_id=run_id,
            release_id='r3',
            chunk_id='chk_law_14',
        )

    assert _event_types(settings.db_path, run_id) == [
        'run.started',
        'tool.started',
        'tool.failed',
    ]
    conn = connect(settings.db_path)
    try:
        assert conn.execute('SELECT COUNT(*) FROM evidence_records').fetchone()[0] == 0
    finally:
        conn.close()


def test_open_event_rolls_back_when_evidence_insert_fails(
    client: TestClient, settings
) -> None:
    case_id = create_case(client)
    run_id = _running_run(settings.db_path, case_id)
    conn = connect(settings.db_path)
    try:
        with transaction(conn):
            conn.execute(
                'INSERT INTO evidence_records (id, case_id, run_id, source_ref_json, quote,'
                ' quote_hash, verification_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    'evid_collision',
                    case_id,
                    run_id,
                    '{}',
                    None,
                    None,
                    json.dumps({'assessed_by': 'unverified'}),
                    '2026-09-12T00:00:00.000Z',
                ),
            )
    finally:
        conn.close()

    def fixed_id(prefix: str) -> str:
        return 'evid_collision' if prefix == 'evid' else 'tool_collision'

    with pytest.raises(sqlite3.IntegrityError, match='UNIQUE constraint failed'):
        _adapter(settings, id_factory=fixed_id).open_source(
            case_id=case_id,
            run_id=run_id,
            release_id='r3',
            chunk_id='chk_law_14',
        )

    assert _event_types(settings.db_path, run_id) == [
        'run.started',
        'tool.started',
        'tool.failed',
    ]


def test_case_resource_and_selection_context_are_revision_bound_and_bounded(
    client: TestClient, settings
) -> None:
    case_id = create_case(client)
    draft = create_draft(
        client,
        case_id,
        blocks=[
            {'block_id': 'before', 'text': '前段'},
            {'block_id': 'selected', 'text': '選取文字'},
            {'block_id': 'after', 'text': '後段'},
            {'block_id': 'outside', 'text': '不應讀取'},
        ],
    )
    run_id = _running_run(settings.db_path, case_id)
    adapter = _adapter(settings)

    resource = adapter.read_case_resource(
        case_id=case_id,
        run_id=run_id,
        resource_id=draft['draft_id'],
        resource_revision=draft['resource_revision'],
    )
    selection = adapter.read_selection_context(
        case_id=case_id,
        run_id=run_id,
        target=block_target(draft, 'selected', '選取文字'),
        adjacent_blocks=1,
    )

    assert resource['resource_revision'] == draft['resource_revision']
    assert resource['is_head'] is True
    assert [block['block_id'] for block in selection['context']['blocks']] == [
        'before',
        'selected',
        'after',
    ]
    assert selection['writable_target']['block_id'] == 'selected'
    assert selection['writable_target']['char_start'] == 0
    assert selection['writable_target']['char_end'] == len('選取文字')
    assert _event_types(settings.db_path, run_id) == [
        'run.started',
        'tool.started',
        'tool.completed',
        'tool.started',
        'tool.completed',
    ]
