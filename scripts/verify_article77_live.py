"""Exercise all eight conditional rules through a running HTTP server.

Creates one clearly named synthetic case and edits only that new case. Uses no
uploaded documents or external model calls. Run with the existing Python runtime:
  python scripts/verify_article77_live.py --base-url http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4


def request(base: str, path: str, *, method: str = 'GET', data: dict | None = None) -> dict:
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    headers = {'Content-Type': 'application/json', 'Idempotency-Key': uuid4().hex}
    with urlopen(Request(base + '/api/v1' + path, data=body, headers=headers, method=method), timeout=30) as response:
        result = json.load(response)
    assert result['success'], result.get('error')
    return result['data']


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--with-demo-upload', action='store_true',
                        help='Also upload the committed fictional PDF pair; no remote analysis.')
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    case = request(base, '/cases', method='POST', data={'title': '第77條完整分支驗收（虛構案件）'})
    case_id = case['case_id']
    path = '/cases/' + case_id
    empty = request(base, path + '/procedural-review')
    assert all(item['status'] == 'INSUFFICIENT_EVIDENCE' for item in empty['clause_assessments'])
    definitions = empty['field_definitions']
    baseline = {item['field_path']: None for item in definitions}
    baseline.update({
        'appellant.name': '程序測試股份有限公司',
        'appeal.form_defect': 'no',
        'service.date': '2020-07-01',
        'appeal.received_date': '2020-07-20',
        'appeal.initial_submission_method': 'written',
        'appellant.standing': 'recipient',
        'appellant.capacity': 'capable',
        'appellant.entity_type': 'legal_person',
        'representative.name': '林測試',
        'representative.authority': 'yes',
        'disposition.current_status': 'exists',
        'case.prior_decision_record': 'no',
        'case.prior_withdrawal_record': 'no',
        'challenged_act.type': 'administrative_disposition',
        'challenged_act.within_appeal_scope': 'yes',
    })

    def save(values: dict) -> list[dict]:
        current = request(base, path)
        request(base, path + '/facts', method='PATCH', data={
            'expected_case_revision': current['case_revision'],
            'reason': '合成驗收條件；非真實案件',
            'field_changes': [
                {'field_path': key, 'value': value, 'human_asserted': True,
                 'reason': '合成驗收條件'} for key, value in values.items()
            ],
        })
        review = request(base, path + '/procedural-review')
        assert review['case_revision'] == current['case_revision'] + 1
        return review['clause_assessments']

    clear = save(baseline)
    assert [item['status'] for item in clear] == ['NOT_TRIGGERED'] * 8, clear
    correction = {
        'appeal.correction_scope': 'all', 'appeal.correction_notified': 'yes',
        'appeal.correction_deadline': '2020-08-01', 'appeal.correction_completed': 'no',
    }
    triggers = {
        1: {'appeal.form_defect': 'yes', 'appeal.defect_remediable': 'no'},
        2: {'appeal.received_date': '2020-08-01'},
        3: {'appellant.standing': 'not_eligible'},
        4: {**correction, 'appellant.capacity': 'incapable', 'legal_representative.present': 'no'},
        5: {**correction, 'representative.authority': 'no'},
        6: {'disposition.current_status': 'nonexistent'},
        7: {'case.prior_decision_record': 'yes'},
        8: {'challenged_act.type': 'non_administrative'},
    }
    for clause, changes in triggers.items():
        result = save({**baseline, **changes})
        assert result[clause - 1]['status'] == 'TRIGGERED', result[clause - 1]
    followup = save({
        **baseline, 'appeal.initial_submission_method': 'objection',
        'appeal.objection_date': '2020-07-20', 'appeal.written_submission_completed': 'yes',
        'appeal.written_submission_date': '2020-08-20',
    })
    assert followup[1]['status'] == 'TRIGGERED'
    restored = save(baseline)
    assert [item['status'] for item in restored] == ['NOT_TRIGGERED'] * 8
    print(json.dumps({'case_id': case_id, 'empty_to_clear': 'PASS', 'eight_trigger_paths': 'PASS',
                      'article57_late_followup': 'PASS', 'reload_persistence': 'PASS'}, ensure_ascii=False))
    if args.with_demo_upload:
        verify_demo_upload(base)


def verify_demo_upload(base: str) -> None:
    """Only the committed fictional pair is eligible for this live test."""
    root = Path(__file__).resolve().parents[1] / 'data' / 'demo'
    boundary = 'article77_' + uuid4().hex
    parts = []
    for field, filename in (
        ('appeal_pdf', '展示用_虛擬資產服務登記_訴願書.pdf'),
        ('disposition_pdf', '展示用_虛擬資產服務登記_行政處分函.pdf'),
    ):
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
                      f'filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n').encode()
                     + (root / filename).read_bytes() + b'\r\n')
    body = b''.join(parts) + f'--{boundary}--\r\n'.encode()
    upload = Request(base + '/api/v1/cases/intake', data=body, method='POST', headers={
        'Content-Type': 'multipart/form-data; boundary=' + boundary,
        'Idempotency-Key': uuid4().hex,
    })
    with urlopen(upload, timeout=60) as response:
        result = json.load(response)['data']
    case_id = result['case_id']
    review = request(base, '/cases/' + case_id + '/procedural-review')
    clauses = review['clause_assessments']
    assert [item['status'] for item in clauses] == ['INSUFFICIENT_EVIDENCE'] + ['NOT_TRIGGERED'] * 7, clauses
    service = clauses[1]['input_sources']['service.date']
    assert service['origin'] == 'program' and service['source']['quote'] and service['source']['source_sha256']
    assert clauses[0]['input']['appeal.correction_deadline'] is None
    print(json.dumps({'uploaded_case_id': case_id, 'document_backed_clauses_2_to_8': 'PASS',
                      'application_correction_excluded': 'PASS',
                      'clause1_requires_form_review': 'PASS'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
