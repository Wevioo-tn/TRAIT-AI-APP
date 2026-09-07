"""Smoke test for /api/health."""


async def test_health_endpoint_reports_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
