"""選法規：對真的 r3 語料做 BM25 搜尋，人工從結果裡挑選要用的法規存起來。

搜尋本身不寫 evidence——這是人工瀏覽候選，不是 AI 工具呼叫；只有之後
真的被拿去當草稿依據時才需要走 open_source 驗證鏈（見 06 §3 規則 14）。
預設查詢字串來自訴願書的事實／理由段落（`extract_case_narrative`），
不是整份文件也不是憑空生成。
"""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from caseapi.evidence.repository import SearchHit
from caseapi.main import create_app

from conftest import create_case, mutate

REAL_APPEAL_PDF = (
    Path(__file__).resolve().parents[2]
    / 'data'
    / 'raw'
    / '訴願書予行政處分函-1'
    / '案01_金管會不予洗錢防制登記_1155000434__訴願書.pdf'
)


class RecordingStatuteRepository:
    """One partial BM25 hit plus a complete, separately opened article section."""

    release_id = 'r3'

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.opened_sections: list[str] = []

    def search(self, query: str, **_: object) -> list[SearchHit]:
        self.queries.append(query)
        return [
            SearchHit(
                release_id='r3',
                chunk_id='chk_aml_6_partial',
                document_id='doc_aml',
                section_id='sec_aml_6',
                document_type='statute',
                case_family_id=None,
                excerpt='第 6 條\n提供虛擬資產服務之事業未完成登記者，不得提供服務。',
                source_spans=(),
                metadata={'statute_name': '洗錢防制法', 'article_key': '6'},
                score=9.25,
                index_eligible=True,
            )
        ]

    def open_section_text(self, section_id: str) -> str:
        self.opened_sections.append(section_id)
        return (
            '第 6 條\n'
            '一、提供虛擬資產服務之事業未完成洗錢防制登記者，不得提供服務。\n'
            '二、申請條件、程序、撤銷或廢止登記及其他應遵行事項，由主管機關定之。\n'
            '三、違反規定者，依本條所定法律效果處理。'
        )


def _intake_real_case(client: TestClient) -> str:
    response = client.post(
        '/api/v1/cases/intake',
        files={'appeal_pdf': ('appeal.pdf', REAL_APPEAL_PDF.read_bytes(), 'application/pdf')},
        headers={'Idempotency-Key': 'intake-for-statute-search'},
    )
    assert response.status_code == 201
    return response.json()['data']['case_id']


@pytest.mark.skipif(not REAL_APPEAL_PDF.exists(), reason='real sample corpus not present')
def test_search_with_no_query_returns_the_generated_compact_case_query(
    client: TestClient,
) -> None:
    case_id = _intake_real_case(client)

    response = client.get(f'/api/v1/cases/{case_id}/statute-search')

    assert response.status_code == 200
    data = response.json()['data']
    assert data['query_used']
    assert '洗錢防制' in data['query_used']
    assert len(data['query_used']) <= 80
    assert '訴願人於' not in data['query_used']
    assert isinstance(data['hits'], list)


@pytest.mark.skipif(not REAL_APPEAL_PDF.exists(), reason='real sample corpus not present')
def test_search_with_an_explicit_query_overrides_the_default(client: TestClient) -> None:
    case_id = _intake_real_case(client)

    response = client.get(
        f'/api/v1/cases/{case_id}/statute-search', params={'q': '訴願三十日期間'}
    )

    data = response.json()['data']
    assert data['query_used'] == '訴願三十日期間'
    for hit in data['hits']:
        assert hit['chunk_id']
        assert hit['statute_name']


def test_search_hit_contains_expandable_full_article_reason_and_official_link(
    settings,
) -> None:
    repository = RecordingStatuteRepository()
    with TestClient(create_app(settings, evidence_repository=repository)) as client:
        case_id = create_case(client)

        response = client.get(
            f'/api/v1/cases/{case_id}/statute-search',
            params={'q': '洗錢防制 登記'},
        )

    assert response.status_code == 200
    hit = response.json()['data']['hits'][0]
    assert hit['excerpt'].endswith('不得提供服務。')
    assert hit['full_text'].startswith('第 6 條')
    assert '申請條件、程序、撤銷或廢止登記' in hit['full_text']
    assert hit['full_text'] != hit['excerpt']
    assert repository.opened_sections == ['sec_aml_6']

    assert hit['why_relevant']
    assert '洗錢防制' in hit['why_relevant']
    assert '登記' in hit['why_relevant']
    assert hit['why_relevant'] != hit['excerpt']
    assert hit['why_relevant_origin'] in {'ai', 'rule'}
    if hit['why_relevant_origin'] == 'ai':
        assert hit['why_relevant_provider']
    assert hit['legal_review_status'] == 'not_reviewed'

    official = urlparse(hit['official_url'])
    assert official.scheme == 'https'
    assert official.netloc == 'law.moj.gov.tw'
    assert official.path == '/LawClass/LawSingle.aspx'
    assert parse_qs(official.query) == {'pcode': ['G0380131'], 'flno': ['6']}


@pytest.mark.skipif(not REAL_APPEAL_PDF.exists(), reason='real sample corpus not present')
def test_default_search_shows_compact_keywords_but_uses_narrative_in_background(
    settings,
) -> None:
    repository = RecordingStatuteRepository()
    with TestClient(create_app(settings, evidence_repository=repository)) as client:
        case_id = _intake_real_case(client)
        facts = client.get(f'/api/v1/cases/{case_id}/facts').json()['data']['fields']

        response = client.get(f'/api/v1/cases/{case_id}/statute-search')

    assert response.status_code == 200
    data = response.json()['data']
    assert data['query_used'] == facts['analysis.statute_query']['value']
    assert len(data['query_used']) <= 80
    assert '洗錢防制' in data['query_used']
    assert '訴願人於' not in data['query_used']
    assert 'background_query' not in data

    assert len(repository.queries) == 1
    background_query = repository.queries[0]
    assert '訴願人於' in background_query
    assert '洗錢防制法第6條' in background_query
    assert len(background_query) > len(data['query_used'])


def test_search_without_an_appeal_document_and_no_query_returns_empty(
    client: TestClient,
) -> None:
    case_id = create_case(client)

    response = client.get(f'/api/v1/cases/{case_id}/statute-search')

    data = response.json()['data']
    assert data['query_used'] is None
    assert data['hits'] == []


def test_selection_starts_empty(client: TestClient) -> None:
    case_id = create_case(client)

    response = client.get(f'/api/v1/cases/{case_id}/statute-selection')

    assert response.status_code == 200
    assert response.json()['data']['selected'] == []


def test_saving_a_selection_persists_it_and_bumps_case_revision(client: TestClient) -> None:
    case_id = create_case(client)
    selected = [
        {
            'chunk_id': 'chk_law_14',
            'document_id': 'doc_law',
            'section_id': 'sec_law_14',
            'statute_name': '訴願法',
            'article_key': '14',
            'excerpt': '訴願之提起，應自行政處分達到或公告期滿之次日起三十日內為之。',
        }
    ]

    response = mutate(
        client,
        'PUT',
        f'/api/v1/cases/{case_id}/statute-selection',
        {'expected_case_revision': 1, 'reason': '人工挑選相關法規', 'selected': selected},
    )

    assert response.status_code == 200
    data = response.json()['data']
    assert data['case_revision'] == 2
    assert data['selected'] == selected

    read_back = client.get(f'/api/v1/cases/{case_id}/statute-selection')
    assert read_back.json()['data']['selected'] == selected


def test_saving_a_second_selection_replaces_the_first(client: TestClient) -> None:
    case_id = create_case(client)
    first = [
        {
            'chunk_id': 'chk_a',
            'document_id': 'doc_a',
            'section_id': 'sec_a',
            'statute_name': '訴願法',
            'article_key': '14',
            'excerpt': 'x',
        }
    ]
    second = [
        {
            'chunk_id': 'chk_b',
            'document_id': 'doc_b',
            'section_id': 'sec_b',
            'statute_name': '行政程序法',
            'article_key': '48',
            'excerpt': 'y',
        }
    ]
    mutate(
        client,
        'PUT',
        f'/api/v1/cases/{case_id}/statute-selection',
        {'expected_case_revision': 1, 'reason': '第一次挑選', 'selected': first},
    )

    response = mutate(
        client,
        'PUT',
        f'/api/v1/cases/{case_id}/statute-selection',
        {'expected_case_revision': 2, 'reason': '換一批', 'selected': second},
    )

    assert response.json()['data']['selected'] == second


def test_saving_a_selection_with_a_stale_case_revision_is_a_conflict(
    client: TestClient,
) -> None:
    case_id = create_case(client)

    response = mutate(
        client,
        'PUT',
        f'/api/v1/cases/{case_id}/statute-selection',
        {'expected_case_revision': 99, 'reason': '過期版本', 'selected': []},
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'
