import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from caseapi.config import Settings
from caseapi.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / 'caseapi.db', actor_id='actor_test')


@pytest.fixture
def client(settings: Settings) -> TestClient:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def new_key() -> str:
    """每次呼叫給一把新的冪等鍵；要測重送時才自己指定同一把。"""
    return f'key_{uuid4().hex[:12]}'


def mutate(
    client: TestClient,
    method: str,
    url: str,
    body: dict | None = None,
    key: str | None = None,
):
    """送出會改變狀態的請求。契約要求這類請求一律帶 Idempotency-Key。"""
    return client.request(
        method,
        url,
        json=body,
        headers={'Idempotency-Key': key or new_key()},
    )


def create_case(client: TestClient, title: str = '示範案件') -> str:
    response = mutate(client, 'POST', '/api/v1/cases', {'title': title})
    assert response.status_code == 201
    return response.json()['data']['case_id']


def create_draft(client: TestClient, case_id: str, blocks: list[dict] | None = None) -> dict:
    current_revision = client.get(f'/api/v1/cases/{case_id}').json()['data']['case_revision']
    body = {
        'expected_case_revision': current_revision,
        'draft_kind': 'decision',
        'title': '訴願決定書草稿',
        'blocks': blocks
        or [
            {'block_id': 'reason-1', 'text': '原處分機關認事用法並無違誤。'},
            {'block_id': 'reason-2', 'text': '訴願人所訴各節，均難謂有理由。'},
        ],
    }
    response = mutate(client, 'POST', f'/api/v1/cases/{case_id}/drafts', body)
    assert response.status_code == 201
    return response.json()['data']


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def block_target(draft: dict, block_id: str, text: str, base_revision: str | None = None) -> dict:
    """整個區塊當選取範圍的 draft_block target。"""
    return {
        'kind': 'draft_block',
        'resource_id': draft['draft_id'],
        'resource_revision': base_revision or draft['resource_revision'],
        'block_id': block_id,
        'char_start': 0,
        'char_end': len(text),
        'selected_text': text,
        'selected_text_sha256': sha256_of(text),
    }


def replace_text_group(
    draft: dict,
    *,
    block_id: str,
    before_text: str,
    after_text: str,
    group_id: str = 'group_wording_1',
    change_class: str = 'wording',
    depends_on: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    base_revision: str | None = None,
) -> dict:
    return {
        'id': group_id,
        'change_class': change_class,
        'reason': '依使用者要求調整文字',
        'depends_on_group_ids': depends_on or [],
        'evidence_ids': evidence_ids or [],
        'operations': [
            {
                'op': 'replace_text',
                'target': block_target(draft, block_id, before_text, base_revision),
                'after_value': after_text,
            }
        ],
    }


def proposal_body(
    draft: dict,
    *,
    expected_case_revision: int,
    change_groups: list[dict],
    mode: str = 'local',
    target: dict | None = None,
    dependencies: dict | None = None,
    evidence: list[dict] | None = None,
) -> dict:
    return {
        'expected_case_revision': expected_case_revision,
        'origin': 'ai',
        'mode': mode,
        'run_id': 'run_fixture_1',
        'target': target
        or block_target(draft, 'reason-1', '原處分機關認事用法並無違誤。'),
        'dependencies': dependencies or {},
        'evidence': evidence or [],
        'change_groups': change_groups,
    }
