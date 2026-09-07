"""Verifies the seed script produces correct, faithful, idempotent data.

The key assertion here is ``test_documentation_example_matches_screenshot``:
it feeds the exact TTC/avoirs from the IMX documentation through the real
generated column and checks the database computes the same montant_net the
documentation highlights (8 117,504) — proving the schema, not just the
Python arithmetic, is correct.
"""
from decimal import Decimal

from sqlalchemy import select

from app.db.models.imx import Adherent, Debiteur, Facture
from scripts import seed


def test_seed_creates_expected_row_counts(db_session):
    seed.run(db_session)

    assert len(db_session.scalars(select(Adherent)).all()) == len(seed.ADHERENTS)
    assert len(db_session.scalars(select(Debiteur)).all()) == len(seed.DEBITEURS)
    assert len(db_session.scalars(select(Facture)).all()) == len(seed.FACTURES)


def test_documentation_example_matches_screenshot(db_session):
    seed.run(db_session)

    adherent = db_session.get(Adherent, "ADH-0142")
    assert adherent.raison_sociale == "SO.CO.PAR."

    debiteur = db_session.get(Debiteur, "DEB-0087")
    assert debiteur.rib == "21258159852364789588"
    assert debiteur.code_adherent == "ADH-0142"

    facture = db_session.get(Facture, "FA-26-0117")
    assert facture.montant_ttc == Decimal("8400.000")
    assert facture.montant_avoirs == Decimal("282.496")
    # Computed by Postgres itself (GENERATED ALWAYS AS ttc - avoirs), not by
    # the application — this is the number the design mockup highlights.
    assert facture.montant_net == Decimal("8117.504")


def test_referential_integrity(db_session):
    seed.run(db_session)

    adherent_codes = {a.code_adherent for a in db_session.scalars(select(Adherent)).all()}
    debiteur_codes = {d.code_debiteur for d in db_session.scalars(select(Debiteur)).all()}

    for debiteur in db_session.scalars(select(Debiteur)).all():
        if debiteur.code_adherent is not None:
            assert debiteur.code_adherent in adherent_codes

    for facture in db_session.scalars(select(Facture)).all():
        assert facture.code_adherent in adherent_codes
        assert facture.code_debiteur in debiteur_codes


def test_seed_is_idempotent(db_session):
    seed.run(db_session)
    seed.run(db_session)  # must not raise (duplicate key, etc.)

    assert len(db_session.scalars(select(Adherent)).all()) == len(seed.ADHERENTS)
