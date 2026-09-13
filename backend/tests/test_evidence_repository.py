import hashlib
import json
from pathlib import Path

import pytest

from caseapi.evidence.repository import EvidenceRepository, ReleaseIntegrityError


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows),
        encoding='utf-8',
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def release_dir(tmp_path: Path) -> Path:
    release = tmp_path / 'r-test'
    release.mkdir()
    documents = [
        {
            'document_id': 'doc_law',
            'document_type': 'statute',
            'case_family_id': None,
            'source_file': 'data/raw/相關法規/訴願法.pdf',
            'source_sha256': 'law-sha',
            'extraction_version': 'ext-test',
        },
        {
            'document_id': 'doc_case',
            'document_type': 'decision',
            'case_family_id': 'fam_same_case',
            'source_file': 'data/raw/歷史訴願決定書/case.pdf',
            'source_sha256': 'case-sha',
            'extraction_version': 'ext-test',
        },
    ]
    pages = [
        {
            'document_id': 'doc_law',
            'extraction_version': 'ext-test',
            'page': 1,
            'lines': [{'line': 1, 'text': '訴願應於三十日內提起。'}],
        },
        {
            'document_id': 'doc_case',
            'extraction_version': 'ext-test',
            'page': 1,
            'lines': [
                {'line': 1, 'text': '本案訴願期間之計算仍有爭議。'},
                {'line': 2, 'text': '訴願逾期，應不受理。'},
            ],
        },
    ]
    sections = [
        {
            'section_id': 'sec_law_14',
            'document_id': 'doc_law',
            'section_type': 'statute_article',
            'metadata': {'statute_name': '訴願法', 'article_key': '14'},
        },
        {
            'section_id': 'sec_case_reason',
            'document_id': 'doc_case',
            'section_type': 'decision_reasons',
            'metadata': {},
        },
        {
            'section_id': 'sec_case_outcome',
            'document_id': 'doc_case',
            'section_type': 'decision_main_text',
            'metadata': {},
        },
    ]
    chunks = [
        {
            'chunk_id': 'chk_law_14',
            'section_id': 'sec_law_14',
            'document_id': 'doc_law',
            'quote_text': '訴願應於三十日內提起。',
            'search_text': '訴願應於三十日內提起。',
            'source_spans': [{
                'document_id': 'doc_law',
                'extraction_version': 'ext-test',
                'page': 1,
                'line': 1,
                'char_start': 0,
                'char_end': 11,
            }],
            'index_eligible': True,
            'quality_flags': [],
        },
        {
            'chunk_id': 'chk_case_reason',
            'section_id': 'sec_case_reason',
            'document_id': 'doc_case',
            'quote_text': '本案訴願期間之計算仍有爭議。',
            'search_text': '本案訴願期間之計算仍有爭議。',
            'source_spans': [{
                'document_id': 'doc_case',
                'extraction_version': 'ext-test',
                'page': 1,
                'line': 1,
                'char_start': 0,
                'char_end': 14,
            }],
            'index_eligible': True,
            'quality_flags': [],
        },
        {
            'chunk_id': 'chk_case_outcome',
            'section_id': 'sec_case_outcome',
            'document_id': 'doc_case',
            'quote_text': '訴願逾期，應不受理。',
            'search_text': '訴願逾期，應不受理。',
            'source_spans': [{
                'document_id': 'doc_case',
                'extraction_version': 'ext-test',
                'page': 1,
                'line': 2,
                'char_start': 0,
                'char_end': 10,
            }],
            'index_eligible': False,
            'quality_flags': ['historical_outcome_excluded'],
        },
    ]
    rows_by_file = {
        'documents.jsonl': documents,
        'pages.jsonl': pages,
        'sections.jsonl': sections,
        'chunks.jsonl': chunks,
    }
    for filename, rows in rows_by_file.items():
        _write_jsonl(release / filename, rows)
    manifest = {
        'release_id': 'r-test',
        'publish_status': 'validated',
        'artifact_sha256': {
            filename: _sha256(release / filename) for filename in rows_by_file
        },
    }
    (release / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False), encoding='utf-8'
    )
    return release


def test_open_source_rebuilds_exact_quote_and_hash(release_dir: Path) -> None:
    repository = EvidenceRepository(release_dir, expected_release_id='r-test')

    source = repository.open_source('chk_law_14')

    assert source.quote_text == '訴願應於三十日內提起。'
    assert source.source_exists is True
    assert source.quote_matches is True
    assert source.temporal_status == 'snapshot_only'
    assert source.content_hash == hashlib.sha256(
        source.quote_text.encode('utf-8')
    ).hexdigest()


def test_verify_quote_distinguishes_missing_source_from_mismatch(release_dir: Path) -> None:
    repository = EvidenceRepository(release_dir, expected_release_id='r-test')
    spans = repository.open_source('chk_law_14').source_spans

    mismatch = repository.verify_quote('doc_law', spans, '錯誤引文')
    missing = repository.verify_quote('doc_missing', spans, '錯誤引文')

    assert mismatch.source_exists is True
    assert mismatch.quote_matches is False
    assert missing.source_exists is False
    assert missing.quote_matches is None


def test_search_uses_only_eligible_chunks_and_can_exclude_same_case(
    release_dir: Path,
) -> None:
    repository = EvidenceRepository(release_dir, expected_release_id='r-test')

    excluded_outcome = repository.search('不受理')
    without_same_case = repository.search(
        '訴願期間', exclude_case_family_id='fam_same_case'
    )

    assert excluded_outcome == []
    assert {hit.document_id for hit in without_same_case} == {'doc_law'}
    assert all(hit.index_eligible for hit in without_same_case)


def test_search_returns_no_arbitrary_zero_score_results(release_dir: Path) -> None:
    repository = EvidenceRepository(release_dir, expected_release_id='r-test')

    assert repository.search('完全不存在的詞彙') == []


def test_release_hash_mismatch_fails_closed(release_dir: Path) -> None:
    with (release_dir / 'chunks.jsonl').open('a', encoding='utf-8') as stream:
        stream.write('{}\n')

    with pytest.raises(ReleaseIntegrityError, match='chunks.jsonl'):
        EvidenceRepository(release_dir, expected_release_id='r-test')


def test_r3_bm25_opens_article_level_source() -> None:
    release = Path(__file__).resolve().parents[2] / 'data' / 'processed' / 'releases' / 'r3'
    repository = EvidenceRepository(release, expected_release_id='r3')

    hits = repository.search(
        '訴願應自行政處分達到次日起三十日內提起',
        document_types={'statute'},
        top_k=5,
    )

    assert hits
    assert any(
        hit.metadata.get('statute_name') == '訴願法'
        and hit.metadata.get('article_key') == '14'
        for hit in hits
    )
    opened = repository.open_source(hits[0].chunk_id)
    assert opened.source_exists is True
    assert opened.quote_matches is True


def test_r3_can_open_a_complete_statute_section_spanning_multiple_chunks() -> None:
    """Search excerpts are chunks; the expandable article must be the whole section.

    r3's 洗錢防制法第 5 條 is immutable and deliberately spans two chunks.  Its
    second chunk contains paragraphs 4-8, which catches an implementation that
    merely relabels the first search excerpt as `full_text`.
    """
    release = Path(__file__).resolve().parents[2] / 'data' / 'processed' / 'releases' / 'r3'
    repository = EvidenceRepository(release, expected_release_id='r3')

    full_text = repository.open_section_text('sec_c7cd819aeb0d8a0c')
    first_chunk = repository.open_source('chk_9b6aa10f17728526')

    assert full_text.startswith('第 5 條')
    assert '前六項之中央目的事業主管機關認定有疑義者' in full_text
    assert '由行政院會同司法院指定之' in full_text
    assert len(full_text) > len(first_chunk.quote_text)
