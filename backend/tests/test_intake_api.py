"""Upload intake: create a case from an uploaded 訴願書 (+ optional 行政處分函),
seeding facts via rule-based extraction. See caseapi/domain/appeal_extraction.py
for why only the appeal letter is auto-extracted (fixed format) and the
disposition letter is stored but not parsed (no fixed format).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REAL_SAMPLE_DIR = (
    Path(__file__).resolve().parents[2] / 'data' / 'raw' / '訴願書予行政處分函-1'
)
REAL_APPEAL_PDF = REAL_SAMPLE_DIR / '案01_金管會不予洗錢防制登記_1155000434__訴願書.pdf'
REAL_DISPOSITION_PDF = (
    REAL_SAMPLE_DIR / '案01_金管會不予洗錢防制登記_1155000434__行政處分函.pdf'
)


def _minimal_pdf_bytes(text: str = 'x') -> bytes:
    """A tiny valid one-page PDF, built at test time so fast tests don't
    depend on external sample files."""
    fitz = pytest.importorskip('fitz')
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _intake(
    client: TestClient,
    *,
    appeal_bytes: bytes,
    disposition_bytes: bytes | None = None,
    title: str | None = None,
    key: str = 'intake-key-1',
):
    files = {'appeal_pdf': ('appeal.pdf', appeal_bytes, 'application/pdf')}
    if disposition_bytes is not None:
        files['disposition_pdf'] = ('disposition.pdf', disposition_bytes, 'application/pdf')
    data = {'title': title} if title is not None else {}
    return client.post(
        '/api/v1/cases/intake',
        files=files,
        data=data,
        headers={'Idempotency-Key': key},
    )


@pytest.mark.skipif(not REAL_APPEAL_PDF.exists(), reason='real sample corpus not present')
def test_intake_extracts_real_fields_from_a_real_appeal_letter(client: TestClient) -> None:
    # Arrange
    appeal_bytes = REAL_APPEAL_PDF.read_bytes()
    disposition_bytes = REAL_DISPOSITION_PDF.read_bytes()

    # Act
    response = _intake(client, appeal_bytes=appeal_bytes, disposition_bytes=disposition_bytes)

    # Assert
    assert response.status_code == 201
    data = response.json()['data']
    case_id = data['case_id']
    assert data['extracted_fields']['appellant.name'] == '絕○○○股份有限公司'
    assert data['extracted_fields']['disposition.authority'] == '金融監督管理委員會'
    assert data['extracted_fields']['disposition.doc_no'] == '金管證券字第1140140639號'
    assert data['extracted_fields']['disposition.date'] == '2025-07-24'

    facts = client.get(f'/api/v1/cases/{case_id}/facts').json()['data']['fields']
    assert facts['appellant.name']['value'] == '絕○○○股份有限公司'
    assert facts['appellant.name']['origin'] == 'program'
    assert facts['appellant.name']['human_asserted'] is False

    case = client.get(f'/api/v1/cases/{case_id}').json()['data']
    assert case['processing_status'] == 'unprocessed'


def test_intake_without_disposition_pdf_still_creates_the_case(client: TestClient) -> None:
    response = _intake(client, appeal_bytes=_minimal_pdf_bytes(), title='測試案件')

    assert response.status_code == 201
    case_id = response.json()['data']['case_id']
    assert client.get(f'/api/v1/cases/{case_id}').json()['data']['title'] == '測試案件'


def test_intake_rejects_a_non_pdf_appeal_file(client: TestClient) -> None:
    response = _intake(client, appeal_bytes=b'not a pdf at all')

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_intake_rejects_an_empty_appeal_file(client: TestClient) -> None:
    response = _intake(client, appeal_bytes=b'')

    assert response.status_code == 422


def test_repeated_intake_with_same_idempotency_key_does_not_create_a_second_case(
    client: TestClient,
) -> None:
    appeal_bytes = _minimal_pdf_bytes()

    first = _intake(client, appeal_bytes=appeal_bytes, key='same-key')
    second = _intake(client, appeal_bytes=appeal_bytes, key='same-key')

    assert first.json()['data']['case_id'] == second.json()['data']['case_id']
    assert second.headers['Idempotency-Replayed'] == 'true'
    all_cases = client.get('/api/v1/cases').json()['data']['items']
    assert len(all_cases) == 1


def test_intake_with_no_extractable_fields_creates_case_without_facts(
    client: TestClient,
) -> None:
    response = _intake(client, appeal_bytes=_minimal_pdf_bytes('completely unrelated text'))

    assert response.status_code == 201
    case_id = response.json()['data']['case_id']
    facts = client.get(f'/api/v1/cases/{case_id}/facts').json()['data']['fields']
    assert facts == {}
