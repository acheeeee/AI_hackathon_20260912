"""AI proposals cannot bypass the procedural fact editor's typed contract."""

import pytest
from pydantic import ValidationError

from caseapi.schemas.proposal import ReplaceFactOperation


@pytest.mark.parametrize(('path', 'value'), [
    ('appellant.standing', 'invented-status'),
    ('appeal.correction_deadline', '2026-02-30'),
    ('appeal.form_defect', 'definitely no'),
])
def test_ai_fact_operation_rejects_invalid_procedural_values(path, value):
    with pytest.raises(ValidationError):
        ReplaceFactOperation.model_validate({
            'op': 'replace_fact',
            'target': {'kind': 'fact_field', 'resource_id': 'facts',
                       'resource_revision': 'rev_test', 'field_path': path},
            'before_value': None, 'after_value': value,
        })
