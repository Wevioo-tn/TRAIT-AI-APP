"""PATCH /api/traites/{id}/montant-avoirs — the caissier's manual avoirs
saisie (BPMN Phase 3, étape 2), and TraiteDetail's exposure of it
alongside the read-only IMX facture context it must never be confused
with. Same test style as test_verification_and_decision_api.py, the
established PATCH-endpoint pattern this mirrors."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.imx import Adherent, Debiteur, Facture, StatutContrat, StatutFacture
from app.db.models.traite import AuditLogEntry, Traite
from app.services.extraction import StubExtractor
from app.services.traite_processing import execute_analysis

TRAITE_PAYLOAD = {
    "numero_lcn": "011570763437",
    "montant": "8117.504",
    "date_echeance": "2026-08-28",
    "date_creation_traite": "2026-08-05",
}


async def _create_traite(client) -> str:
    response = await client.post("/api/traites", json=TRAITE_PAYLOAD)
    return response.json()["id"]


async def test_patch_montant_avoirs_sets_value(client):
    traite_id = await _create_traite(client)

    response = await client.patch(f"/api/traites/{traite_id}/montant-avoirs", json={"montant_avoirs": "282.496"})

    assert response.status_code == 200
    assert response.json()["montant_avoirs_saisi"] == "282.496"


async def test_patch_montant_avoirs_null_clears_previous_value(client):
    traite_id = await _create_traite(client)
    await client.patch(f"/api/traites/{traite_id}/montant-avoirs", json={"montant_avoirs": "100.000"})

    response = await client.patch(f"/api/traites/{traite_id}/montant-avoirs", json={"montant_avoirs": None})

    assert response.status_code == 200
    assert response.json()["montant_avoirs_saisi"] is None


async def test_patch_montant_avoirs_negative_value_rejected(client):
    traite_id = await _create_traite(client)

    response = await client.patch(f"/api/traites/{traite_id}/montant-avoirs", json={"montant_avoirs": "-1.000"})

    assert response.status_code == 422


async def test_patch_montant_avoirs_zero_is_a_legitimate_value(client):
    """Zero ("no avoir applicable") is a real, explicit saisie — distinct
    from null ("not yet saisi") — and must not be rejected like a negative
    value would be. Checked via a fresh GET (a new request-scoped session,
    not the PATCH's own echoed-back in-memory value) to confirm what's
    actually persisted, normalized to the column's NUMERIC(14,3) scale."""
    traite_id = await _create_traite(client)

    response = await client.patch(f"/api/traites/{traite_id}/montant-avoirs", json={"montant_avoirs": "0"})
    assert response.status_code == 200

    fresh = await client.get(f"/api/traites/{traite_id}")
    assert fresh.json()["montant_avoirs_saisi"] == "0.000"


async def test_patch_montant_avoirs_unknown_traite_returns_404(client):
    response = await client.patch(
        "/api/traites/00000000-0000-0000-0000-000000000000/montant-avoirs", json={"montant_avoirs": "50.000"}
    )
    assert response.status_code == 404


async def test_patch_montant_avoirs_rejected_once_traite_has_final_decision(client):
    traite_id = await _create_traite(client)
    await client.post(
        f"/api/traites/{traite_id}/decisions", json={"type": "renvoi", "commentaire": "Complément requis."}
    )

    response = await client.patch(f"/api/traites/{traite_id}/montant-avoirs", json={"montant_avoirs": "50.000"})

    assert response.status_code == 409


async def test_patch_montant_avoirs_writes_audit_log_entry_with_old_and_new_value(client, sync_engine):
    traite_id = await _create_traite(client)
    await client.patch(f"/api/traites/{traite_id}/montant-avoirs", json={"montant_avoirs": "100.000"})

    await client.patch(f"/api/traites/{traite_id}/montant-avoirs", json={"montant_avoirs": "150.500"})

    with Session(sync_engine) as session:
        entries = session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.traite_id == uuid.UUID(traite_id),
                AuditLogEntry.action == "montant_avoirs_saisi",
            ).order_by(AuditLogEntry.horodatage)
        ).all()

    assert len(entries) == 2
    assert entries[0].details == {"ancienne_valeur": None, "nouvelle_valeur": "100.000"}
    assert entries[1].details == {"ancienne_valeur": "100.000", "nouvelle_valeur": "150.500"}


# Unique to this file — no other test's seed data uses these codes.
CODE_ADHERENT = "ADH-MA6001"
CODE_DEBITEUR = "DEB-MA6001"
NUM_FACTURE = "FA-MA6001-01"


async def test_traite_detail_keeps_imx_facture_context_distinct_from_cashier_saisie(client, tmp_path):
    """The whole point of this story: facture_rapprochee (IMX, read-only)
    and montant_avoirs_saisi (this app's own) must never be confused —
    PATCHing one never touches the other."""
    created = await client.post("/api/traites", json=TRAITE_PAYLOAD)
    traite_id = created.json()["id"]
    await client.post(
        f"/api/traites/{traite_id}/documents",
        params={"face": "recto"},
        files={"file": ("recto.jpg", b"data", "image/jpeg")},
    )
    await client.post(
        f"/api/traites/{traite_id}/documents",
        params={"face": "verso"},
        files={"file": ("verso.jpg", b"data", "image/jpeg")},
    )

    engine = create_engine(get_settings().database_url_test, future=True)
    try:
        with Session(engine) as session:
            session.add(
                Adherent(code_adherent=CODE_ADHERENT, raison_sociale="ADACTIM", statut_contrat=StatutContrat.ACTIF)
            )
            session.add(
                Debiteur(code_debiteur=CODE_DEBITEUR, raison_sociale="LA MÉDITERRANÉENNE", rib="11003000291700178836")
            )
            session.add(
                Facture(
                    num_facture=NUM_FACTURE,
                    code_adherent=CODE_ADHERENT,
                    code_debiteur=CODE_DEBITEUR,
                    montant_ttc=Decimal("8400.000"),
                    montant_avoirs=Decimal("282.496"),  # montant_net = 8117.504, matches the traite exactly
                    date_facture=date(2026, 8, 1),
                    statut=StatutFacture.ENCOURS,
                )
            )
            session.commit()

            traite = session.get(Traite, uuid.UUID(traite_id))
            for doc in traite.documents:
                path = tmp_path / f"{doc.face.value}.jpg"
                path.write_bytes(b"data")
                doc.fichier_chemin = str(path)
            session.commit()

            execute_analysis(
                uuid.UUID(traite_id),
                session,
                StubExtractor(tireur_texte="ADACTIM", tire_texte="LA MÉDITERRANÉENNE"),
            )
            session.commit()

        before = (await client.get(f"/api/traites/{traite_id}")).json()
        assert before["montant_avoirs_saisi"] is None  # nothing saisi yet
        assert before["facture_rapprochee"]["num_facture"] == NUM_FACTURE
        assert before["facture_rapprochee"]["montant_ttc"] == "8400.000"
        assert before["facture_rapprochee"]["montant_avoirs"] == "282.496"  # IMX's own value
        assert before["facture_rapprochee"]["montant_net"] == "8117.504"

        await client.patch(f"/api/traites/{traite_id}/montant-avoirs", json={"montant_avoirs": "999.000"})

        after = (await client.get(f"/api/traites/{traite_id}")).json()
        assert after["montant_avoirs_saisi"] == "999.000"  # the caissier's own saisie
        assert after["facture_rapprochee"]["montant_avoirs"] == "282.496"  # IMX's own value, untouched
    finally:
        with Session(engine) as session:
            session.execute(text("TRUNCATE traites CASCADE"))
            session.execute(delete(Facture).where(Facture.num_facture == NUM_FACTURE))
            session.execute(delete(Debiteur).where(Debiteur.code_debiteur == CODE_DEBITEUR))
            session.execute(delete(Adherent).where(Adherent.code_adherent == CODE_ADHERENT))
            session.commit()
        engine.dispose()


async def test_traite_detail_facture_rapprochee_is_null_without_a_matched_invoice(client):
    traite_id = await _create_traite(client)

    response = await client.get(f"/api/traites/{traite_id}")

    assert response.json()["facture_rapprochee"] is None
    assert response.json()["montant_avoirs_saisi"] is None
