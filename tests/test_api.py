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
