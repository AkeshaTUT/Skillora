from __future__ import annotations


def test_courses_list(client):
    response = client.get("/api/courses?page=1&page_size=5")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert isinstance(payload["items"], list)


def test_protected_endpoint_requires_token(client):
    response = client.get("/api/admin/stats")
    assert response.status_code == 401


def test_auth_token_and_protected_access(client):
    token_resp = client.post(
        "/api/auth/token",
        data={"username": "admin", "password": "admin123"},
    )
    assert token_resp.status_code == 200

    token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me_resp = client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "admin"

    stats_resp = client.get("/api/admin/stats", headers=headers)
    assert stats_resp.status_code == 200
    assert "total_courses" in stats_resp.json()
