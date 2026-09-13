"""Enrich procedural facts from this case's stored documents without remote calls."""

from __future__ import annotations

import sqlite3
from typing import Any

from caseapi.domain.procedural_extraction import extract_procedural_fields


def enrich_procedural_fields(
    conn: sqlite3.Connection, *, case_id: str, fields: dict[str, Any],
) -> dict[str, Any]:
    """Human edits (including explicit unknown) always win over document extraction.

    New intake persists the enriched fields. Older cases may read these source
    assertions on demand: GET never advances revisions or modifies stored facts.
    """
    documents = conn.execute(
        'SELECT id, document_role, source_sha256, source_filename, extracted_text '
        'FROM case_documents WHERE case_id = ? ORDER BY rowid', (case_id,),
    ).fetchall()
    candidates: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        extracted = extract_procedural_fields(
            document['extracted_text'], document_role=document['document_role'],
        )
        for path, item in extracted.items():
            candidates.setdefault(path, []).append({
                'value': item['value'], 'origin': 'program', 'human_asserted': False,
                'reason': '依文件明載內容擷取，仍待人工核對',
                'legal_review_status': 'not_reviewed',
                'source': {
                    'document_id': document['id'],
                    'document_role': document['document_role'],
                    'source_filename': document['source_filename'],
                    'source_sha256': document['source_sha256'],
                    'quote': item['quote'], 'char_start': item['start'], 'char_end': item['end'],
                    'extraction_version': 'procedural-1',
                    **({'conflict': True, 'candidates': item['candidates']} if item.get('conflict') else {}),
                },
            })

    enriched = dict(fields)
    for path, items in candidates.items():
        existing = fields.get(path)
        if existing and (existing.get('origin') == 'human' or existing.get('human_asserted')):
            continue
        if existing and existing.get('value') is not None:
            continue
        if len({item['value'] for item in items}) > 1 or any(item['source'].get('conflict') for item in items):
            enriched[path] = {
                **items[0], 'value': None, 'reason': '文件記載互有矛盾，請核對後補值',
                'source': {**items[0]['source'], 'conflict': True, 'candidates': [item['source'] for item in items]},
            }
        else:
            enriched[path] = items[0]
    return enriched
