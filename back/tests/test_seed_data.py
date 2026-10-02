"""Verifies the seed script produces correct, faithful, idempotent data.

The key assertion here is ``test_real_sample_facture_montant_net_computed_by_db``:
it feeds the reconstructed TTC/avoirs for the one real sample traite (see
seed.py's own docstring — ADACTIM / LA MÉDITERRANÉENNE, transcribed from an
actual physical Lettre de Change, Sprint 12) through the real generated
column and checks the database computes the same montant_net the traite
itself states (8 117,504) — proving the schema, not just the Python
arithmetic, is correct.
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


def test_real_sample_facture_montant_net_computed_by_db(db_session):
    seed.run(db_session)

    adherent = db_session.get(Adherent, "ADH-0142")
    assert adherent.raison_sociale == "ADACTIM"
    assert adherent.matricule_fiscal == "1330392/A/A/M/000"
    assert adherent.beneficiaire_attendu == "SPG"

    debiteur = db_session.get(Debiteur, "DEB-0087")
    assert debiteur.raison_sociale == "LA MEDITERRANEENNE"
    assert debiteur.adresse == "Lot 31, Z.I. Chotrana II, 2036 Ariana"
    assert debiteur.rib == "11003000291700178836"
    assert debiteur.code_adherent == "ADH-0142"

    facture = db_session.get(Facture, "FA-26-0301")
    assert facture.montant_ttc == Decimal("8400.000")
    assert facture.montant_avoirs == Decimal("282.496")
    assert facture.code_adherent == "ADH-0142"
    assert facture.code_debiteur == "DEB-0087"
    # Computed by Postgres itself (GENERATED ALWAYS AS ttc - avoirs), not by
    # the application — this is the traite's own real montant (8117,504 DT,
    # both handwritten en lettres and boxed en chiffres on the sample).
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
