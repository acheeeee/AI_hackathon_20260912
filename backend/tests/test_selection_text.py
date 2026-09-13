"""`selection_text_from_context`：送進模型的選取文字要是人看得懂的中文。

模型拿到的是這個函式的輸出。如果事實欄位寫成 `appellant.name`，模型（與
畫面上回顯這段文字的側邊欄）就得自己猜那是什麼欄位；`fact_fields.py`
已經有一份中文對照表，這裡要用它。
"""

from caseapi.ai.selection_text import selection_text_from_context


def _fact_field_context(field_path: str, value: str | None) -> dict:
    """`evidence_tools._selection_context` 對 fact_field 目標回傳的形狀。"""
    return {
        'writable_target': {
            'kind': 'fact_field',
            'resource_id': 'facts',
            'resource_revision': 'res_1',
            'field_path': field_path,
        },
        'context': {'field': None if value is None else {'value': value, 'origin': 'program'}},
    }


def test_fact_field_selection_uses_the_chinese_label_not_the_raw_path() -> None:
    text = selection_text_from_context(_fact_field_context('appellant.name', '絕○○○股份有限公司'))

    assert text == '訴願人：絕○○○股份有限公司'
    assert 'appellant.name' not in text


def test_every_allowlisted_fact_field_renders_without_a_raw_path() -> None:
    from caseapi.domain.fact_fields import FACT_FIELD_ALLOWLIST

    for path in sorted(FACT_FIELD_ALLOWLIST):
        text = selection_text_from_context(_fact_field_context(path, '測試值'))
        assert path not in text, f'{path} 仍以原始路徑送進模型'
        assert text.endswith('：測試值')


def test_unset_fact_field_still_reports_nothing_to_explain() -> None:
    assert selection_text_from_context(_fact_field_context('service.date', None)) == ''


def test_draft_block_selection_still_returns_the_selected_text_verbatim() -> None:
    context = {
        'writable_target': {
            'kind': 'draft_block',
            'block_id': 'reason-1',
            'selected_text': '未作任何法律判斷',
        }
    }

    assert selection_text_from_context(context) == '未作任何法律判斷'
