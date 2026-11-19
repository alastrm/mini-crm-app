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
