"""草稿 PDF 匯出：只輸出目前 head，且不把內部證據資料混進正文。"""

import fitz
import pytest
from fastapi.testclient import TestClient

from tests.conftest import create_case, create_draft, mutate


def _formal_blocks(*, reason: str = '一、目前理由內容。') -> list[dict]:
    return [
        {
            'block_id': 'index-header-1',
            'text': (
                '訴願決定書\n'
                '案號：（待承辦人填寫）\n'
                '要旨：（待承辦人核定主文後填寫）\n'
                '發文日期：（待承辦人填寫）\n'
                '發文字號：（待承辦人填寫）\n'
                '相關法條：訴願法第 77 條\n'
                '全文：'
            ),
            'citations': ['ev_private_index_1'],
        },
        {
            'block_id': 'body-heading-1',
            'text': '新北市政府訴願決定書\n案號：（待承辦人填寫）號',
            'citations': [],
        },
        {
            'block_id': 'parties-1',
            'text': '訴願人　吳○德\n原處分機關　新北市政府環境保護局',
            'citations': [],
        },
        {
            'block_id': 'main-1',
            'text': '主文\n（待承辦人核定處理結果後填寫）',
            'citations': [],
        },
        {
            'block_id': 'reason-1',
            'text': f'理由\n{reason}',
            'citations': ['ev_private_reason_1'],
        },
    ]


def _open_pdf(response) -> fitz.Document:
    assert response.content.startswith(b'%PDF-')
    return fitz.open(stream=response.content, filetype='pdf')


def test_export_returns_a4_pdf_with_formal_headings_and_embedded_chinese_font(
    client: TestClient,
) -> None:
    case_id = create_case(client)
    draft = create_draft(
        client,
        case_id,
        blocks=_formal_blocks(
            reason='\n'.join(f'{index}、這是供排版驗證的理由段落。' for index in range(1, 181))
        ),
    )

    response = client.get(f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}/pdf')

    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    disposition = response.headers['content-disposition']
    assert disposition.startswith('attachment;')
    assert '\r' not in disposition and '\n' not in disposition
    assert '/' not in disposition and '\\' not in disposition

    with _open_pdf(response) as document:
        assert document.page_count >= 2
        for page in document:
            assert page.rect.width == pytest.approx(595.28, abs=0.5)
            assert page.rect.height == pytest.approx(841.89, abs=0.5)
        text = ''.join(page.get_text() for page in document)
        assert '訴願決定書' in text
        assert '新北市政府訴願決定書' in text
        assert '主文' in text
        assert '待承辦人核定處理結果後填寫' in text
        assert '理由' in text
        assert '180、這是供排版驗證的理由段落。' in text
        assert f'1 / {document.page_count}' in text
        assert f'{document.page_count} / {document.page_count}' in text

        embedded_font_lengths = [
            len(document.extract_font(font[0])[3])
            for page_number in range(document.page_count)
            for font in document.get_page_fonts(page_number, full=True)
        ]
        assert embedded_font_lengths
        assert max(embedded_font_lengths) > 0


def test_export_uses_only_the_formal_body_not_the_search_index_header(
    client: TestClient,
) -> None:
    """The persisted index block is UI metadata, not a second document body."""
    case_id = create_case(client)
    draft = create_draft(client, case_id, blocks=_formal_blocks())

    response = client.get(f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}/pdf')

    assert response.status_code == 200
    with _open_pdf(response) as document:
        text = ''.join(page.get_text() for page in document)
    assert text.count('訴願決定書') == 1
    assert '新北市政府訴願決定書' in text
    assert '要旨：' not in text
    assert '發文日期：' not in text
    assert '發文字號：' not in text
    assert '全文：' not in text


def test_export_reads_only_the_current_persisted_draft_head(client: TestClient) -> None:
    case_id = create_case(client)
    draft = create_draft(
        client,
        case_id,
        blocks=_formal_blocks(reason='一、舊版文字不應再被匯出。'),
    )
    changed = mutate(
        client,
        'PATCH',
        f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}',
        {
            'expected_case_revision': draft['case_revision'],
            'base_resource_revision': draft['resource_revision'],
            'block_changes': [
                {
                    'block_id': 'reason-1',
                    'text': '理由\n一、目前 head 的人工修改。',
                    'citations': ['ev_private_reason_1'],
                }
            ],
        },
    )
    assert changed.status_code == 200

    response = client.get(f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}/pdf')

    assert response.status_code == 200
    with _open_pdf(response) as document:
        text = ''.join(page.get_text() for page in document)
    assert '目前 head 的人工修改' in text
    assert '舊版文字不應再被匯出' not in text
    assert 'ev_private_index_1' not in text
    assert 'ev_private_reason_1' not in text
    assert 'resource_revision' not in text


def test_export_preserves_an_explicit_placeholder_instead_of_inventing_a_decision(
    client: TestClient,
) -> None:
    case_id = create_case(client)
    draft = create_draft(
        client,
        case_id,
        blocks=[
            {
                'block_id': 'main-1',
                'text': '主文\n（待承辦人核定處理結果後填寫）',
                'citations': [],
            }
        ],
    )

    response = client.get(f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}/pdf')

    with _open_pdf(response) as document:
        text = ''.join(page.get_text() for page in document)
    assert '待承辦人核定處理結果後填寫' in text
    assert '訴願不受理' not in text
    assert '訴願駁回' not in text
    assert '原處分撤銷' not in text


def test_export_rejects_a_draft_that_belongs_to_another_case(client: TestClient) -> None:
    case_a = create_case(client, title='案件 A')
    case_b = create_case(client, title='案件 B')
    draft = create_draft(client, case_a, blocks=_formal_blocks())

    response = client.get(f'/api/v1/cases/{case_b}/drafts/{draft["draft_id"]}/pdf')

    assert response.status_code == 404
    assert response.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_export_filename_cannot_inject_headers_or_paths(client: TestClient) -> None:
    case_id = create_case(client)
    draft = create_draft(client, case_id, blocks=_formal_blocks())

    response = client.get(f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}/pdf')

    disposition = response.headers['content-disposition']
    assert '\r' not in disposition and '\n' not in disposition
    assert '..' not in disposition
    assert '/' not in disposition and '\\' not in disposition
    assert disposition.endswith('.pdf"')


def test_export_rejects_an_unrenderable_character_instead_of_silently_corrupting_it(
    client: TestClient,
) -> None:
    case_id = create_case(client)
    draft = create_draft(
        client,
        case_id,
        blocks=[
            {
                'block_id': 'parties-1',
                'text': '訴願人　𠀀○德',
                'citations': [],
            }
        ],
    )

    response = client.get(f'/api/v1/cases/{case_id}/drafts/{draft["draft_id"]}/pdf')

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'
    assert 'U+20000' in response.json()['error']['message']
