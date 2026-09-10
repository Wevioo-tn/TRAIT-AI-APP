"""Sprint 3 — manual verification PATCH + cashier decision endpoints."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.traite import AuditLogEntry, Traite, TraiteStatut

from .conftest import TEST_USERNAME

TRAITE_PAYLOAD = {
    "numero_lcn": "011570763437",
    "montant": "8117.504",
    "date_echeance": "2026-08-28",
    "date_creation_traite": "2026-08-05",
}

ALL_CODES = ["sigTire", "accept", "sigTireur", "endos"]


async def _create_traite(client) -> str:
    response = await client.post("/api/traites", json=TRAITE_PAYLOAD)
    return response.json()["id"]


async def _mark_all_conforme(client, traite_id: str) -> None:
    for code in ALL_CODES:
        response = await client.patch(f"/api/traites/{traite_id}/verifications/{code}", json={"statut": "conforme"})
        assert response.status_code == 200


# ---- verification PATCH -----------------------------------------------------


async def test_patch_verification_sets_statut_and_metadata(client):
    traite_id = await _create_traite(client)

    response = await client.patch(
        f"/api/traites/{traite_id}/verifications/sigTireur", json={"statut": "conforme"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["statut"] == "conforme"
    assert body["verifie_par"] == TEST_USERNAME  # the real authenticated user, not a hardcoded placeholder
    assert body["verifie_le"] is not None


async def test_patch_verification_reset_to_null_clears_metadata(client):
    traite_id = await _create_traite(client)
    await client.patch(f"/api/traites/{traite_id}/verifications/accept", json={"statut": "anomalie"})

    response = await client.patch(f"/api/traites/{traite_id}/verifications/accept", json={"statut": None})
    assert response.status_code == 200
    body = response.json()
    assert body["statut"] is None
    assert body["verifie_par"] is None
    assert body["verifie_le"] is None


async def test_patch_verification_unknown_traite_returns_404(client):
    response = await client.patch(
        "/api/traites/00000000-0000-0000-0000-000000000000/verifications/sigTireur",
        json={"statut": "conforme"},
    )
    assert response.status_code == 404


async def test_get_traite_exposes_bloque_and_recommendation(client):
    traite_id = await _create_traite(client)

    fresh = await client.get(f"/api/traites/{traite_id}")
    assert fresh.json()["bloque"] is True
    assert fresh.json()["recommandation"]["titre"] == "Terminer les vérifications manuelles"

    await _mark_all_conforme(client, traite_id)
    ready = await client.get(f"/api/traites/{traite_id}")
    assert ready.json()["bloque"] is False
    assert ready.json()["recommandation"]["titre"] == "Valider la traite"


async def test_patch_verification_rejected_once_traite_has_final_decision(client):
    traite_id = await _create_traite(client)
    await _mark_all_conforme(client, traite_id)
    await client.post(f"/api/traites/{traite_id}/decisions", json={"type": "validee"})

    response = await client.patch(f"/api/traites/{traite_id}/verifications/sigTireur", json={"statut": "anomalie"})
    assert response.status_code == 409


# ---- decisions ---------------------------------------------------------------


async def test_decision_validee_blocked_when_verifications_incomplete(client):
    traite_id = await _create_traite(client)
    response = await client.post(f"/api/traites/{traite_id}/decisions", json={"type": "validee"})
    assert response.status_code == 409
    assert "incomplètes" in response.json()["detail"]


async def test_decision_validee_succeeds_and_updates_traite_statut(client):
    traite_id = await _create_traite(client)
    await _mark_all_conforme(client, traite_id)

    response = await client.post(f"/api/traites/{traite_id}/decisions", json={"type": "validee"})
    assert response.status_code == 201
    assert response.json()["type"] == "validee"

    traite = await client.get(f"/api/traites/{traite_id}")
    assert traite.json()["statut"] == "Validée"


async def test_decision_validee_blocked_by_single_anomaly_even_if_rest_conforme(client):
    traite_id = await _create_traite(client)
    await _mark_all_conforme(client, traite_id)
    await client.patch(f"/api/traites/{traite_id}/verifications/accept", json={"statut": "anomalie"})

    response = await client.post(f"/api/traites/{traite_id}/decisions", json={"type": "validee"})
    assert response.status_code == 409
    assert "Anomalie" in response.json()["detail"]


async def test_decision_validee_blocked_by_unresolved_automatic_ecarts_even_if_manual_all_conforme(
    client, sync_engine
):
    """TR-117: the real bug found live — a traite could be genuinely
    validated through this exact endpoint once the 4 manual checks were
    conforme, even with a real, unresolved automatic écart (a RIB-confirmed
    débiteur whose scanned name doesn't corroborate, a duplicated-field
    mismatch, ...) that execute_analysis had already flagged by leaving the
    traite's own statut at ECARTS_A_TRAITER."""
    traite_id = await _create_traite(client)
    await _mark_all_conforme(client, traite_id)

    # Simulates what execute_analysis leaves behind on a traite with a real
    # unresolved écart — setting the statut directly is the pragmatic way
    # to reach this state in an API-level test without re-running a full
    # OCR pipeline (see test_traite_processing.py for how that statut is
    # actually computed).
    with Session(sync_engine) as session:
        traite = session.get(Traite, uuid.UUID(traite_id))
        traite.statut = TraiteStatut.ECARTS_A_TRAITER
        session.commit()

    response = await client.post(f"/api/traites/{traite_id}/decisions", json={"type": "validee"})
    assert response.status_code == 409
    assert "Écarts automatiques" in response.json()["detail"]

    # Never actually validated — the traite's own statut is untouched.
    traite = await client.get(f"/api/traites/{traite_id}")
    assert traite.json()["statut"] == "Écarts à traiter"


async def test_decision_renvoi_requires_commentaire(client):
    traite_id = await _create_traite(client)

    missing = await client.post(f"/api/traites/{traite_id}/decisions", json={"type": "renvoi"})
    assert missing.status_code == 422

    ok = await client.post(
        f"/api/traites/{traite_id}/decisions",
        json={"type": "renvoi", "commentaire": "Signature du tireur manquante, retour à l'adhérent."},
    )
    assert ok.status_code == 201

    traite = await client.get(f"/api/traites/{traite_id}")
    assert traite.json()["statut"] == "Renvoyée"


async def test_decision_fraude_requires_commentaire(client):
    traite_id = await _create_traite(client)

    missing = await client.post(f"/api/traites/{traite_id}/decisions", json={"type": "fraude"})
    assert missing.status_code == 422

    ok = await client.post(
        f"/api/traites/{traite_id}/decisions",
        json={"type": "fraude", "commentaire": "Cachet identique tireur/tiré."},
    )
    assert ok.status_code == 201

    traite = await client.get(f"/api/traites/{traite_id}")
    assert traite.json()["statut"] == "Fraude signalée"


async def test_decision_rejected_once_traite_already_decided(client):
    traite_id = await _create_traite(client)
    await client.post(
        f"/api/traites/{traite_id}/decisions",
        json={"type": "renvoi", "commentaire": "Premier renvoi."},
    )

    second = await client.post(
        f"/api/traites/{traite_id}/decisions",
        json={"type": "fraude", "commentaire": "Ne devrait pas passer."},
    )
    assert second.status_code == 409


async def test_decision_unknown_traite_returns_404(client):
    response = await client.post(
        "/api/traites/00000000-0000-0000-0000-000000000000/decisions", json={"type": "validee"}
    )
    assert response.status_code == 404


async def test_decision_writes_audit_log_entry(client, sync_engine):
    traite_id = await _create_traite(client)
    await client.post(
        f"/api/traites/{traite_id}/decisions",
        json={"type": "renvoi", "commentaire": "Complément requis."},
    )

    with Session(sync_engine) as session:
        entries = session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.traite_id == uuid.UUID(traite_id),
                AuditLogEntry.action == "decision_prise",
            )
        ).all()
    assert len(entries) == 1
    assert entries[0].details["type"] == "renvoi"
