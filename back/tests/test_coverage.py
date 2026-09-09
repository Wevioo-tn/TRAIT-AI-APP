"""Debtor invoice-coverage check (BPMN Phase 3, étape 3), exercised
through the real GET /api/traites/{id} endpoint — same style as
test_montant_avoirs_api.py: bills created via the real API, imx.*
referential seeded via a raw sync session, and (since this story
deliberately isn't about re-testing RIB matching, see coverage.py's own
"hors scope" note) each bill's code_adherent/code_debiteur/montant set
directly rather than routed through a full execute_analysis pass.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.imx import Adherent, Debiteur, Facture, StatutContrat, StatutFacture
from app.db.models.traite import Traite

EMPTY_PAYLOAD: dict = {}


async def _create_bill(client) -> str:
    response = await client.post("/api/traites", json=EMPTY_PAYLOAD)
    return response.json()["id"]


def _set_bill(engine, bill_id: str, *, code_adherent: str, code_debiteur: str, montant: str, avoirs: str | None = None) -> None:
    with Session(engine) as session:
        bill = session.get(Traite, uuid.UUID(bill_id))
        bill.code_adherent = code_adherent
        bill.code_debiteur = code_debiteur
        bill.montant = Decimal(montant)
        if avoirs is not None:
            bill.montant_avoirs_saisi = Decimal(avoirs)
        session.commit()


class _ImxFixture:
    """One (adherent, debiteur) pair, unique per test via a caller-given
    suffix — cheap isolation without needing TRUNCATE between tests."""

    def __init__(self, engine, suffix: str) -> None:
        self.engine = engine
        self.code_adherent = f"ADH-COV-{suffix}"
        self.code_debiteur = f"DEB-COV-{suffix}"
        self._invoice_nums: list[str] = []
        with Session(engine) as session:
            session.add(
                Adherent(code_adherent=self.code_adherent, raison_sociale="ADACTIM", statut_contrat=StatutContrat.ACTIF)
            )
            session.add(
                Debiteur(
                    code_debiteur=self.code_debiteur,
                    raison_sociale="LA MÉDITERRANÉENNE",
                    rib=f"1000000000000{suffix}".ljust(20, "0")[:20],
                )
            )
            session.commit()

    def add_invoice(self, num_facture: str, montant_ttc: str, montant_avoirs: str = "0") -> None:
        self._invoice_nums.append(num_facture)
        with Session(self.engine) as session:
            session.add(
                Facture(
                    num_facture=num_facture,
                    code_adherent=self.code_adherent,
                    code_debiteur=self.code_debiteur,
                    montant_ttc=Decimal(montant_ttc),
                    montant_avoirs=Decimal(montant_avoirs),
                    date_facture=date(2026, 8, 1),
                    statut=StatutFacture.ENCOURS,
                )
            )
            session.commit()

    def cleanup(self) -> None:
        with Session(self.engine) as session:
            session.execute(text("TRUNCATE traites CASCADE"))
            for num in self._invoice_nums:
                session.execute(delete(Facture).where(Facture.num_facture == num))
            session.execute(delete(Debiteur).where(Debiteur.code_debiteur == self.code_debiteur))
            session.execute(delete(Adherent).where(Adherent.code_adherent == self.code_adherent))
            session.commit()


async def test_debtor_coverage_is_null_without_a_resolved_debtor(client):
    bill_id = await _create_bill(client)

    response = await client.get(f"/api/traites/{bill_id}")

    assert response.json()["debtor_coverage"] is None


async def test_single_bill_single_invoice_trivial_coverage(client):
    engine = create_engine(get_settings().database_url_test, future=True)
    fixture = _ImxFixture(engine, "0001")
    try:
        fixture.add_invoice("FA-COV-0001-01", "100.000")  # montant_net = 100.000
        bill_id = await _create_bill(client)
        _set_bill(engine, bill_id, code_adherent=fixture.code_adherent, code_debiteur=fixture.code_debiteur, montant="100.000")

        coverage = (await client.get(f"/api/traites/{bill_id}")).json()["debtor_coverage"]

        assert coverage["total_bills_amount"] == "100.000"
        assert coverage["total_invoices_net_amount"] == "100.000"
        assert coverage["total_credit_notes_amount"] == "0.000"
        assert coverage["gap"] == "0.000"
        assert coverage["sufficient"] is True
    finally:
        fixture.cleanup()
        engine.dispose()


async def test_credit_notes_entered_reduce_the_gap(client):
    """Without the avoirs saisis, a real 15-unit gap exceeds the default
    10.000 threshold; entering them as an avoir brings it back to zero —
    proving TR-113's montant_avoirs_saisi now has a real effect."""
    engine = create_engine(get_settings().database_url_test, future=True)
    fixture = _ImxFixture(engine, "0002")
    try:
        fixture.add_invoice("FA-COV-0002-01", "115.000")  # montant_net = 115.000
        bill_id = await _create_bill(client)
        _set_bill(engine, bill_id, code_adherent=fixture.code_adherent, code_debiteur=fixture.code_debiteur, montant="100.000")

        without_avoir = (await client.get(f"/api/traites/{bill_id}")).json()["debtor_coverage"]
        assert without_avoir["gap"] == "15.000"
        assert without_avoir["sufficient"] is False

        _set_bill(
            engine, bill_id, code_adherent=fixture.code_adherent, code_debiteur=fixture.code_debiteur,
            montant="100.000", avoirs="15.000",
        )
        with_avoir = (await client.get(f"/api/traites/{bill_id}")).json()["debtor_coverage"]
        assert with_avoir["total_credit_notes_amount"] == "15.000"
        assert with_avoir["gap"] == "0.000"
        assert with_avoir["sufficient"] is True
    finally:
        fixture.cleanup()
        engine.dispose()


async def test_two_bills_same_invoice_counted_once(client):
    engine = create_engine(get_settings().database_url_test, future=True)
    fixture = _ImxFixture(engine, "0003")
    try:
        fixture.add_invoice("FA-COV-0003-01", "150.000")  # montant_net = 150.000, the only candidate for both bills
        bill_1 = await _create_bill(client)
        bill_2 = await _create_bill(client)
        _set_bill(engine, bill_1, code_adherent=fixture.code_adherent, code_debiteur=fixture.code_debiteur, montant="70.000")
        _set_bill(engine, bill_2, code_adherent=fixture.code_adherent, code_debiteur=fixture.code_debiteur, montant="80.000")

        coverage = (await client.get(f"/api/traites/{bill_1}")).json()["debtor_coverage"]

        assert coverage["total_bills_amount"] == "150.000"  # 70 + 80
        assert coverage["total_invoices_net_amount"] == "150.000"  # the SAME invoice, not double-counted
        assert coverage["gap"] == "0.000"
        assert coverage["sufficient"] is True
    finally:
        fixture.cleanup()
        engine.dispose()


async def test_two_bills_two_different_invoices_both_summed(client):
    engine = create_engine(get_settings().database_url_test, future=True)
    fixture = _ImxFixture(engine, "0004")
    try:
        fixture.add_invoice("FA-COV-0004-01", "100.000")  # montant_net = 100.000
        fixture.add_invoice("FA-COV-0004-02", "1000.000")  # montant_net = 1000.000
        bill_1 = await _create_bill(client)
        bill_2 = await _create_bill(client)
        # Each bill's montant is closest to a different one of the two invoices.
        _set_bill(engine, bill_1, code_adherent=fixture.code_adherent, code_debiteur=fixture.code_debiteur, montant="100.000")
        _set_bill(engine, bill_2, code_adherent=fixture.code_adherent, code_debiteur=fixture.code_debiteur, montant="1000.000")

        coverage = (await client.get(f"/api/traites/{bill_1}")).json()["debtor_coverage"]

        assert coverage["total_bills_amount"] == "1100.000"  # 100 + 1000
        assert coverage["total_invoices_net_amount"] == "1100.000"  # both invoices summed
        assert coverage["gap"] == "0.000"
        assert coverage["sufficient"] is True
    finally:
        fixture.cleanup()
        engine.dispose()


async def test_gap_above_threshold_is_insufficient(client):
    engine = create_engine(get_settings().database_url_test, future=True)
    fixture = _ImxFixture(engine, "0005")
    try:
        fixture.add_invoice("FA-COV-0005-01", "111.000")  # montant_net = 111.000
        bill_id = await _create_bill(client)
        # gap = 111 - 100 = 11 > default threshold (10.000)
        _set_bill(engine, bill_id, code_adherent=fixture.code_adherent, code_debiteur=fixture.code_debiteur, montant="100.000")

        coverage = (await client.get(f"/api/traites/{bill_id}")).json()["debtor_coverage"]

        assert coverage["gap"] == "11.000"
        assert coverage["sufficient"] is False
    finally:
        fixture.cleanup()
        engine.dispose()


async def test_gap_at_or_below_threshold_is_sufficient(client):
    engine = create_engine(get_settings().database_url_test, future=True)
    fixture = _ImxFixture(engine, "0006")
    try:
        fixture.add_invoice("FA-COV-0006-01", "110.000")  # montant_net = 110.000
        bill_id = await _create_bill(client)
        # gap = 110 - 100 = 10, exactly at the default threshold (10.000).
        _set_bill(engine, bill_id, code_adherent=fixture.code_adherent, code_debiteur=fixture.code_debiteur, montant="100.000")

        coverage = (await client.get(f"/api/traites/{bill_id}")).json()["debtor_coverage"]

        assert coverage["gap"] == "10.000"
        assert coverage["sufficient"] is True
    finally:
        fixture.cleanup()
        engine.dispose()
