"""Shared by every ModelProvider's `explain` handler.

`read_selection_context`'s `writable_target` is just the TargetRef the
caller sent back (`target.model_dump()`), and only `draft_block` targets
carry a `selected_text` field directly on it. A `fact_field` target's
actual value lives one level down, in `context['context']['field']`
(see `caseapi/tools/evidence_tools.py::_selection_context`). Providers
that only checked `writable_target.get('selected_text', '')` silently
explained an empty string for every fact-field selection instead of
raising or reading the real value — this is the one place that lookup
happens, so every provider stays consistent and the gap can't reopen
per-provider.
"""

from __future__ import annotations

from typing import Any


def selection_text_from_context(context: dict[str, Any]) -> str:
    target = context['writable_target']
    if target.get('kind') == 'fact_field':
        field = context.get('context', {}).get('field')
        if field is None or field.get('value') is None:
            return ''
        return f"{target['field_path']}：{field['value']}"
    return target.get('selected_text', '')
