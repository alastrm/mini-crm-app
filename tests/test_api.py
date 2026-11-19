import pytest


def test_create_company_and_paginate(client):
    for number in range(1, 4):
        response = client.post(
            "/companies",
            json={
                "name": f"Company {number}",
                "bin": f"{number:012d}",
                "phone": "+77001234567",
            },
        )
        assert response.status_code == 201
        assert response.json()["status"] == "new"

    response = client.get("/companies", params={"page": 2, "page_size": 2})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["page"] == 2
    assert data["page_size"] == 2
    assert [item["name"] for item in data["items"]] == ["Company 3"]
    assert client.get("/companies", params={"status": "refused"}).json()["total"] == 0
    assert client.get("/companies", params={"page": 3}).json()["items"] == []


def test_duplicate_bin_returns_conflict(client, company):
    response = client.post(
        "/companies",
        json={"name": "Another name", "bin": company["bin"], "phone": "+77001234567"},
    )
    assert response.status_code == 409
    assert "BIN" in response.json()["detail"]
    assert client.get("/companies").json()["total"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "   "),
        ("phone", ""),
        ("bin", "123"),
        ("bin", "12345678901a"),
        ("bin", "١٢٣٤٥٦٧٨٩٠١٢"),
        ("status", "refused"),
    ],
)
def test_invalid_company_is_rejected(client, field, value):
    payload = {"name": "Example", "bin": "123456789012", "phone": "+77001234567"}
    payload[field] = value
    assert client.post("/companies", json=payload).status_code == 422
    assert client.get("/companies").json()["total"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": 10**100},
        {"page_size": 0},
        {"page_size": 101},
        {"status": "unknown"},
    ],
)
def test_invalid_company_query_is_rejected(client, params):
    assert client.get("/companies", params=params).status_code == 422


def test_company_name_with_sql_text_is_saved_as_data(client):
    name = "Example'); DROP TABLE companies; --"
    response = client.post(
        "/companies", json={"name": name, "bin": "123456789012", "phone": "+77001234567"}
    )
    assert response.status_code == 201
    assert response.json()["name"] == name
    assert client.get("/companies").json()["items"][0]["name"] == name


def test_call_updates_company_status_and_filter(client, company):
    response = client.post(
        "/calls", json={"company_id": company["id"], "result": "no_answer"}
    )
    assert response.status_code == 201
    call = response.json()
    assert call["company_id"] == company["id"]
    assert call["result"] == "no_answer"
    assert call["meeting_id"] is None
    assert call["created_at"].endswith("Z")
    assert client.get("/companies", params={"status": "no_answer"}).json()["total"] == 1

    response = client.post(
        "/calls", json={"company_id": company["id"], "result": "refused"}
    )
    assert response.status_code == 201
    assert response.json()["id"] != call["id"]
    assert client.get("/companies", params={"status": "refused"}).json()["total"] == 1
    assert client.get("/companies", params={"status": "no_answer"}).json()["total"] == 0


def test_call_with_unknown_company_returns_not_found(client):
    response = client.post("/calls", json={"company_id": 999, "result": "no_answer"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Company not found"


def test_meeting_set_requires_an_existing_meeting(client, company):
    payload = {"company_id": company["id"], "result": "meeting_set"}
    assert client.post("/calls", json=payload).status_code == 422
    payload["meeting_id"] = 999
    assert client.post("/calls", json=payload).status_code == 422
    assert client.get("/companies").json()["items"][0]["status"] == "new"


@pytest.mark.parametrize(
    "changes",
    [
        {"company_id": 0},
        {"company_id": True},
        {"company_id": 1.5},
        {"company_id": 10**100},
        {"result": "unknown"},
        {"meeting_id": 1},
        {"extra_field": "unexpected"},
    ],
)
def test_invalid_call_is_rejected(client, company, changes):
    payload = {"company_id": company["id"], "result": "no_answer"}
    payload.update(changes)
    assert client.post("/calls", json=payload).status_code == 422


def test_schedule_filters_manager_date_and_sorts_by_start(client, company):
    for manager_id, start_at in [
        (1, "2026-11-23T06:00:00Z"),
        (1, "2026-11-23T05:00:00+00:00"),
        (2, "2026-11-23T07:00:00Z"),
        (1, "2026-11-24T05:00:00Z"),
    ]:
        response = client.post(
            "/meetings",
            json={"company_id": company["id"], "manager_id": manager_id, "start_at": start_at},
        )
        assert response.status_code == 201
        assert response.json()["start_at"] == response.json()["original_start_at"]
        assert response.json()["created_at"].endswith("Z")

    response = client.get("/managers/1/schedule", params={"date": "2026-11-23"})
    assert response.status_code == 200
    assert [row["start_at"] for row in response.json()] == [
        "2026-11-23T05:00:00Z", "2026-11-23T06:00:00Z"
    ]
    assert len(client.get("/managers/2/schedule", params={"date": "2026-11-23"}).json()) == 1
    assert len(client.get("/managers/1/schedule", params={"date": "2026-11-24"}).json()) == 1
    assert client.get("/managers/1/schedule", params={"date": "2026-11-25"}).json() == []


def test_reschedule_preserves_original_and_created_at(client, meeting):
    for start_at in ["2026-11-23T06:00:00Z", "2026-11-23T07:00:00+00:00"]:
        response = client.patch(f"/meetings/{meeting['id']}", json={"start_at": start_at})
        assert response.status_code == 200
        updated = response.json()
        assert updated["original_start_at"] == meeting["original_start_at"]
        assert updated["created_at"] == meeting["created_at"]
        assert updated["status"] == "scheduled"
    schedule = client.get("/managers/1/schedule", params={"date": "2026-11-23"}).json()
    assert schedule[0]["start_at"] == "2026-11-23T07:00:00Z"


def test_cancel_hides_meeting_and_prevents_rescheduling(client, meeting):
    path = f"/meetings/{meeting['id']}"
    response = client.patch(path, json={"status": "cancelled"})
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["original_start_at"] == meeting["original_start_at"]
    assert client.get("/managers/1/schedule", params={"date": "2026-11-23"}).json() == []
    assert client.patch(path, json={"status": "cancelled"}).status_code == 200
    assert client.patch(path, json={"start_at": "2026-11-23T06:00:00Z"}).status_code == 409


def test_meeting_set_checks_company_and_active_status(client, company, meeting):
    payload = {"company_id": company["id"], "result": "meeting_set", "meeting_id": meeting["id"]}
    response = client.post("/calls", json=payload)
    assert response.status_code == 201
    assert response.json()["meeting_id"] == meeting["id"]

    other = client.post(
        "/companies", json={"name": "Other", "bin": "000000000001", "phone": "+77001234567"}
    )
    assert other.status_code == 201
    assert client.post("/calls", json={**payload, "company_id": other.json()["id"]}).status_code == 422
    assert client.patch(f"/meetings/{meeting['id']}", json={"status": "cancelled"}).status_code == 200
    assert client.post("/calls", json=payload).status_code == 422
    assert client.get("/companies", params={"status": "meeting_set"}).json()["total"] == 1


def test_refused_call_does_not_cancel_existing_meeting(client, company, meeting):
    response = client.post("/calls", json={"company_id": company["id"], "result": "refused"})
    assert response.status_code == 201
    schedule = client.get("/managers/1/schedule", params={"date": "2026-11-23"}).json()
    assert [row["id"] for row in schedule] == [meeting["id"]]


def test_unknown_meeting_references_return_not_found(client, company):
    payload = {"company_id": 999, "manager_id": 1, "start_at": "2026-11-23T05:00:00Z"}
    assert client.post("/meetings", json=payload).status_code == 404
    payload.update(company_id=company["id"], manager_id=999)
    assert client.post("/meetings", json=payload).status_code == 404
    assert client.patch("/meetings/999", json={"status": "cancelled"}).status_code == 404
    assert client.get("/managers/999/schedule", params={"date": "2026-11-23"}).status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"company_id": 0},
        {"manager_id": True},
        {"manager_id": 10**100},
        {"start_at": "2026-11-23T05:00:00"},
        {"start_at": "2026-11-23T10:00:00+05:00"},
        {"start_at": 1795400000},
        {"start_at": "not-a-date"},
        {"status": "scheduled"},
    ],
)
def test_invalid_meeting_is_rejected(client, company, changes):
    payload = {"company_id": company["id"], "manager_id": 1, "start_at": "2026-11-23T05:00:00Z"}
    payload.update(changes)
    assert client.post("/meetings", json=payload).status_code == 422
    assert client.get("/managers/1/schedule", params={"date": "2026-11-23"}).json() == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "scheduled"},
        {"status": None},
        {"start_at": None},
        {"start_at": "2026-11-23T06:00:00Z", "status": "cancelled"},
        {"start_at": "2026-11-23T06:00:00Z", "status": None},
        {"start_at": "2026-11-23T06:00:00"},
        {"start_at": "2026-11-23T11:00:00+05:00"},
        {"manager_id": 2},
    ],
)
def test_invalid_patch_does_not_change_meeting(client, meeting, payload):
    assert client.patch(f"/meetings/{meeting['id']}", json=payload).status_code == 422
    schedule = client.get("/managers/1/schedule", params={"date": "2026-11-23"}).json()
    assert schedule == [meeting]


@pytest.mark.parametrize(
    "date",
    ["2026-02-30", "20261123", "not-a-date", "0001-01-01", "9999-12-31"],
)
def test_invalid_schedule_date_is_rejected(client, date):
    assert client.get("/managers/1/schedule", params={"date": date}).status_code == 422


def test_schedule_requires_date_and_ids_must_fit_sqlite(client):
    assert client.get("/managers/1/schedule").status_code == 422
    for id in [0, -1, 10**100]:
        assert client.get(f"/managers/{id}/schedule", params={"date": "2026-11-23"}).status_code == 422
        assert client.patch(f"/meetings/{id}", json={"status": "cancelled"}).status_code == 422
