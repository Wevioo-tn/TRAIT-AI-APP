"""Regression test for the missing-CORS bug caught live via a real browser
(curl doesn't enforce or even reveal CORS — this is the only layer that
would have caught it before a human/browser did)."""
from app.core.config import get_settings


async def test_allowed_frontend_origin_gets_cors_header(client):
    origin = get_settings().cors_allowed_origins_list[0]
    response = await client.get("/api/health", headers={"Origin": origin})
    assert response.headers.get("access-control-allow-origin") == origin


async def test_unknown_origin_does_not_get_cors_header(client):
    response = await client.get("/api/health", headers={"Origin": "http://evil.example.com"})
    assert "access-control-allow-origin" not in response.headers
