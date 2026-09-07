"""Sprint 9 — extraction_log.py's raw-psycopg read/write path.

This module's whole reason to exist is to talk to Postgres directly,
bypassing the SQLAlchemy ORM used everywhere else — faking that boundary
would test nothing real. So unlike test_vlm_extraction.py (which mocks
this module at the VlmExtractor level), these tests hit the real test
database, the same way test_migrations.py/test_seed_data.py do.

Note: the rows returned by ``list_extractions`` carry the real (French) DB
column names as dict keys (fournisseur, modele, succes, reponse_brute,
erreur, duree_ms, cree_le) — those come straight from the cursor
description, i.e. the unchanged ``extractions_ia`` table schema.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.traite import Traite
from app.services import extraction_log


@pytest.fixture(autouse=True)
def _point_extraction_log_at_test_database(monkeypatch):
    """extraction_log.py opens its own connection via get_settings() —
    point it at database_url_test instead of the dev database, the same
    isolation every other test in this suite already gets."""
    test_settings = Settings(database_url=get_settings().database_url_test)
    monkeypatch.setattr("app.services.extraction_log.get_settings", lambda: test_settings)


@pytest.fixture
def traite_id(sync_engine):
    """A real, committed traite row — extraction_log.py uses its own
    connection, so an uncommitted row from the rollback-based `db_session`
    fixture wouldn't be visible to it (and would violate the FK anyway)."""
    with Session(sync_engine) as session:
        traite = Traite(
            numero_lcn="099900002222",
            montant=Decimal("100.000"),
            date_echeance=date(2026, 10, 1),
            date_creation_traite=date(2026, 9, 1),
        )
        session.add(traite)
        session.commit()
        tid = traite.id
    try:
        yield tid
    finally:
        with sync_engine.begin() as connection:
            connection.execute(text("TRUNCATE traites CASCADE"))


def test_record_extraction_then_list_extractions_round_trips(traite_id):
    extraction_log.record_extraction(
        traite_id=traite_id,
        provider="local_llm",
        model="moondream",
        success=True,
        raw_response='{"numero_lcn": {"occurrence_1": "099900002222"}}',
        error=None,
        duration_ms=1234,
    )

    rows = extraction_log.list_extractions(traite_id)

    assert len(rows) == 1
    row = rows[0]
    assert row["traite_id"] == traite_id
    assert row["fournisseur"] == "local_llm"
    assert row["modele"] == "moondream"
    assert row["succes"] is True
    assert row["reponse_brute"] == '{"numero_lcn": {"occurrence_1": "099900002222"}}'
    assert row["erreur"] is None
    assert row["duree_ms"] == 1234
    assert row["cree_le"] is not None


def test_record_extraction_records_a_failed_attempt_with_raw_response(traite_id):
    extraction_log.record_extraction(
        traite_id=traite_id,
        provider="local_llm",
        model="moondream",
        success=False,
        raw_response="The image features a gray and brown striped pattern.",
        error="La réponse du modèle ne contient pas d'objet JSON exploitable",
        duration_ms=987,
    )

    rows = extraction_log.list_extractions(traite_id)

    assert len(rows) == 1
    assert rows[0]["succes"] is False
    assert rows[0]["reponse_brute"] == "The image features a gray and brown striped pattern."
    assert "JSON" in rows[0]["erreur"]


def test_list_extractions_orders_multiple_attempts_chronologically(traite_id):
    extraction_log.record_extraction(
        traite_id=traite_id, provider="local_llm", model="moondream",
        success=False, raw_response="premier essai raté", error="erreur", duration_ms=500,
    )
    extraction_log.record_extraction(
        traite_id=traite_id, provider="local_llm", model="moondream",
        success=True, raw_response="second essai réussi", error=None, duration_ms=600,
    )

    rows = extraction_log.list_extractions(traite_id)

    assert [row["reponse_brute"] for row in rows] == ["premier essai raté", "second essai réussi"]


def test_list_extractions_is_scoped_to_its_own_traite(traite_id, sync_engine):
    extraction_log.record_extraction(
        traite_id=traite_id, provider="local_llm", model="moondream",
        success=True, raw_response="pour cette traite", error=None, duration_ms=100,
    )

    assert extraction_log.list_extractions(uuid.uuid4()) == []


def test_record_extraction_never_raises_on_a_bad_traite_id():
    """A logging failure must never take down the analysis pipeline it's
    observing (see the module docstring) — proven here with a traite_id
    that violates the foreign key, not just asserted in a comment."""
    extraction_log.record_extraction(
        traite_id=uuid.uuid4(),
        provider="local_llm",
        model="moondream",
        success=True,
        raw_response="peu importe",
        error=None,
        duration_ms=1,
    )
