"""訴願法第77條八款的程序審查輸出。

目前只有第2款有經程式實作的日期試算。其餘款別仍列出規則需要的輸入與判斷
方式，讓 UI 能完整揭露八款；第1、4、5、6、7款明確標成 mock，第3、8款固定
轉人工覆核。mock 與人工款絕不輸出成立／不成立，避免示範資料被誤認為法律
結論。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from caseapi.domain.appeal_deadline import (
    STATUS_DEADLINE_KNOWN,
    STATUS_INSUFFICIENT,
    STATUS_OVERDUE,
    STATUS_WITHIN_PERIOD,
    DeadlineReview,
)

OUTCOME_NOT_TRIGGERED = 'NOT_TRIGGERED'
OUTCOME_TRIGGERED = 'TRIGGERED'
OUTCOME_INSUFFICIENT = 'INSUFFICIENT_EVIDENCE'
OUTCOME_NEEDS_HUMAN = 'NEEDS_HUMAN'

MODE_RULE = 'rule'
MODE_MOCK = 'mock'
MODE_MANUAL_REVIEW = 'manual_review'

InputValue = str | int | bool | None


@dataclass(frozen=True)
class Article77Assessment:
    clause_no: int
    rule_id: str
    input: dict[str, InputValue]
    status: str
    rule_description: str
    reason: str
    evaluation_mode: str


@dataclass(frozen=True)
class _PendingRule:
    clause_no: int
    evaluation_mode: str
    status: str
    input_fields: tuple[str, ...]
    rule_description: str
    reason: str


_PENDING_RULES = {
    rule.clause_no: rule
    for rule in (
        _PendingRule(
            clause_no=1,
            evaluation_mode=MODE_MOCK,
            status=OUTCOME_INSUFFICIENT,
            input_fields=(
                'appeal.form_defect',
                'appeal.defect_remediable',
                'appeal.correction_deadline',
                'appeal.correction_completed',
            ),
            rule_description=(
                '檢查訴願書法定程式、是否可補正，以及通知補正後是否逾期未完成。'
            ),
            reason=(
                '目前未擷取訴願書程式、補正通知與補正完成狀態；Mock 規則只揭露'
                '所需輸入，不作成立與否判定。'
            ),
        ),
        _PendingRule(
            clause_no=3,
            evaluation_mode=MODE_MANUAL_REVIEW,
            status=OUTCOME_NEEDS_HUMAN,
            input_fields=(
                'appellant.name',
                'disposition.recipient',
                'appellant.interest_basis',
            ),
            rule_description=(
                '核對訴願人是否符合第18條的處分相對人或利害關係人資格；涉及法律'
                '判斷，固定轉交人工覆核。'
            ),
            reason='現有欄位無法判斷訴願人與處分的法律上關係，需由承辦人覆核。',
        ),
        _PendingRule(
            clause_no=4,
            evaluation_mode=MODE_MOCK,
            status=OUTCOME_INSUFFICIENT,
            input_fields=(
                'appellant.capacity',
                'legal_representative.present',
                'appeal.correction_deadline',
                'appeal.correction_completed',
            ),
            rule_description=(
                '檢查訴願能力、法定代理人及通知補正後的完成狀態；目前以 Mock 規則'
                '揭露所需輸入。'
            ),
            reason=(
                '目前未擷取訴願能力、法定代理人及補正狀態；Mock 規則不作成立與否'
                '判定。'
            ),
        ),
        _PendingRule(
            clause_no=5,
            evaluation_mode=MODE_MOCK,
            status=OUTCOME_INSUFFICIENT,
            input_fields=(
                'appellant.entity_type',
                'representative.name',
                'representative.authority',
                'appeal.correction_completed',
            ),
            rule_description=(
                '檢查團體類型、代表人或管理人及通知補正後的完成狀態；目前以 Mock '
                '規則揭露所需輸入。'
            ),
            reason=(
                '目前未擷取團體類型、代表權及補正狀態；Mock 規則不作成立與否判定。'
            ),
        ),
        _PendingRule(
            clause_no=6,
            evaluation_mode=MODE_MOCK,
            status=OUTCOME_INSUFFICIENT,
            input_fields=('disposition.doc_no', 'disposition.current_status'),
            rule_description=(
                '檢查原行政處分是否已撤銷、廢止或因其他原因不存在；目前以 Mock '
                '規則揭露所需輸入。'
            ),
            reason=(
                '現有資料沒有原處分目前效力狀態；Mock 規則不作成立與否判定。'
            ),
        ),
        _PendingRule(
            clause_no=7,
            evaluation_mode=MODE_MOCK,
            status=OUTCOME_INSUFFICIENT,
            input_fields=(
                'case.prior_decision_record',
                'case.prior_withdrawal_record',
            ),
            rule_description=(
                '以案件識別資料比對是否已有決定或撤回紀錄；目前未串接完整前案庫，'
                '使用 Mock 規則。'
            ),
            reason=(
                '目前沒有可比對的前次決定或撤回紀錄；Mock 規則不宣稱已查核案件庫。'
            ),
        ),
        _PendingRule(
            clause_no=8,
            evaluation_mode=MODE_MANUAL_REVIEW,
            status=OUTCOME_NEEDS_HUMAN,
            input_fields=(
                'disposition.authority',
                'disposition.doc_no',
                'challenged_act.type',
                'challenged_act.legal_effect',
            ),
            rule_description=(
                '核對被爭執事項是否為行政處分且屬訴願救濟範圍；涉及法律判斷，固定'
                '轉交人工覆核。'
            ),
            reason='是否屬行政處分及訴願救濟範圍需法律判斷，本款固定轉人工覆核。',
        ),
    )
}


def review_article_77(
    *,
    facts: Mapping[str, InputValue],
    deadline_review: DeadlineReview,
) -> tuple[Article77Assessment, ...]:
    """依款次輸出八筆結果；不以 mock 或人工結果推導法律結論。"""
    assessments: list[Article77Assessment] = []
    for clause_no in range(1, 9):
        if clause_no == 2:
            assessments.append(_deadline_assessment(facts, deadline_review))
            continue
        rule = _PENDING_RULES[clause_no]
        assessments.append(
            Article77Assessment(
                clause_no=rule.clause_no,
                rule_id=f'art77_para{rule.clause_no}',
                input={path: facts.get(path) for path in rule.input_fields},
                status=rule.status,
                rule_description=rule.rule_description,
                reason=rule.reason,
                evaluation_mode=rule.evaluation_mode,
            )
        )
    return tuple(assessments)


def _deadline_assessment(
    facts: Mapping[str, InputValue],
    review: DeadlineReview,
) -> Article77Assessment:
    status, reason = _deadline_outcome_and_reason(review)
    return Article77Assessment(
        clause_no=2,
        rule_id='art77_para2',
        input={
            'service.date': facts.get('service.date'),
            'appeal.filed_date': facts.get('appeal.filed_date'),
            'computed.deadline_date': review.deadline_date,
            'computed.days_from_deadline': review.days_from_deadline,
        },
        status=status,
        rule_description=(
            '比較行政處分送達日、三十日法定期間與訴願提起日；期限計算沿用既有'
            '訴願法第14條試算。'
        ),
        reason=reason,
        evaluation_mode=MODE_RULE,
    )


def _deadline_outcome_and_reason(review: DeadlineReview) -> tuple[str, str]:
    if review.status == STATUS_INSUFFICIENT:
        return OUTCOME_INSUFFICIENT, '缺少送達日期，無法試算訴願提起期間。'
    if review.status == STATUS_DEADLINE_KNOWN:
        return (
            OUTCOME_INSUFFICIENT,
            f'試算期限為 {review.deadline_date}，但缺少訴願提起日，無法判斷是否逾期。',
        )
    if review.days_from_deadline is None:
        raise ValueError('completed deadline review must include days_from_deadline')
    if review.status == STATUS_OVERDUE:
        return (
            OUTCOME_TRIGGERED,
            f'訴願提起日晚於試算期限 {review.days_from_deadline} 天，規則標記為可能逾期。',
        )
    if review.status == STATUS_WITHIN_PERIOD:
        if review.days_from_deadline == 0:
            reason = '訴願提起日為試算期限當日，規則未標記逾期。'
        else:
            reason = (
                f'訴願提起日早於試算期限 {-review.days_from_deadline} 天，規則未標記逾期。'
            )
        return OUTCOME_NOT_TRIGGERED, reason
    raise ValueError(f'unsupported deadline review status: {review.status}')
