"""Sprint 4 — POST .../analyse and GET .../status.

The Celery dispatch itself (.delay()) is monkeypatched to a spy: these
tests are about the API's own validation and state transition, not about
proving Celery can reach Redis (that's covered live in Docker, and the task
body itself is covered by test_celery_task.py / test_traite_processing.py
without needing a broker at all).
"""
import app.api.routes.traites as traites_routes

TRAITE_PAYLOAD = {
    "numero_lcn": "011570763437",
    "montant": "8117.504",
    "date_echeance": "2026-08-28",
    "date_creation_traite": "2026-08-05",
}


async def _create_traite(client) -> str:
    response = await client.post("/api/traites", json=TRAITE_PAYLOAD)
    return response.json()["id"]


async def _upload_both_faces(client, traite_id: str) -> None:
    for face in ("recto", "verso"):
        await client.post(
            f"/api/traites/{traite_id}/documents",
            params={"face": face},
            files={"file": (f"{face}.jpg", b"data", "image/jpeg")},
        )


def _spy_delay(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(traites_routes.launch_traite_analysis, "delay", lambda traite_id: calls.append(traite_id))
    return calls


async def test_analyse_requires_both_faces(client, monkeypatch):
    _spy_delay(monkeypatch)
    traite_id = await _create_traite(client)

    response = await client.post(f"/api/traites/{traite_id}/analyse")
    assert response.status_code == 409
    assert "recto" in response.json()["detail"] and "verso" in response.json()["detail"]


async def test_analyse_succeeds_with_both_faces_and_dispatches_task(client, monkeypatch):
    calls = _spy_delay(monkeypatch)
    traite_id = await _create_traite(client)
    await _upload_both_faces(client, traite_id)

    response = await client.post(f"/api/traites/{traite_id}/analyse")
    assert response.status_code == 202
    assert response.json()["statut"] == "En cours OCR"
    assert calls == [traite_id]


async def test_analyse_rejects_relaunch_once_already_running(client, monkeypatch):
    _spy_delay(monkeypatch)
    traite_id = await _create_traite(client)
    await _upload_both_faces(client, traite_id)
    await client.post(f"/api/traites/{traite_id}/analyse")

    second = await client.post(f"/api/traites/{traite_id}/analyse")
    assert second.status_code == 409


async def test_analyse_unknown_traite_returns_404(client, monkeypatch):
    _spy_delay(monkeypatch)
    response = await client.post("/api/traites/00000000-0000-0000-0000-000000000000/analyse")
    assert response.status_code == 404


async def test_status_reflects_en_cours_after_launch(client, monkeypatch):
    _spy_delay(monkeypatch)
    traite_id = await _create_traite(client)

    before = await client.get(f"/api/traites/{traite_id}/status")
    assert before.json() == {"statut": "À traiter", "en_cours": False}

    await _upload_both_faces(client, traite_id)
    await client.post(f"/api/traites/{traite_id}/analyse")

    after = await client.get(f"/api/traites/{traite_id}/status")
    assert after.json() == {"statut": "En cours OCR", "en_cours": True}


async def test_status_unknown_traite_returns_404(client):
    response = await client.get("/api/traites/00000000-0000-0000-0000-000000000000/status")
    assert response.status_code == 404
