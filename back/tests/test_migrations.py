"""Verifies the Alembic migrations produce the expected schema shape.

This is the safety net for the "create all the tables" ask: if a migration
is ever edited in a way that silently drops a column or a table, these
tests fail before the app or the seed script ever gets a chance to.
"""
from sqlalchemy import inspect


def test_imx_schema_has_expected_tables(sync_engine):
    inspector = inspect(sync_engine)
    tables = set(inspector.get_table_names(schema="imx"))
    assert tables == {"adherents", "debiteurs", "factures"}


def test_app_schema_has_expected_tables(sync_engine):
    inspector = inspect(sync_engine)
    tables = set(inspector.get_table_names(schema="public"))
    # "alembic_version" is Alembic's own bookkeeping table, not one of ours.
    tables.discard("alembic_version")
    assert tables == {
        "traites",
        "traite_documents",
        "champs_extraits",
        "rapprochements_nlp",
        "verifications_manuelles",
        "decisions",
        "audit_log",
        # Sprint 8/9 — raw-SQL only (see app/services/extraction_log.py),
        # never touched through the ORM, but it's still part of this app's
        # schema and belongs in this inventory.
        "extractions_ia",
    }


def test_extractions_ia_columns_and_fk(sync_engine):
    """Written and read entirely via raw SQL (extraction_log.py) — this is
    the only place its shape is checked against the ORM's own reflection,
    since no SQLAlchemy model exists for it to keep in sync automatically."""
    inspector = inspect(sync_engine)
    columns = {c["name"] for c in inspector.get_columns("extractions_ia")}
    assert columns == {
        "id", "traite_id", "fournisseur", "modele", "succes",
        "reponse_brute", "erreur", "duree_ms", "cree_le",
    }

    fks = inspector.get_foreign_keys("extractions_ia")
    assert any(fk["referred_table"] == "traites" for fk in fks)

    indexes = inspector.get_indexes("extractions_ia")
    assert any(idx["column_names"] == ["traite_id"] for idx in indexes)


def test_adherents_columns(sync_engine):
    inspector = inspect(sync_engine)
    columns = {c["name"] for c in inspector.get_columns("adherents", schema="imx")}
    assert columns == {"code_adherent", "raison_sociale", "matricule_fiscal", "statut_contrat"}


def test_debiteurs_columns_and_fk(sync_engine):
    inspector = inspect(sync_engine)
    columns = {c["name"] for c in inspector.get_columns("debiteurs", schema="imx")}
    assert columns == {"code_debiteur", "raison_sociale", "adresse", "rib", "code_adherent"}

    fks = inspector.get_foreign_keys("debiteurs", schema="imx")
    assert any(fk["referred_table"] == "adherents" for fk in fks)


def test_factures_montant_net_is_generated(sync_engine):
    inspector = inspect(sync_engine)
    columns = {c["name"]: c for c in inspector.get_columns("factures", schema="imx")}
    assert "montant_net" in columns
    # computed columns report a "computed" dict in SQLAlchemy's reflection
    assert columns["montant_net"].get("computed") is not None


def test_traites_unique_numero_lcn(sync_engine):
    inspector = inspect(sync_engine)
    uniques = inspector.get_unique_constraints("traites")
    assert any("numero_lcn" in u["column_names"] for u in uniques)


def test_verifications_manuelles_unique_per_traite_and_code(sync_engine):
    inspector = inspect(sync_engine)
    uniques = inspector.get_unique_constraints("verifications_manuelles")
    assert any(
        set(u["column_names"]) == {"traite_id", "code_verification"} for u in uniques
    )
