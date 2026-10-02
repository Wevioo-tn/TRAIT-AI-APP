"""Sprint 6.0 — integration test proving GET /api/traites/{id} exposes the
mentions/date-rules read-model and the matched facture, end to end through
the real API (not just the pure unit tests in test_mentions_rules.py).

Runs the real execute_analysis (sync) against the same physical test
database the async `client` fixture talks to — two connections to one DB,
which is exactly how the async request path and the sync background task
relate in production. Uses its own throwaway engine (not the shared `sync_engine`
fixture) and commits directly, since the imx rows need to be visible to
the `client` fixture's independent async connection.

Two real bugs caught building this, neither visible running this test
alone — only running the full suite surfaced them:

1. `imx.*` tables are never truncated between tests (only `traites` is,
   via `clean_app_tables` — imx isn't referenced *from* traites, so
   CASCADE never reaches it). This test's rows are actually committed
   (not rollback-isolated, since they need to be visible to the `client`
   fixture's independent async connection), so a first version reusing
   "ADH-1001"/"DEB-1001" — the same codes test_traite_processing.py's own
   seed helper uses — left rows for other tests to collide with. Fixed by
   using codes unique to this file.
2. Cleanup order: execute_analysis resolves the traite's code_adherent/
   code_debiteur to point at these very rows, so deleting the debiteur/
   adherent before clearing that FK raised ForeignKeyViolation *inside the
   test's own teardown* — which looked, from outside, like unrelated
   later tests failing for no reason. Fixed by nulling the traite's FK
   columns before deleting the imx rows.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.imx import Adherent, Debiteur, Facture, StatutContrat, StatutFacture
from app.db.models.traite import Traite
from app.services.extraction import StubExtractor
from app.services.traite_processing import execute_analysis

TRAITE_PAYLOAD = {
    "numero_lcn": "011570763437",
    "montant": "8117.504",
    "date_echeance": "2026-08-28",
    "date_creation_traite": "2026-08-05",
}

# Unique to this test file — no other test's seed data uses these codes.
CODE_ADHERENT = "ADH-RM6001"
CODE_DEBITEUR = "DEB-RM6001"
NUM_FACTURE = "FA-RM6001-01"


async def test_traite_detail_exposes_mentions_and_matched_facture(client, tmp_path):
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
                Debiteur(
                    code_debiteur=CODE_DEBITEUR,
                    raison_sociale="LA MÉDITERRANÉENNE",
                    rib="11003000291700178836",
                    code_adherent=CODE_ADHERENT,
                )
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

            # Analysis consumes the same database bytes saved by the upload API.
            execute_analysis(
                uuid.UUID(traite_id),
                session,
                StubExtractor(
                    # Deliberately different from both IMX names: the
                    # header must describe this scan, not the matched row.
                    tireur_texte="MARWEN BEN AHMED",
                    tire_texte="KAMEL JANDOUBI",
                        rib_tire="11003000291700178836",
                    domiciliation_texte="UBCI Agence Paris, Tunis",
                ),
            )
            session.commit()

        response = await client.get(f"/api/traites/{traite_id}")
        body = response.json()

        assert body["num_facture_rapprochee"] == NUM_FACTURE
        # TR-116: two real, already-computed values that were previously
        # invisible to a reviewer — exposed here for the first time.
        assert body["domiciliation"] == "UBCI Agence Paris, Tunis"
        assert body["cross_field_discrepancies"] == []  # StubExtractor's fields are all internally coherent
        assert body["tireur_nom"] == "MARWEN BEN AHMED"
        assert body["tire_nom"] == "KAMEL JANDOUBI"

        mentions_by_code = {m["code"]: m for m in body["mentions"]}
        assert mentions_by_code["nom_tire"]["statut"] == "ok"
        assert mentions_by_code["nom_tire"]["valeur"] == "KAMEL JANDOUBI"
        assert mentions_by_code["echeance"]["statut"] == "ok"

        regles_by_label = {r["label"]: r for r in body["regles_dates"]}
        avance = regles_by_label["Date de création ≥ date de la facture rapprochée"]
        assert avance["ok"] is True  # facture (01/08) antérieure à la création (05/08) : cohérent
    finally:
        with Session(engine) as session:
            # execute_analysis resolved traite.code_adherent/code_debiteur
            # AND wrote a rapprochements_nlp row pointing at these same
            # rows — both reference imx.*, so deleting the imx rows first
            # raises ForeignKeyViolation. TRUNCATE ... CASCADE sweeps the
            # traite and everything hanging off it (champs_extraits,
            # rapprochements_nlp, verifications_manuelles, audit_log, ...)
            # in one shot — the same pattern clean_app_tables uses for
            # every other client-based test, safe here since tests run
            # sequentially, never concurrently.
            session.execute(text("TRUNCATE traites CASCADE"))
            session.execute(delete(Facture).where(Facture.num_facture == NUM_FACTURE))
            session.execute(delete(Debiteur).where(Debiteur.code_debiteur == CODE_DEBITEUR))
            session.execute(delete(Adherent).where(Adherent.code_adherent == CODE_ADHERENT))
            session.commit()
        engine.dispose()


async def test_existing_extraction_is_consistent_across_analysis_blocks(client):
    from app.db.models.traite import ChampExtrait, RapprochementNlp, RoleNlp, SourceChamp
    created = await client.post("/api/traites", json=TRAITE_PAYLOAD)
    bill_id = created.json()["id"]
    engine = create_engine(get_settings().database_url_test)
    try:
        with Session(engine) as session:
            bill = session.get(Traite, uuid.UUID(bill_id))
            bill.visual_marks = {"has_signature_tireur": True, "has_cachet_tireur": True}
            for name, value in (("rib_tire", "21 266 1588623321 88"),
                                ("date_creation", "07/09/26"), ("echeance", "30/09/25")):
                session.add(ChampExtrait(traite_id=bill.id, nom_champ=name, occurrence=1,
                                        valeur=value, source=SourceChamp.OCR))
            session.add(RapprochementNlp(traite_id=bill.id, role=RoleNlp.TIRE,
                                        valeur_scan="KAMEL JANDOUBI", score=0))
            session.add(RapprochementNlp(traite_id=bill.id, role=RoleNlp.RIB,
                                        valeur_scan="", score=0))
            session.commit()
        response = await client.get(f"/api/traites/{bill_id}")
        assert response.status_code == 200
        data = response.json()
        mentions = {m["code"]: m for m in data["mentions"]}
        assert mentions["nom_tire"]["valeur"] == "KAMEL JANDOUBI"
        rib = next(n for n in data["rapprochements_nlp"] if n["role"] == "rib")
        assert rib["valeur_scan"] == mentions["lieu_paiement"]["valeur"]
        assert rib["valeur_referentiel"] is None
        assert float(rib["score"]) == 0
        assert data["regles_dates"][1]["ok"] is False
        assert data["visual_marks"]["has_signature_tireur"] is True
        assert mentions["signature_tireur"]["statut"] == "warn"
        assert data["bloque"] is True
    finally:
        engine.dispose()


async def test_summary_uses_single_reading_without_promoting_business_amount(client):
    from app.db.models.traite import ChampExtrait, RapprochementNlp, RoleNlp, SourceChamp
    response = await client.post("/api/traites", json={})
    bill_id = response.json()["id"]
    engine = create_engine(get_settings().database_url_test)
    try:
        with Session(engine) as session:
            bill = session.get(Traite, uuid.UUID(bill_id))
            for name, value in (("montant_chiffres", "#8117,504#"), ("echeance", "28/08/26")):
                session.add(ChampExtrait(traite_id=bill.id, nom_champ=name, occurrence=1,
                                        valeur=value, source=SourceChamp.OCR))
            session.add(RapprochementNlp(traite_id=bill.id, role=RoleNlp.TIRE,
                                        valeur_scan="Lot 31, ZI, Chotrana II", score=0))
            session.commit()
        result = (await client.get(f"/api/traites/{bill_id}")).json()
        assert Decimal(result["montant"]) == Decimal("8117.504")
        assert result["date_echeance"] == "2026-08-28"
        assert result["tire_nom"] == "Lot 31, ZI, Chotrana II"
        assert result["tireur_nom"] is None
        queue = (await client.get("/api/traites", params={"per_page": 100})).json()
        queue_row = next(item for item in queue["items"] if item["id"] == bill_id)
        assert Decimal(queue_row["montant"]) == Decimal("8117.504")
        with Session(engine) as session:
            bill = session.get(Traite, uuid.UUID(bill_id))
            assert bill.montant == Decimal("0.001")
            session.add(ChampExtrait(traite_id=bill.id, nom_champ="montant_chiffres", occurrence=2,
                                    valeur="9000", source=SourceChamp.OCR))
            session.commit()
        conflict = (await client.get(f"/api/traites/{bill_id}")).json()
        assert Decimal(conflict["montant"]) == Decimal("0.001")
        queue = (await client.get("/api/traites", params={"per_page": 100})).json()
        queue_row = next(item for item in queue["items"] if item["id"] == bill_id)
        assert Decimal(queue_row["montant"]) == Decimal("0.001")
    finally:
        engine.dispose()
