"""Shared final-outcome guard for generated analysis and draft reasoning.

Generated content may describe evidence gaps and legal elements, but it must
not decide the appeal. Match normalized text so formatting whitespace cannot
bypass the guard while leaving neutral discussion untouched.
"""

from __future__ import annotations

import unicodedata


FINAL_OUTCOME_MARKERS = (
    '本訴願駁回',
    '本件訴願駁回',
    '本件訴願應予駁回',
    '訴願應予駁回',
    '本件應予駁回',
    '本訴願為有理由',
    '本件訴願為有理由',
    '本訴願為無理由',
    '本件訴願為無理由',
    '本案訴願為無理由',
    '原處分應予撤銷',
    '撤銷原處分',
    '維持原處分',
    '原處分並無違誤應予維持',
    '訴願不受理',
    '不受理決定',
    '應作成不受理決定',
    '應不受理',
    '本案欠缺程序要件應予不受理',
)


def contains_final_outcome(text: str) -> bool:
    """Return whether normalized generated text asserts a final outcome."""
    normalized = _normalize(text)
    return any(_normalize(marker) in normalized for marker in FINAL_OUTCOME_MARKERS)


def _normalize(text: str) -> str:
    return ''.join(
        character
        for character in text
        if not character.isspace()
        and unicodedata.category(character)[0] not in {'P', 'Z'}
    )
