"""Upload intake: create a case from an uploaded 訴願書 (+ optional 行政處分函),
seeding facts via rule-based extraction. See caseapi/domain/appeal_extraction.py
for why only the appeal letter is auto-extracted (fixed format) and the
disposition letter is stored but not parsed (no fixed format).
"""

import io
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from caseapi.ai.agentcore_provider import AgentCoreModelProvider
from caseapi.config import Settings
from caseapi.main import create_app
from caseapi.services import intake_service

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
    consent_to_online_analysis: bool = False,
):
    files = {'appeal_pdf': ('appeal.pdf', appeal_bytes, 'application/pdf')}
    if disposition_bytes is not None:
        files['disposition_pdf'] = ('disposition.pdf', disposition_bytes, 'application/pdf')
    data: dict[str, str] = {}
    if title is not None:
        data['title'] = title
    if consent_to_online_analysis:
        data['consent_to_online_analysis'] = 'true'
    return client.post(
        '/api/v1/cases/intake',
        files=files,
        data=data,
        headers={'Idempotency-Key': key},
    )


class _FakeAgentCoreClient:
    def __init__(self, *, answer: str, before_response=None) -> None:
        self.answer = answer
        self.before_response = before_response
        self.calls: list[dict[str, Any]] = []

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.before_response is not None:
            self.before_response()
        body = json.dumps({'response': self.answer}).encode('utf-8')
        return {'response': io.BytesIO(body)}


def _agentcore_provider(fake_client: _FakeAgentCoreClient) -> AgentCoreModelProvider:
    return AgentCoreModelProvider(
        runtime_arn='arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/test',
        region='us-west-2',
        client=fake_client,
    )


def _agentcore_client(
    tmp_path: Path, fake_client: _FakeAgentCoreClient
) -> TestClient:
    settings = Settings(
        db_path=tmp_path / 'agentcore-intake.db',
        actor_id='actor_test',
        model_provider='agentcore',
        agentcore_runtime_arn='arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/test',
        agentcore_region='us-west-2',
    )
    return TestClient(create_app(settings, model_provider=_agentcore_provider(fake_client)))


def _valid_analysis_json() -> str:
    return json.dumps(
        {
            'keywords': '行政處分、程序審查',
            'statute_query': '行政處分 程序',
            'disposition_summary': None,
        },
        ensure_ascii=False,
    )


def test_agentcore_intake_requires_explicit_per_request_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeAgentCoreClient(answer=_valid_analysis_json())
    monkeypatch.setattr(
        intake_service,
        'extract_pdf_text',
        lambda _content: ('事實：本件涉及行政處分及訴願期間。', 1),
    )

    with _agentcore_client(tmp_path, fake) as client:
        response = _intake(
            client,
            appeal_bytes=_minimal_pdf_bytes('事實：本件涉及行政處分及訴願期間。'),
            key='agentcore-no-consent',
        )

        assert response.status_code == 201
        assert fake.calls == []
        data = response.json()['data']
        assert data['analysis_status'] == 'offline'
        assert data['analysis_error'] is None
        assert client.get(f'/api/v1/cases/{data["case_id"]}').status_code == 200
        facts = client.get(f'/api/v1/cases/{data["case_id"]}/facts').json()['data']['fields']
        assert facts['analysis.keywords']['source']['provider'] == 'fixed'


def test_agentcore_intake_with_explicit_consent_runs_outside_write_transaction(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / 'agentcore-intake.db'

    def assert_writer_is_not_held() -> None:
        probe = sqlite3.connect(db_path, isolation_level=None, timeout=0)
        try:
            probe.execute('BEGIN IMMEDIATE')
            probe.execute('ROLLBACK')
        finally:
            probe.close()

    fake = _FakeAgentCoreClient(
        answer=_valid_analysis_json(), before_response=assert_writer_is_not_held
    )
    appeal_bytes = _minimal_pdf_bytes('事實：本件涉及行政處分及訴願期間。')

    with _agentcore_client(tmp_path, fake) as client:
        first = _intake(
            client,
            appeal_bytes=appeal_bytes,
            key='agentcore-with-consent',
            consent_to_online_analysis=True,
        )
        replay = _intake(
            client,
            appeal_bytes=appeal_bytes,
            key='agentcore-with-consent',
            consent_to_online_analysis=True,
        )
        facts = client.get(
            f'/api/v1/cases/{first.json()["data"]["case_id"]}/facts'
        ).json()['data']['fields']

    assert first.status_code == 201
    assert first.json()['data']['analysis_status'] == 'online_completed'
    assert first.json()['data']['analysis_error'] is None
    assert facts['analysis.keywords']['source']['provider'] == 'agentcore'
    assert replay.status_code == 201
    assert replay.headers['Idempotency-Replayed'] == 'true'
    assert len(fake.calls) == 1


@pytest.mark.parametrize('failure_kind', ['malformed', 'timeout'])
def test_agentcore_intake_failure_falls_back_and_still_persists_upload(
    tmp_path: Path, failure_kind: str
) -> None:
    def timeout() -> None:
        raise TimeoutError('simulated provider timeout with private infrastructure detail')

    fake = _FakeAgentCoreClient(
        answer='not valid intake JSON',
        before_response=timeout if failure_kind == 'timeout' else None,
    )

    with _agentcore_client(tmp_path, fake) as client:
        response = _intake(
            client,
            appeal_bytes=_minimal_pdf_bytes('事實：本件涉及行政處分及訴願期間。'),
            key=f'agentcore-{failure_kind}-result',
            consent_to_online_analysis=True,
        )

        assert response.status_code == 201
        data = response.json()['data']
        assert data['analysis_status'] == 'online_failed_fallback'
        assert data['analysis_error'] == (
            '線上分析未完成，已改用本機分析；案件與原始檔案已保存。'
        )
        documents = client.get(f'/api/v1/cases/{data["case_id"]}/documents')
        assert documents.status_code == 200
        assert len(documents.json()['data']['items']) == 1


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


@pytest.mark.skipif(
    not (REAL_APPEAL_PDF.exists() and REAL_DISPOSITION_PDF.exists()),
    reason='real sample corpus not present',
)
def test_intake_generates_reviewable_case_keywords_and_disposition_summary(
    client: TestClient,
) -> None:
    """AI enrichments are suggestions, not silently promoted case facts.

    The fixed provider is the deterministic mock for this contract.  The UI still
    needs provenance and the explicit not-legally-reviewed state even in mock mode.
    """
    response = _intake(
        client,
        appeal_bytes=REAL_APPEAL_PDF.read_bytes(),
        disposition_bytes=REAL_DISPOSITION_PDF.read_bytes(),
        key='intake-with-generated-analysis',
    )

    assert response.status_code == 201
    data = response.json()['data']
    facts = client.get(f'/api/v1/cases/{data["case_id"]}/facts').json()['data']['fields']
    assert {
        'analysis.keywords',
        'disposition.summary',
        'analysis.statute_query',
    } <= facts.keys()

    for path in ('analysis.keywords', 'disposition.summary', 'analysis.statute_query'):
        assert facts[path]['origin'] == 'llm'
        assert facts[path]['human_asserted'] is False
        assert facts[path]['legal_review_status'] == 'not_reviewed'
        assert facts[path]['source']['provider'] == 'fixed'

    keywords = facts['analysis.keywords']['value']
    assert isinstance(keywords, str) and keywords.strip()
    assert len(keywords) <= 120
    assert '洗錢防制' in keywords
    assert '訴願人於' not in keywords

    summary = facts['disposition.summary']['value']
    assert isinstance(summary, str) and summary.strip()
    assert '不予登記' in summary or '未予登記' in summary
    assert not any(
        unsupported in summary
        for unsupported in ('本訴願駁回', '訴願不受理', '原處分應予撤銷')
    )

    statute_query = facts['analysis.statute_query']['value']
    assert isinstance(statute_query, str) and statute_query.strip()
    assert len(statute_query) <= 80
    assert '洗錢防制' in statute_query
    assert '訴願人於' not in statute_query


@pytest.mark.skipif(not REAL_APPEAL_PDF.exists(), reason='real sample corpus not present')
def test_editing_generated_analysis_does_not_silently_mark_it_legally_reviewed(
    client: TestClient,
) -> None:
    intake = _intake(
        client,
        appeal_bytes=REAL_APPEAL_PDF.read_bytes(),
        key='intake-edit-generated-analysis',
    ).json()['data']

    response = client.patch(
        f'/api/v1/cases/{intake["case_id"]}/facts',
        json={
            'expected_case_revision': intake['case_revision'],
            'reason': '人工修正關鍵字文字',
            'field_changes': [
                {
                    'field_path': 'analysis.keywords',
                    'value': '洗錢防制登記、比例原則',
                    'human_asserted': True,
                    'reason': '刪除不相關關鍵字',
                }
            ],
        },
        headers={'Idempotency-Key': 'edit-generated-analysis'},
    )

    assert response.status_code == 200
    field = response.json()['data']['fields']['analysis.keywords']
    assert field['origin'] == 'human'
    assert field['legal_review_status'] == 'not_reviewed'


def test_intake_without_disposition_pdf_still_creates_the_case(client: TestClient) -> None:
    response = _intake(client, appeal_bytes=_minimal_pdf_bytes(), title='測試案件')

    assert response.status_code == 201
    data = response.json()['data']
    case_id = data['case_id']
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
