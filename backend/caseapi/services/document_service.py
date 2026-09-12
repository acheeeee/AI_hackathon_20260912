"""讀回上傳建案時保存的原始 PDF，供案件詳情頁「原檔展開」使用。

只有 metadata 走列表端點；原始位元組要單獨用內容端點取，避免列表回應
夾帶大型 blob。案件隔離用 case_id 過濾，不存在或跨案一律視為 404。
"""

import sqlite3
from typing import Any

from caseapi.errors import resource_not_found
from caseapi.services.case_repository import require_case


def list_documents(
    conn: sqlite3.Connection, *, case_id: str, actor_id: str
) -> list[dict[str, Any]]:
    require_case(conn, case_id=case_id, actor_id=actor_id)
    rows = conn.execute(
        'SELECT id, document_role, source_filename, source_sha256, page_count, created_at'
        ' FROM case_documents WHERE case_id = ? ORDER BY created_at ASC',
        (case_id,),
    ).fetchall()
    return [
        {
            'document_id': row['id'],
            'document_role': row['document_role'],
            'source_filename': row['source_filename'],
            'source_sha256': row['source_sha256'],
            'page_count': row['page_count'],
            'created_at': row['created_at'],
        }
        for row in rows
    ]


def get_document_content(
    conn: sqlite3.Connection, *, case_id: str, actor_id: str, document_id: str
) -> bytes:
    require_case(conn, case_id=case_id, actor_id=actor_id)
    row = conn.execute(
        'SELECT content_blob FROM case_documents WHERE id = ? AND case_id = ?',
        (document_id, case_id),
    ).fetchone()
    if row is None:
        raise resource_not_found()
    return row['content_blob']
