"""Sprint 7 (superseded) — local username/password login and JWT-protected
routes.

Runs against the real `users` table in the real test database — not a
mock. `conftest.py`'s `seed_test_user` fixture inserts a real Argon2 hash
for TEST_USERNAME/TEST_PASSWORD once per test session; this file verifies
the actual login endpoint (app/api/routes/auth.py, app/services/
local_auth.py) authenticates against it for real. See BACKLOG.md's
Sprint 7 notes for the LDAP-based version this replaced.
"""
from httpx import ASGITransport, AsyncClient

from app.main import app

from .conftest import TEST_PASSWORD, TEST_USERNAME


async def test_login_with_valid_credentials_returns_token(client):
    response = await client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == TEST_USERNAME
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 0


async def test_login_with_wrong_password_returns_401(client):
    response = await client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": "not-the-password"}
    )
    assert response.status_code == 401


async def test_login_with_unknown_user_returns_same_401(client):
    """Unknown-user and wrong-password must be indistinguishable to the
    caller, so a login endpoint can't be used to enumerate valid usernames."""
    unknown = await client.post(
        "/api/auth/login", json={"username": "no.such.user", "password": TEST_PASSWORD}
    )
    wrong_password = await client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": "not-the-password"}
    )
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json()["detail"] == wrong_password.json()["detail"]


async def test_login_rejects_empty_credentials(client):
    response = await client.post("/api/auth/login", json={"username": "", "password": ""})
    assert response.status_code == 422


async def test_traites_endpoint_requires_authentication(client):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        response = await anon.get("/api/traites")
    assert response.status_code == 401


async def test_traites_endpoint_rejects_invalid_token(client):
    headers = {"Authorization": "Bearer this-is-not-a-real-token"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as anon:
        response = await anon.get("/api/traites")
    assert response.status_code == 401
