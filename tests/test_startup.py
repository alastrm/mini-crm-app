import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def database_path(tmp_path, monkeypatch):
    path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("CRM_DB_PATH", str(path))
    return path


def test_startup_creates_schema_and_opens_docs(database_path):
    assert not database_path.exists()

    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").json()["info"]["title"] == "Mini CRM"

    with closing(sqlite3.connect(database_path)) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        assert {row[0] for row in tables} == {
            "companies", "managers", "meetings", "calls"
        }
        assert connection.execute("SELECT id FROM managers ORDER BY id").fetchall() == [
            (1,), (2,)
        ]


def test_restart_keeps_data_and_does_not_duplicate_managers(database_path):
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "INSERT INTO companies (name, bin, phone) VALUES (?, ?, ?)",
            ("Example company", "123456789012", "+77001234567"),
        )
        connection.commit()

    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200

    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("SELECT name FROM companies").fetchall() == [
            ("Example company",)
        ]
        assert connection.execute("SELECT count(*) FROM managers").fetchone()[0] == 2
