"""A1 案件端點：envelope、建立／讀取、冪等鍵、稽核。"""

from fastapi.testclient import TestClient

CREATE_BODY = {'title': '示範案件', 'official_case_no': '府訴字第1130000001號'}


def create_case(client: TestClient, key: str = 'key-1', body: dict | None = None):
    return client.post(
        '/api/v1/cases',
        json=CREATE_BODY if body is None else body,
        headers={'Idempotency-Key': key},
    )


def test_create_case_returns_201_with_location_and_first_revision(client: TestClient) -> None:
    # Act
    response = create_case(client)

    # Assert
    assert response.status_code == 201
    payload = response.json()
    assert payload['success'] is True
    assert payload['error'] is None
    assert payload['data']['case_revision'] == 1
    assert payload['data']['workflow_state'] == 'human_review'
    assert payload['meta']['request_id']
    assert response.headers['Location'] == f'/api/v1/cases/{payload["data"]["case_id"]}'


def test_created_case_can_be_read_back(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client).json()['data']['case_id']

    # Act
    response = client.get(f'/api/v1/cases/{case_id}')

    # Assert
    assert response.status_code == 200
    data = response.json()['data']
    assert data['case_id'] == case_id
    assert data['title'] == CREATE_BODY['title']
    assert data['active_heads'] == {}
    assert response.json()['meta']['case_revision'] == 1


def test_unknown_case_returns_404_without_leaking_details(client: TestClient) -> None:
    # Act
    response = client.get('/api/v1/cases/case_does_not_exist')

    # Assert
    assert response.status_code == 404
    payload = response.json()
    assert payload['success'] is False
    assert payload['data'] is None
    assert payload['error']['code'] == 'RESOURCE_NOT_FOUND'
    assert payload['error']['retryable'] is False


def test_missing_idempotency_key_is_rejected(client: TestClient) -> None:
    # Act
    response = client.post('/api/v1/cases', json=CREATE_BODY)

    # Assert
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_replaying_same_key_and_body_returns_the_original_case(client: TestClient) -> None:
    # Arrange
    first = create_case(client, key='key-replay')

    # Act
    second = create_case(client, key='key-replay')

    # Assert
    assert second.status_code == 201
    assert second.json()['data']['case_id'] == first.json()['data']['case_id']
    assert len(client.get('/api/v1/cases').json()['data']['items']) == 1


def test_same_key_with_different_body_returns_409(client: TestClient) -> None:
    # Arrange
    create_case(client, key='key-clash')

    # Act
    response = create_case(client, key='key-clash', body={'title': '另一個案件'})

    # Assert
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'IDEMPOTENCY_KEY_REUSED'


def test_case_list_paginates_with_cursor(client: TestClient) -> None:
    # Arrange
    for index in range(3):
        create_case(client, key=f'key-{index}', body={'title': f'案件 {index}'})

    # Act
    first_page = client.get('/api/v1/cases?limit=2').json()['data']
    second_page = client.get(f'/api/v1/cases?limit=2&cursor={first_page["next_cursor"]}').json()['data']

    # Assert
    assert len(first_page['items']) == 2
    assert first_page['next_cursor'] is not None
    assert len(second_page['items']) == 1
    assert second_page['next_cursor'] is None


def test_list_limit_above_maximum_is_rejected(client: TestClient) -> None:
    # Act
    response = client.get('/api/v1/cases?limit=101')

    # Assert
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INVALID_FIELD'


def test_case_creation_is_recorded_in_the_audit_log(client: TestClient) -> None:
    # Arrange
    case_id = create_case(client).json()['data']['case_id']

    # Act
    response = client.get(f'/api/v1/cases/{case_id}/audit')

    # Assert
    entries = response.json()['data']['items']
    assert [entry['action'] for entry in entries] == ['case.created']
    assert entries[0]['actor_id'] == 'actor_test'
    assert entries[0]['sequence'] == 1


def test_audit_of_unknown_case_returns_404(client: TestClient) -> None:
    # Act
    response = client.get('/api/v1/cases/case_missing/audit')

    # Assert
    assert response.status_code == 404
