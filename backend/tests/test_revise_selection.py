"""選取局部修改（intent=revise_selection）：候選只能落在選取範圍內，且未採用前正文不變。

模型輸出的安全閘門（危險字樣阻擋）在 provider 層測試，見
test_revise_selection_providers.py；這裡只覆蓋 HTTP／DB 這一層的行為。
"""

import hashlib

from fastapi.testclient import TestClient

from caseapi.ai.fixed_provider import FixedModelProvider
from caseapi.main import create_app

from conftest import create_case, create_draft, mutate

PHRASE = '原處分機關認事用法並無違誤'


class _NoopEvidenceRepository:
    release_id = 'r3'

    def search(self, query, **_):
        del query
        return []

    def open_source(self, chunk_id):
        raise AssertionError('revise_selection must not open sources for a wording candidate')


def _client(settings, *, model_provider) -> TestClient:
    return TestClient(
        create_app(
            settings,
            evidence_repository=_NoopEvidenceRepository(),
            model_provider=model_provider,
        )
    )


def _create_thread(client: TestClient, case_id: str) -> str:
    response = mutate(client, 'POST', f'/api/v1/cases/{case_id}/chat-threads', {'title': '局部修改'})
    assert response.status_code == 201
    return response.json()['data']['thread_id']


def _send_revise(
    client: TestClient,
    case_id: str,
    thread_id: str,
    *,
    content: str,
    target: dict | None,
    expected_case_revision: int,
    key: str | None = None,
):
    return mutate(
        client,
        'POST',
        f'/api/v1/cases/{case_id}/chat-threads/{thread_id}/messages',
        {
            'expected_case_revision': expected_case_revision,
            'content': content,
            'intent': 'revise_selection',
            'target': target,
            'annotation_refs': [],
        },
        key=key,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _draft_block_target(draft: dict, *, block_id: str, text: str, start: int, end: int) -> dict:
    return {
        'kind': 'draft_block',
        'resource_id': draft['draft_id'],
        'resource_revision': draft['resource_revision'],
        'block_id': block_id,
        'char_start': start,
        'char_end': end,
        'selected_text': text,
        'selected_text_sha256': _sha256(text),
    }


def test_revise_selection_requires_a_draft_block_target(settings) -> None:
    with _client(settings, model_provider=FixedModelProvider()) as client:
        case_id = create_case(client)
        draft = create_draft(client, case_id)
        thread_id = _create_thread(client, case_id)

        response = _send_revise(
            client,
            case_id,
            thread_id,
            content='改得更正式',
            target=None,
            expected_case_revision=draft['case_revision'],
        )

        assert response.status_code == 422
        assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_revise_selection_rejects_a_fact_field_target(settings) -> None:
    """驗證發生在請求層級（pydantic），不用真的先建立 facts 資源版本。"""
    with _client(settings, model_provider=FixedModelProvider()) as client:
        case_id = create_case(client)
        draft = create_draft(client, case_id)
        thread_id = _create_thread(client, case_id)

        response = _send_revise(
            client,
            case_id,
            thread_id,
            content='改得更正式',
            target={
                'kind': 'fact_field',
                'resource_id': 'facts',
                'resource_revision': 'res_fake',
                'field_path': 'appellant.name',
            },
            expected_case_revision=draft['case_revision'],
        )

        assert response.status_code == 422
        assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_revise_selection_scopes_a_local_proposal_to_the_second_occurrence(settings) -> None:
    with _client(settings, model_provider=FixedModelProvider()) as client:
        case_id = create_case(client)
        block_text = f'{PHRASE}。{PHRASE}，故本件無理由。'
        draft = create_draft(
            client, case_id, blocks=[{'block_id': 'reason-1', 'text': block_text}]
        )
        thread_id = _create_thread(client, case_id)

        second_start = block_text.index(PHRASE, block_text.index(PHRASE) + 1)
        second_end = second_start + len(PHRASE)
        target = _draft_block_target(
            draft, block_id='reason-1', text=PHRASE, start=second_start, end=second_end
        )

        response = _send_revise(
            client,
            case_id,
            thread_id,
            content='把這一句改得更正式',
            target=target,
            expected_case_revision=draft['case_revision'],
        )

        assert response.status_code == 202
        run_id = response.json()['data']['run_id']

        run = client.get(f'/api/v1/cases/{case_id}/runs/{run_id}').json()['data']
        assert run['state'] == 'completed'
        assert run['proposal_ids']

        proposal = client.get(
            f'/api/v1/cases/{case_id}/proposals/{run["proposal_ids"][0]}'
        ).json()['data']
        assert proposal['mode'] == 'local'
        assert len(proposal['change_groups']) == 1
        group = proposal['change_groups'][0]
        assert len(group['operations']) == 1
        operation = group['operations'][0]
        assert operation['op'] == 'replace_text'
        assert operation['target']['block_id'] == 'reason-1'
        assert operation['target']['char_start'] == second_start
        assert operation['target']['char_end'] == second_end

        resource = client.get(
            f'/api/v1/cases/{case_id}/resources/{draft["draft_id"]}'
        ).json()['data']
        assert resource['content']['blocks'][0]['text'] == block_text


