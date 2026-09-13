"""把 `revise_selection` intent 的候選文字寫成一筆 `mode='local'` 提案。

跟 `draft_generation_service.save_generated_proposal` 是同一種形狀，差別是
`replace_document`（整份草稿）換成 `replace_text`（選取範圍內的文字）：
提案的頂層 `target` 與操作自己的 `target` 用同一個 `DraftBlockTarget`，
範圍檢查（`proposal_service._assert_within_scope`）天然通過，候選不會擴大
或縮小使用者當初選取的範圍。這裡一樣只組請求、呼叫既有
`proposal_service.create_proposal`，不直接改正文。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from caseapi.ai.contracts import ModelResult
from caseapi.schemas.proposal import (
    ChangeGroup,
    ProposalCreateRequest,
    ProposalDependencies,
    ReplaceTextOperation,
)
from caseapi.schemas.target import DraftBlockTarget
from caseapi.services import case_repository as repo
from caseapi.services import proposal_service

GROUP_ID = 'revise_selection_1'
GROUP_REASON = '依使用者選取範圍與修改指示產生的局部文字候選'


def save_revision_proposal(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_id: str,
    run_id: str,
    target: DraftBlockTarget,
    result: ModelResult,
) -> dict[str, Any]:
    case_row = repo.require_case(conn, case_id=case_id, actor_id=actor_id)
    candidate_text = result.draft_blocks[0].text
    proposal_request = ProposalCreateRequest(
        expected_case_revision=case_row['case_revision'],
        origin='ai',
        mode='local',
        run_id=run_id,
        target=target,
        dependencies=ProposalDependencies(),
        evidence=[],
        change_groups=[
            ChangeGroup(
                id=GROUP_ID,
                change_class='wording',
                reason=GROUP_REASON,
                evidence_ids=list(result.evidence_ids),
                operations=[
                    ReplaceTextOperation(op='replace_text', target=target, after_value=candidate_text)
                ],
            )
        ],
    )
    return proposal_service.create_proposal(
        conn, case_id=case_id, actor_id=actor_id, request=proposal_request
    )
