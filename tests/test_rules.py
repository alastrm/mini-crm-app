import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest

from app import main


@pytest.mark.parametrize(
    "start_at,expected_status",
    [
        ("2026-11-23T04:00:00Z", 201),  # 09:00 Almaty
        ("2026-11-23T12:00:00Z", 201),  # 17:00 Almaty
        ("2026-11-23T12:30:00Z", 422),  # 17:30 Almaty
        ("2026-11-23T13:00:00Z", 422),  # 18:00 Almaty
        ("2026-11-23T03:59:00Z", 422),  # 08:59 Almaty
        ("2026-11-23T18:30:00Z", 422),  # Ends on the next local day
        ("2026-11-28T05:00:00Z", 422),  # Saturday
    ],
)
def test_working_hours_boundaries(client, company, start_at, expected_status):
    response = client.post(
        "/meetings",
        json={"company_id": company["id"], "manager_id": 1, "start_at": start_at},
    )
    assert response.status_code == expected_status
    if expected_status == 422:
        assert response.json()["detail"]


def test_manager_cannot_have_overlapping_meetings(client, other_company, meeting):
    response = client.post(
        "/meetings",
        json={"company_id": other_company["id"], "manager_id": 1, "start_at": "2026-11-23T05:30:00Z"},
    )
    assert response.status_code == 409
    assert "Manager" in response.json()["detail"]
    assert client.get("/managers/1/schedule", params={"date": "2026-11-23"}).json() == [meeting]


def test_company_cannot_overlap_even_with_different_managers(client, company, meeting):
    response = client.post(
        "/meetings",
        json={"company_id": company["id"], "manager_id": 2, "start_at": "2026-11-23T05:30:00Z"},
    )
    assert response.status_code == 409
    assert "Company" in response.json()["detail"]
    assert client.get("/managers/2/schedule", params={"date": "2026-11-23"}).json() == []


def test_adjacent_meetings_do_not_conflict(client, company, meeting):
    response = client.post(
        "/meetings",
        json={"company_id": company["id"], "manager_id": 1, "start_at": "2026-11-23T06:00:00Z"},
    )
    assert response.status_code == 201
    schedule = client.get("/managers/1/schedule", params={"date": "2026-11-23"}).json()
    assert [row["id"] for row in schedule] == [meeting["id"], response.json()["id"]]


def test_distinct_companies_and_managers_can_meet_at_same_time(client, other_company, meeting):
    response = client.post(
        "/meetings",
        json={"company_id": other_company["id"], "manager_id": 2, "start_at": meeting["start_at"]},
    )
    assert response.status_code == 201


@pytest.mark.parametrize("same_company", [False, True])
def test_reschedule_checks_manager_and_company_conflicts(
    client, company, other_company, meeting, same_company
):
    response = client.post(
        "/meetings",
        json={
            "company_id": company["id"] if same_company else other_company["id"],
            "manager_id": 2 if same_company else 1,
            "start_at": "2026-11-23T07:00:00Z",
        },
    )
    assert response.status_code == 201
    original = response.json()
    response = client.patch(
        f"/meetings/{original['id']}", json={"start_at": "2026-11-23T05:30:00Z"}
    )
    assert response.status_code == 409
    assert ("Company" if same_company else "Manager") in response.json()["detail"]
    schedule = client.get(
        f"/managers/{original['manager_id']}/schedule", params={"date": "2026-11-23"}
    ).json()
    assert original in schedule


def test_reschedule_ignores_its_own_old_slot(client, meeting):
    response = client.patch(
        f"/meetings/{meeting['id']}", json={"start_at": "2026-11-23T05:30:00Z"}
    )
    assert response.status_code == 200
    assert response.json()["start_at"] == "2026-11-23T05:30:00Z"
    assert response.json()["original_start_at"] == meeting["original_start_at"]


@pytest.mark.parametrize("start_at", ["2026-11-23T12:30:00Z", "2026-11-28T05:00:00Z"])
def test_reschedule_also_checks_working_hours(client, meeting, start_at):
    response = client.patch(f"/meetings/{meeting['id']}", json={"start_at": start_at})
    assert response.status_code == 422
    assert client.get("/managers/1/schedule", params={"date": "2026-11-23"}).json() == [meeting]


def test_cancelled_meeting_frees_slot(client, company, meeting):
    assert client.patch(f"/meetings/{meeting['id']}", json={"status": "cancelled"}).status_code == 200
    response = client.post(
        "/meetings",
        json={"company_id": company["id"], "manager_id": 1, "start_at": meeting["start_at"]},
    )
    assert response.status_code == 201
    assert response.json()["id"] != meeting["id"]
    assert client.get("/managers/1/schedule", params={"date": "2026-11-23"}).json() == [response.json()]


def test_schedule_uses_local_midnight_boundaries(client, company, database_path):
    # Legacy rows outside office hours distinguish the local day from the UTC day.
    with closing(sqlite3.connect(database_path)) as connection:
        for start_at in ["2026-11-22T19:00:00.000000+00:00", "2026-11-23T19:00:00.000000+00:00"]:
            connection.execute(
                "INSERT INTO meetings (company_id, manager_id, start_at, original_start_at, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (company["id"], 1, start_at, start_at, start_at),
            )
        connection.commit()
    response = client.get("/managers/1/schedule", params={"date": "2026-11-23"})
    assert response.status_code == 200
    assert [row["start_at"] for row in response.json()] == ["2026-11-22T19:00:00Z"]


@pytest.mark.parametrize("action", ["create", "reschedule"])
def test_concurrent_requests_use_separate_connections_and_cannot_double_book(
    client, company, monkeypatch, action
):
    requests = []
    for manager_id in [1, 2]:
        if action == "create":
            requests.append(("POST", "/meetings", {
                "company_id": company["id"], "manager_id": manager_id,
                "start_at": "2026-11-23T05:00:00Z",
            }))
        else:
            response = client.post("/meetings", json={
                "company_id": company["id"], "manager_id": manager_id,
                "start_at": "2026-11-23T04:00:00Z" if manager_id == 1 else "2026-11-23T06:00:00Z",
            })
            assert response.status_code == 201
            requests.append(("PATCH", f"/meetings/{response.json()['id']}", {
                "start_at": "2026-11-23T05:00:00Z",
            }))

    barrier = Barrier(2)
    connections = []
    original_get_connection = main.get_connection

    def simultaneous_connection():
        connection = original_get_connection()
        connections.append(connection)
        barrier.wait(timeout=5)
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(main, "get_connection", simultaneous_connection)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(client.request, method, path, json=body) for method, path, body in requests]
            responses = [future.result(timeout=10) for future in futures]

    assert len(connections) == 2
    assert connections[0] is not connections[1]
    assert sorted(response.status_code for response in responses) == [201 if action == "create" else 200, 409]
    meetings = []
    for manager_id in [1, 2]:
        meetings.extend(client.get(f"/managers/{manager_id}/schedule", params={"date": "2026-11-23"}).json())
    assert sum(meeting["start_at"] == "2026-11-23T05:00:00Z" for meeting in meetings) == 1
    assert len(meetings) == (1 if action == "create" else 2)


def test_database_lock_returns_503_and_recovers(client, company, database_path):
    payload = {"company_id": company["id"], "manager_id": 1, "start_at": "2026-11-23T05:00:00Z"}
    with closing(sqlite3.connect(database_path)) as locked_connection:
        locked_connection.execute("BEGIN IMMEDIATE")
        try:
            response = client.post("/meetings", json=payload)
        finally:
            locked_connection.rollback()
    assert response.status_code == 503
    assert "busy" in response.json()["detail"].lower()
    assert response.headers["Retry-After"] == "1"
    assert client.post("/meetings", json=payload).status_code == 201
