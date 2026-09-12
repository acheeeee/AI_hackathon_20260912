"""Reading back the original uploaded PDFs for the case-detail "原檔展開" view."""

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


def _intake_with_both_documents(client: TestClient) -> str:
    response = client.post(
        '/api/v1/cases/intake',
        files={
            'appeal_pdf': ('appeal.pdf', REAL_APPEAL_PDF.read_bytes(), 'application/pdf'),
            'disposition_pdf': (
                'disposition.pdf',
                REAL_DISPOSITION_PDF.read_bytes(),
                'application/pdf',
            ),
        },
        headers={'Idempotency-Key': 'intake-doc-test'},
    )
    assert response.status_code == 201
    return response.json()['data']['case_id']


@pytest.mark.skipif(not REAL_APPEAL_PDF.exists(), reason='real sample corpus not present')
def test_lists_both_uploaded_documents_without_their_bytes(client: TestClient) -> None:
    case_id = _intake_with_both_documents(client)

    response = client.get(f'/api/v1/cases/{case_id}/documents')

    assert response.status_code == 200
    items = response.json()['data']['items']
    assert {item['document_role'] for item in items} == {'appeal', 'disposition'}
    for item in items:
        assert 'content_blob' not in item
        assert item['page_count'] >= 1
        assert item['source_filename']


@pytest.mark.skipif(not REAL_APPEAL_PDF.exists(), reason='real sample corpus not present')
def test_reads_back_the_exact_original_pdf_bytes(client: TestClient) -> None:
    case_id = _intake_with_both_documents(client)
    documents = client.get(f'/api/v1/cases/{case_id}/documents').json()['data']['items']
    appeal_doc = next(d for d in documents if d['document_role'] == 'appeal')

    response = client.get(
        f'/api/v1/cases/{case_id}/documents/{appeal_doc["document_id"]}/content'
    )

    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.content == REAL_APPEAL_PDF.read_bytes()


def test_document_from_another_case_is_not_reachable(client: TestClient) -> None:
    case_a = _intake_with_both_documents(client) if REAL_APPEAL_PDF.exists() else None
    if case_a is None:
        pytest.skip('real sample corpus not present')
    other_response = client.post(
        '/api/v1/cases',
        json={'title': '另一案'},
        headers={'Idempotency-Key': 'other-case'},
    )
    case_b = other_response.json()['data']['case_id']
    documents = client.get(f'/api/v1/cases/{case_a}/documents').json()['data']['items']
    doc_id = documents[0]['document_id']

    response = client.get(f'/api/v1/cases/{case_b}/documents/{doc_id}/content')

    assert response.status_code == 404


def test_unknown_document_id_returns_404(client: TestClient) -> None:
    response = client.post(
        '/api/v1/cases', json={'title': 't'}, headers={'Idempotency-Key': 'k1'}
    )
    case_id = response.json()['data']['case_id']

    response = client.get(f'/api/v1/cases/{case_id}/documents/doc_missing/content')

    assert response.status_code == 404
