import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def database_path(tmp_path, monkeypatch):
    path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("CRM_DB_PATH", str(path))
    return path


@pytest.fixture
def client(database_path):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def company(client):
    response = client.post(
        "/companies",
        json={"name": "Example company", "bin": "123456789012", "phone": "+77001234567"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def meeting(client, company):
    response = client.post(
        "/meetings",
        json={"company_id": company["id"], "manager_id": 1, "start_at": "2026-11-23T05:00:00Z"},
    )
    assert response.status_code == 201
    return response.json()
