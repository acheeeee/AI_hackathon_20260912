"""程序審查（訴願法第14條期間試算）讀取端點的服務層。

結果不持久化：每次都用當下的 facts 即時計算，跟 case_service 的
`processing_status` 是同一種作法——demo 導向、不建分析表，見 06 §5.2。
`legal_review_status` 固定回 `'not_reviewed'`：這支端點只給計算過程與
依據法條，最終是否受理留給人工覆核，不假裝系統能下最終認定。
"""

import sqlite3
from typing import Any

from caseapi.domain.appeal_deadline import review_appeal_deadline
from caseapi.services import case_repository as repo
from caseapi.services.facts_service import read_current_fields

LEGAL_REVIEW_STATUS = 'not_reviewed'


def get_procedural_review(
    conn: sqlite3.Connection, *, case_id: str, actor_id: str
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    heads = repo.load_heads(case_row)
    fields = read_current_fields(conn, case_id=case_id, heads=heads)

    review = review_appeal_deadline(
        service_date=_field_value(fields, 'service.date'),
        filed_date=_field_value(fields, 'appeal.filed_date'),
    )
    return {
        'case_id': case_id,
        'status': review.status,
        'deadline_date': review.deadline_date,
        'days_from_deadline': review.days_from_deadline,
        'missing_fields': list(review.missing_fields),
        'statute_basis': review.statute_basis,
        'caveats': list(review.caveats),
        'legal_review_status': LEGAL_REVIEW_STATUS,
    }


def _field_value(fields: dict[str, Any], path: str) -> str | None:
    field = fields.get(path)
    return field.get('value') if field else None
