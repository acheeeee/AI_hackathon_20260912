"""Hash-bound source opening and offline BM25 over one immutable release."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import jieba
from rank_bm25 import BM25Okapi


class ReleaseIntegrityError(RuntimeError):
    """The release cannot be trusted as the requested immutable snapshot."""


@dataclass(frozen=True)
class EvidenceCheck:
    source_exists: bool
    quote_matches: bool | None
    source_text: str | None


@dataclass(frozen=True)
class OpenedSource:
    release_id: str
    chunk_id: str
    document_id: str
    section_id: str
    quote_text: str
    source_spans: tuple[dict[str, Any], ...]
    source_file: str
    source_sha256: str
    content_hash: str
    source_exists: bool
    quote_matches: bool
    temporal_status: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SearchHit:
    release_id: str
    chunk_id: str
    document_id: str
    section_id: str
    document_type: str
    case_family_id: str | None
    excerpt: str
    source_spans: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]
    score: float
    index_eligible: bool


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding='utf-8') as stream:
            return [json.loads(line) for line in stream if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseIntegrityError(f'cannot read {path.name}: {exc}') from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
    except OSError as exc:
        raise ReleaseIntegrityError(f'cannot hash {path.name}: {exc}') from exc
    return digest.hexdigest()


def _tokenize(text: str) -> list[str]:
    return [token for token in jieba.lcut(text or '') if token.strip()]


class EvidenceRepository:
    """Read and search one release without modifying the case database.

    Construction verifies the four artifacts this repository consumes against
    the manifest. Search indexes only chunks explicitly marked eligible.
    """

    _REQUIRED_ARTIFACTS = (
        'documents.jsonl',
        'pages.jsonl',
        'sections.jsonl',
        'chunks.jsonl',
    )

    def __init__(self, release_dir: Path, *, expected_release_id: str) -> None:
        self.release_dir = Path(release_dir)
        self._manifest = self._load_manifest(expected_release_id)
        self.release_id = expected_release_id
        self._verify_artifact_hashes()

        documents = _read_jsonl(self.release_dir / 'documents.jsonl')
        pages = _read_jsonl(self.release_dir / 'pages.jsonl')
        sections = _read_jsonl(self.release_dir / 'sections.jsonl')
        chunks = _read_jsonl(self.release_dir / 'chunks.jsonl')

        self._documents = self._index_unique(documents, 'document_id', 'documents.jsonl')
        self._sections = self._index_unique(sections, 'section_id', 'sections.jsonl')
        self._chunks = self._index_unique(chunks, 'chunk_id', 'chunks.jsonl')
        self._page_lines = self._index_page_lines(pages)
        self._eligible_chunks = [chunk for chunk in chunks if chunk.get('index_eligible') is True]
        self._tokens = [_tokenize(chunk.get('search_text', '')) for chunk in self._eligible_chunks]
        self._token_sets = [set(tokens) for tokens in self._tokens]
        self._bm25 = BM25Okapi(self._tokens) if self._tokens else None

    def _load_manifest(self, expected_release_id: str) -> dict[str, Any]:
        path = self.release_dir / 'manifest.json'
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseIntegrityError(f'cannot read manifest.json: {exc}') from exc
        if manifest.get('release_id') != expected_release_id:
            raise ReleaseIntegrityError(
                f'release id mismatch: expected {expected_release_id}, '
                f"got {manifest.get('release_id')}"
            )
        if manifest.get('publish_status') != 'validated':
            raise ReleaseIntegrityError('release publish_status is not validated')
        return manifest

    def _verify_artifact_hashes(self) -> None:
        declared = self._manifest.get('artifact_sha256')
        if not isinstance(declared, dict):
            raise ReleaseIntegrityError('manifest artifact_sha256 is missing')
        for filename in self._REQUIRED_ARTIFACTS:
            expected = declared.get(filename)
            if not isinstance(expected, str):
                raise ReleaseIntegrityError(f'{filename} hash is missing')
            actual = _sha256_file(self.release_dir / filename)
            if actual != expected:
                raise ReleaseIntegrityError(f'{filename} hash mismatch')

    @staticmethod
    def _index_unique(
        rows: Iterable[dict[str, Any]], key: str, filename: str
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            value = row.get(key)
            if not isinstance(value, str) or not value or value in result:
                raise ReleaseIntegrityError(f'{filename} has invalid or duplicate {key}')
            result[value] = row
        return result

    @staticmethod
    def _index_page_lines(pages: Iterable[dict[str, Any]]) -> dict[tuple[str, int, int], str]:
        result: dict[tuple[str, int, int], str] = {}
        for page in pages:
            document_id = page.get('document_id')
            page_number = page.get('page')
            for line in page.get('lines', []):
                key = (document_id, page_number, line.get('line'))
                if key in result or not isinstance(line.get('text'), str):
                    raise ReleaseIntegrityError('pages.jsonl has duplicate or invalid line')
                result[key] = line['text']
        return result

    def verify_quote(
        self,
        document_id: str,
        source_spans: Iterable[Mapping[str, Any]],
        quote: str,
    ) -> EvidenceCheck:
        spans = list(source_spans)
        if document_id not in self._documents or not spans:
            return EvidenceCheck(False, None, None)
        source_text = self._rebuild(document_id, spans)
        if source_text is None:
            return EvidenceCheck(False, None, None)
        return EvidenceCheck(True, source_text == quote, source_text)

    def _rebuild(
        self, document_id: str, source_spans: Iterable[Mapping[str, Any]]
    ) -> str | None:
        document = self._documents[document_id]
        parts: list[str] = []
        for span in source_spans:
            if span.get('document_id') != document_id:
                return None
            extraction_version = span.get('extraction_version')
            if extraction_version != document.get('extraction_version'):
                return None
            key = (document_id, span.get('page'), span.get('line'))
            line = self._page_lines.get(key)
            start = span.get('char_start')
            end = span.get('char_end')
            if (
                line is None
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end < start
                or end > len(line)
            ):
                return None
            parts.append(line[start:end])
        return '\n'.join(parts)

    def open_source(self, chunk_id: str) -> OpenedSource:
        chunk = self._chunks.get(chunk_id)
        if chunk is None:
            raise KeyError(f'unknown chunk_id: {chunk_id}')
        document_id = chunk['document_id']
        check = self.verify_quote(
            document_id, chunk.get('source_spans', []), chunk.get('quote_text', '')
        )
        if not check.source_exists or not check.quote_matches:
            raise ReleaseIntegrityError(f'{chunk_id} source span does not rebuild quote')
        document = self._documents[document_id]
        section = self._sections.get(chunk['section_id'])
        if section is None or section.get('document_id') != document_id:
            raise ReleaseIntegrityError(f'{chunk_id} references an invalid section')
        quote_text = chunk['quote_text']
        return OpenedSource(
            release_id=self.release_id,
            chunk_id=chunk_id,
            document_id=document_id,
            section_id=chunk['section_id'],
            quote_text=quote_text,
            source_spans=tuple(dict(span) for span in chunk['source_spans']),
            source_file=document['source_file'],
            source_sha256=document['source_sha256'],
            content_hash=hashlib.sha256(quote_text.encode('utf-8')).hexdigest(),
            source_exists=True,
            quote_matches=True,
            temporal_status='snapshot_only',
            metadata=dict(section.get('metadata', {})),
        )

    def open_section_text(self, section_id: str) -> str:
        """Rebuild and return the complete section, not a single search chunk."""
        section = self._sections.get(section_id)
        if section is None:
            raise KeyError(f'unknown section_id: {section_id}')
        document_id = section['document_id']
        check = self.verify_quote(
            document_id,
            section.get('source_spans', []),
            section.get('quote_text', ''),
        )
        if not check.source_exists or not check.quote_matches or check.source_text is None:
            raise ReleaseIntegrityError(f'{section_id} source span does not rebuild quote')
        return _normalize_section_for_display(check.source_text)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        document_types: set[str] | None = None,
        exclude_case_family_id: str | None = None,
    ) -> list[SearchHit]:
        if not query.strip() or top_k <= 0 or self._bm25 is None:
            return []
        query_tokens = _tokenize(query)
        query_set = set(query_tokens)
        if not query_set:
            return []
        scores = self._bm25.get_scores(query_tokens)
        ranked = sorted(range(len(scores)), key=lambda index: (-float(scores[index]), index))

        hits: list[SearchHit] = []
        seen: set[tuple[str, str]] = set()
        for index in ranked:
            if not query_set.intersection(self._token_sets[index]):
                continue
            chunk = self._eligible_chunks[index]
            document = self._documents.get(chunk['document_id'])
            section = self._sections.get(chunk['section_id'])
            if document is None or section is None:
                raise ReleaseIntegrityError('eligible chunk has a dangling reference')
            document_type = document.get('document_type')
            family_id = document.get('case_family_id')
            if document_types is not None and document_type not in document_types:
                continue
            if exclude_case_family_id is not None and family_id == exclude_case_family_id:
                continue
            dedupe_key = self._dedupe_key(document, section)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            hits.append(self._to_search_hit(chunk, document, section, float(scores[index])))
            if len(hits) >= top_k:
                break
        return hits

    @staticmethod
    def _dedupe_key(
        document: Mapping[str, Any], section: Mapping[str, Any]
    ) -> tuple[str, str]:
        if document.get('document_type') == 'statute':
            return ('statute_section', str(section['section_id']))
        if document.get('document_type') == 'decision' and document.get('case_family_id'):
            return ('case_family', str(document['case_family_id']))
        return ('document', str(document['document_id']))

    def _to_search_hit(
        self,
        chunk: Mapping[str, Any],
        document: Mapping[str, Any],
        section: Mapping[str, Any],
        score: float,
    ) -> SearchHit:
        return SearchHit(
            release_id=self.release_id,
            chunk_id=str(chunk['chunk_id']),
            document_id=str(document['document_id']),
            section_id=str(section['section_id']),
            document_type=str(document['document_type']),
            case_family_id=document.get('case_family_id'),
            excerpt=str(chunk.get('quote_text', '')),
            source_spans=tuple(dict(span) for span in chunk.get('source_spans', [])),
            metadata=dict(section.get('metadata', {})),
            score=score,
            index_eligible=True,
        )


_SECTION_LINE_BOUNDARY = re.compile(
    r'^(?:第\s*\d+(?:-\d+)?\s*條$|\d+(?:\s+|$)|[一二三四五六七八九十百]+、|'
    r'（[一二三四五六七八九十百]+）)'
)
_SECTION_STANDALONE_BOUNDARY = re.compile(r'^(?:第\s*\d+(?:-\d+)?\s*條|\d+)$')


def _normalize_section_for_display(text: str) -> str:
    """Remove PDF visual wraps while retaining article/paragraph/list boundaries."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ''
    output = [lines[0]]
    previous = lines[0]
    for line in lines[1:]:
        if _SECTION_LINE_BOUNDARY.match(line) or _SECTION_STANDALONE_BOUNDARY.match(previous):
            output.extend(('\n', line))
        else:
            output.append(line)
        previous = line
    return ''.join(output)
