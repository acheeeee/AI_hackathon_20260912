"""上傳建案：接收訴願書（必要）與行政處分函（選填）PDF，建立案件並用規則式
抽欄位種下第一版事實。

行政處分函格式不固定，這裡只存原件供之後展開查看，不對它做欄位抽取——對一
份沒有固定格式的文件做規則式抽取只會抽錯或抽不到，用模型抽也只是多一個
幻覺來源；這件事留給人工編輯或之後另外授權的 AI 輔助抽取（見 06 §5.2）。
"""

import hashlib
import sqlite3
from typing import Any

import fitz  # PyMuPDF

from caseapi.audit import append_entry
from caseapi.clock import now_iso
from caseapi.domain.appeal_extraction import extract_appeal_fields
from caseapi.ids import new_id
from caseapi.schemas.case import CaseCreateRequest, CaseDetail
from caseapi.services import case_repository as repo
from caseapi.services import case_service, resource_service
from caseapi.services.facts_service import FACTS_RESOURCE_ID

ROLE_APPEAL = 'appeal'
ROLE_DISPOSITION = 'disposition'
INTAKE_REASON = '規則式抽取自上傳訴願書'


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int]:
    """回傳全文與頁數；呼叫端負責在交易外先讀好檔案位元組。"""
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        text = ''.join(page.get_text() for page in doc)
        return text, doc.page_count
    finally:
        doc.close()


def intake_case(
    conn: sqlite3.Connection,
    *,
    actor_id: str,
    title: str | None,
    appeal_filename: str,
    appeal_bytes: bytes,
    disposition_filename: str | None = None,
    disposition_bytes: bytes | None = None,
) -> dict[str, Any]:
    case = case_service.create_case(
        conn, actor_id=actor_id, request=CaseCreateRequest(title=title)
    )
    appeal_text, appeal_pages = extract_pdf_text(appeal_bytes)
    _save_document(
        conn,
        case_id=case.case_id,
        actor_id=actor_id,
        role=ROLE_APPEAL,
        filename=appeal_filename,
        content=appeal_bytes,
        extracted_text=appeal_text,
        page_count=appeal_pages,
    )
    if disposition_bytes is not None:
        disposition_text, disposition_pages = extract_pdf_text(disposition_bytes)
        _save_document(
            conn,
            case_id=case.case_id,
            actor_id=actor_id,
            role=ROLE_DISPOSITION,
            filename=disposition_filename or 'disposition.pdf',
            content=disposition_bytes,
            extracted_text=disposition_text,
            page_count=disposition_pages,
        )
    extracted_fields = extract_appeal_fields(appeal_text)
    updated_case = _seed_facts(
        conn, case_id=case.case_id, actor_id=actor_id, extracted_fields=extracted_fields
    )
    return {
        'case_id': updated_case.case_id,
        'case_revision': updated_case.case_revision,
        'extracted_fields': extracted_fields,
    }


def _save_document(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    role: str,
    filename: str,
    content: bytes,
    extracted_text: str,
    page_count: int,
) -> None:
    conn.execute(
        'INSERT INTO case_documents (id, case_id, document_role, source_filename,'
        ' source_sha256, content_blob, extracted_text, page_count, created_by, created_at)'
        ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            new_id('doc'),
            case_id,
            role,
            filename,
            hashlib.sha256(content).hexdigest(),
            content,
            extracted_text,
            page_count,
            actor_id,
            now_iso(),
        ),
    )


def _seed_facts(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    extracted_fields: dict[str, str | None],
) -> CaseDetail:
    """把非 None 的抽取欄位寫成 facts 第一版；抽不到的欄位留給人工編輯。"""
    non_null = {path: value for path, value in extracted_fields.items() if value is not None}
    if not non_null:
        return case_service.get_case(conn, case_id=case_id, actor_id=actor_id)

    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    heads = repo.load_heads(case_row)
    timestamp = now_iso()
    fields = {
        path: {
            'value': value,
            'origin': resource_service.ORIGIN_PROGRAM,
            'human_asserted': False,
            'reason': INTAKE_REASON,
            'source': None,
            'updated_by': actor_id,
            'updated_at': timestamp,
        }
        for path, value in non_null.items()
    }
    version = resource_service.save_version(
        conn,
        case_id=case_id,
        resource_id=FACTS_RESOURCE_ID,
        resource_kind=repo.KIND_FACTS,
        content={'fields': fields},
        parent_id=None,
        origin=resource_service.ORIGIN_PROGRAM,
        actor_id=actor_id,
    )
    next_heads = repo.set_head(
        heads,
        resource_id=FACTS_RESOURCE_ID,
        kind=repo.KIND_FACTS,
        revision_id=version['resource_revision'],
        freshness=repo.FRESHNESS_CURRENT,
    )
    mutation_id = new_id('mut')
    repo.advance_case(
        conn,
        case_id=case_id,
        expected_revision=case_row['case_revision'],
        heads=next_heads,
        actor_id=actor_id,
        mutation_id=mutation_id,
    )
    append_entry(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action='case.intake',
        mutation_id=mutation_id,
        after_refs={
            'facts_revision': version['resource_revision'],
            'extracted_field_paths': list(fields),
        },
        reason=INTAKE_REASON,
    )
    return case_service.get_case(conn, case_id=case_id, actor_id=actor_id)
