"""Upload source PDFs, seed rule-extracted facts, and persist reviewable AI suggestions.

The disposition has no stable form, so its summary is never promoted to a verified
fact.  Keywords, summary, and statute query retain LLM provenance and an explicit
``not_reviewed`` flag, including when the deterministic offline provider is used.
"""

import hashlib
import sqlite3
from typing import Any

import fitz  # PyMuPDF

from caseapi.audit import append_entry
from caseapi.ai.contracts import ModelProvider
from caseapi.ai.intake_analysis import IntakeAnalysis
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
# ``llm`` is the field-provenance category expected by the UI.  ``source.provider``
# still distinguishes the deterministic fixed mock from the live AgentCore path.
LLM_ANALYSIS_REASON = '自動產生的案件分析建議；尚未經法律覆核'
LLM_FIELD_ORIGIN = 'llm'
LEGAL_REVIEW_NOT_REVIEWED = 'not_reviewed'


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
    analysis_provider: ModelProvider,
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
    disposition_text: str | None = None
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
    analysis = analysis_provider.analyze_intake(
        appeal_text=appeal_text,
        disposition_text=disposition_text,
    )
    updated_case = _seed_facts(
        conn,
        case_id=case.case_id,
        actor_id=actor_id,
        extracted_fields=extracted_fields,
        analysis=analysis,
        analysis_provider=analysis_provider.descriptor().get('provider', 'unknown'),
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
    analysis: IntakeAnalysis | None,
    analysis_provider: str,
) -> CaseDetail:
    """Persist rule fields and clearly marked model suggestions in one facts version."""
    non_null = {path: value for path, value in extracted_fields.items() if value is not None}
    generated = _analysis_fields(analysis)
    if not non_null and not generated:
        return case_service.get_case(conn, case_id=case_id, actor_id=actor_id)

    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    heads = repo.load_heads(case_row)
    timestamp = now_iso()
    rule_fields = {
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
    generated_fields = {
        path: {
            'value': value,
            'origin': LLM_FIELD_ORIGIN,
            'human_asserted': False,
            'reason': LLM_ANALYSIS_REASON,
            'source': {'provider': analysis_provider},
            'legal_review_status': LEGAL_REVIEW_NOT_REVIEWED,
            'updated_by': actor_id,
            'updated_at': timestamp,
        }
        for path, value in generated.items()
    }
    fields = {**rule_fields, **generated_fields}
    version = resource_service.save_version(
        conn,
        case_id=case_id,
        resource_id=FACTS_RESOURCE_ID,
        resource_kind=repo.KIND_FACTS,
        content={'fields': fields},
        parent_id=None,
        origin=(
            resource_service.ORIGIN_AI
            if generated_fields
            else resource_service.ORIGIN_PROGRAM
        ),
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


def _analysis_fields(analysis: IntakeAnalysis | None) -> dict[str, str]:
    if analysis is None:
        return {}
    fields = {
        'analysis.keywords': analysis.keywords,
        'analysis.statute_query': analysis.statute_query,
        'disposition.summary': analysis.disposition_summary,
    }
    return {path: value for path, value in fields.items() if value is not None}
