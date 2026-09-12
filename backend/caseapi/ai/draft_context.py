"""依 run 凍結的 refs 把草稿生成要用的內容讀出來。

run 的 `context_manifest` 只存 refs（哪個 facts 版本、哪個選法規版本、哪份
訴願書文件），建立後不可變（06 §3 規則 13）。這裡按那些 refs 讀回內容，
所以同一個 run 重讀得到同一份 context，就算之後事實或選法規又被改過也一樣。

讀出來的東西交給 provider 的是純資料：provider 不拿 DB 連線，也不能挑別的
案件或別的版本（規則 15）。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from caseapi.services import resource_service
from caseapi.services.facts_service import FACTS_RESOURCE_ID
from caseapi.services.statute_selection_service import STATUTE_SELECTION_RESOURCE_ID


def load_draft_context(
    conn: sqlite3.Connection, *, case_id: str, manifest: dict[str, Any]
) -> dict[str, Any]:
    return {
        'release_id': manifest.get('kb_release_id'),
        'facts': _facts(conn, case_id=case_id, revision_id=manifest.get('facts_revision')),
        'statutes': _statutes(
            conn, case_id=case_id, revision_id=manifest.get('statute_selection_revision')
        ),
        'appeal_text': _appeal_text(conn, document_id=manifest.get('appeal_document_id')),
    }


def _content(
    conn: sqlite3.Connection, *, case_id: str, resource_id: str, revision_id: str | None
) -> dict[str, Any] | None:
    if not revision_id:
        return None
    row = resource_service.require_version(
        conn, case_id=case_id, resource_id=resource_id, revision_id=revision_id
    )
    return json.loads(row['content_json'])


def _facts(
    conn: sqlite3.Connection, *, case_id: str, revision_id: str | None
) -> dict[str, Any]:
    """只取值，不把 origin／reason 這類欄位中繼資料送進模型 context。"""
    content = _content(
        conn, case_id=case_id, resource_id=FACTS_RESOURCE_ID, revision_id=revision_id
    )
    fields = (content or {}).get('fields', {})
    return {path: field.get('value') for path, field in fields.items()}


def _statutes(
    conn: sqlite3.Connection, *, case_id: str, revision_id: str | None
) -> list[dict[str, Any]]:
    content = _content(
        conn,
        case_id=case_id,
        resource_id=STATUTE_SELECTION_RESOURCE_ID,
        revision_id=revision_id,
    )
    return list((content or {}).get('selected', []))


def _appeal_text(conn: sqlite3.Connection, *, document_id: str | None) -> str | None:
    if not document_id:
        return None
    row = conn.execute(
        'SELECT extracted_text FROM case_documents WHERE id = ?', (document_id,)
    ).fetchone()
    return row['extracted_text'] if row else None
