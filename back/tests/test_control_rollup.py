"""Debtor per-rubrique control rollup (BPMN Phase 2, étape 10), exercised
through the real GET /api/traites/{id} endpoint — same style as
test_coverage.py: one real Debiteur seeded via a raw sync session, bills
created via the real API with their champs_extraits/rapprochements_nlp/
verifications_manuelles/code_debiteur set directly. This story is about
rolling up already-computed verdicts, not re-testing how each one gets
computed — that's each rubrique's own module's job (mentions_rules.py,
traite_processing.py, TR-102's RIB matching, coverage.py).
"""
import uuid
from decimal import Decimal

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.imx import Debiteur
from app.db.models.traite import (
    ChampExtrait,
    MethodeIdentification,
    RapprochementNlp,
    RoleNlp,
    SourceChamp,
    StatutVerification,
    Traite,
    VerificationCode,
    VerificationManuelle,
)

EMPTY_PAYLOAD: dict = {}


async def _create_bill(client) -> str:
    response = await client.post("/api/traites", json=EMPTY_PAYLOAD)
    return response.json()["id"]


def _make_bill_fully_passing(engine, bill_id: str, code_debiteur: str, *, with_rib_tire: bool = True) -> None:
    """Every row needed for all 5 rubriques to read true:

    - a small montant (coverage_ok is trivially satisfiable with zero
      matched invoices — no code_adherent is set, so find_matching_invoice
      always returns None here, a deliberate simplification of this
      fixture, not something coverage.py itself relies on);
    - the fields evaluate_mandatory_mentions needs (echeance, rib_tire,
      lieu_creation, date_creation — set with_rib_tire=False to leave one
      absent and fail mandatory_mentions_ok specifically);
    - an ORDRE beneficiary and a conforme SIG_TIREUR verification;
    - RIB-identified (TR-102) TIREUR/TIRE rows with no alerte_ecart_nom.

    The 3 date rules that don't need a matched invoice pass for free:
    an empty-payload POST /api/traites defaults date_creation_traite =
    date_echeance = today, so création<=aujourd'hui<=échéance all hold
    trivially; the 4th rule (avance sur facture) has no invoice to judge
    and is skipped (ok=None), not a failure.
    """
    with Session(engine) as session:
        bill = session.get(Traite, uuid.UUID(bill_id))
        bill.code_debiteur = code_debiteur
        bill.montant = Decimal("5.000")

        fields = [
            ("echeance", "2026-08-28"),
            ("lieu_creation", "Tunis"),
            ("date_creation", "2026-08-05"),
        ]
        if with_rib_tire:
            fields.append(("rib_tire", "11003000291700178836"))
        for nom_champ, valeur in fields:
            session.add(
                ChampExtrait(traite_id=bill.id, nom_champ=nom_champ, occurrence=1, valeur=valeur, source=SourceChamp.OCR)
            )

        session.add(
            RapprochementNlp(
                traite_id=bill.id,
                role=RoleNlp.TIREUR,
                valeur_scan="ADACTIM",
                valeur_referentiel="ADACTIM",
                score=Decimal("100"),
                methode_identification=MethodeIdentification.RIB,
                alerte_ecart_nom=False,
            )
        )
        session.add(
            RapprochementNlp(
                traite_id=bill.id,
                role=RoleNlp.TIRE,
                valeur_scan="TEST SA",
                valeur_referentiel="TEST SA",
                score=Decimal("100"),
                methode_identification=MethodeIdentification.RIB,
                alerte_ecart_nom=False,
            )
        )
        session.add(RapprochementNlp(traite_id=bill.id, role=RoleNlp.ORDRE, valeur_scan="SPG", score=Decimal("0")))

        sig_tireur = session.scalar(
            select(VerificationManuelle).where(
                VerificationManuelle.traite_id == bill.id,
                VerificationManuelle.code_verification == VerificationCode.SIG_TIREUR,
            )
        )
        sig_tireur.statut = StatutVerification.CONFORME

        session.commit()


class _DebtorFixture:
    def __init__(self, engine, suffix: str) -> None:
        self.engine = engine
        self.code_debiteur = f"DEB-ROLLUP-{suffix}"
        with Session(engine) as session:
            session.add(
                Debiteur(code_debiteur=self.code_debiteur, raison_sociale="TEST SA", rib=f"999999999999999{suffix}")
            )
            session.commit()

    def cleanup(self) -> None:
        with Session(self.engine) as session:
            session.execute(text("TRUNCATE traites CASCADE"))
            session.execute(delete(Debiteur).where(Debiteur.code_debiteur == self.code_debiteur))
            session.commit()


async def test_debtor_control_rollup_is_null_without_a_resolved_debtor(client):
    bill_id = await _create_bill(client)

    response = await client.get(f"/api/traites/{bill_id}")

    assert response.json()["control_rollup"] is None


async def test_single_bill_passing_everything_rolls_up_entirely_true(client):
    engine = create_engine(get_settings().database_url_test, future=True)
    fixture = _DebtorFixture(engine, "0001")
    try:
        bill_id = await _create_bill(client)
        _make_bill_fully_passing(engine, bill_id, fixture.code_debiteur)

        rollup = (await client.get(f"/api/traites/{bill_id}")).json()["control_rollup"]

        assert rollup == {
            "mandatory_mentions_ok": True,
            "duplicated_fields_ok": True,
            "date_rules_ok": True,
            "identification_ok": True,
            "coverage_ok": True,
        }
    finally:
        fixture.cleanup()
        engine.dispose()


async def test_single_bill_failing_duplicated_fields_flips_only_that_rubrique(client):
    engine = create_engine(get_settings().database_url_test, future=True)
    fixture = _DebtorFixture(engine, "0002")
    try:
        bill_id = await _create_bill(client)
        _make_bill_fully_passing(engine, bill_id, fixture.code_debiteur)
        with Session(engine) as session:
            bill = session.get(Traite, uuid.UUID(bill_id))
            # Two disagreeing occurrences of the same field — a real écart.
            session.add(
                ChampExtrait(traite_id=bill.id, nom_champ="numero_lcn", occurrence=1, valeur="111", source=SourceChamp.OCR)
            )
            session.add(
                ChampExtrait(traite_id=bill.id, nom_champ="numero_lcn", occurrence=2, valeur="222", source=SourceChamp.OCR)
            )
            session.commit()

        rollup = (await client.get(f"/api/traites/{bill_id}")).json()["control_rollup"]

        assert rollup["duplicated_fields_ok"] is False
        assert rollup["mandatory_mentions_ok"] is True
        assert rollup["date_rules_ok"] is True
        assert rollup["identification_ok"] is True
        assert rollup["coverage_ok"] is True
    finally:
        fixture.cleanup()
        engine.dispose()


async def test_one_of_two_bills_failing_mandatory_mentions_fails_the_debtor(client):
    """Any single bill's failure fails the whole rubrique for the
    debtor — the other 4 stay true since both bills genuinely pass them."""
    engine = create_engine(get_settings().database_url_test, future=True)
    fixture = _DebtorFixture(engine, "0003")
    try:
        passing_bill = await _create_bill(client)
        _make_bill_fully_passing(engine, passing_bill, fixture.code_debiteur)

        failing_bill = await _create_bill(client)
        _make_bill_fully_passing(engine, failing_bill, fixture.code_debiteur, with_rib_tire=False)

        rollup = (await client.get(f"/api/traites/{passing_bill}")).json()["control_rollup"]

        assert rollup["mandatory_mentions_ok"] is False
        assert rollup["duplicated_fields_ok"] is True
        assert rollup["date_rules_ok"] is True
        assert rollup["identification_ok"] is True
        assert rollup["coverage_ok"] is True
    finally:
        fixture.cleanup()
        engine.dispose()
