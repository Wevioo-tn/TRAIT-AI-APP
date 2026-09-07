"""Raw-SQL persistence for VLM extraction attempts — deliberately not the
SQLAlchemy ORM used everywhere else in this app.

This is an audit trail of real external model calls (Sprint 8): what was
asked, what came back, whether it parsed, how long it took. It's written
through its own short-lived, autocommit ``psycopg`` connection rather than
folded into ``execute_analysis``'s SQLAlchemy ``Session`` — deliberately,
so a log entry always survives even when the surrounding business
transaction later rolls back (or the caller never commits at all, as in
the case where extraction itself is what fails). That's the correct shape
for an audit log, not just an excuse to avoid the ORM.

Table DDL lives in migrations/versions/0004_extractions_ia_log.py, written
as raw SQL for the same reason — see that file's docstring.

Note: the ``extractions_ia`` table's own columns (fournisseur, modele,
succes, reponse_brute, erreur, duree_ms) stay in French — that's the DB
schema, unchanged by this rename. Only the Python-side parameter/variable
names here are English; they're mapped onto the French columns by
position in the raw SQL below, not by name.
"""
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Iterator

import psycopg

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _dsn() -> str:
    # psycopg's connection string doesn't use SQLAlchemy's "+psycopg"
    # dialect marker in the scheme.
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def _connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        yield conn


class Stopwatch:
    """Tiny helper so callers don't hand-roll `time.monotonic()` math."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)


def record_extraction(
    *,
    traite_id: uuid.UUID,
    provider: str,
    model: str,
    success: bool,
    raw_response: str | None,
    error: str | None,
    duration_ms: int,
) -> None:
    """Logs one extraction attempt. Never raises: a failure to log must
    never take down the analysis pipeline it's observing — it's only
    reported via a warning."""
    try:
        with _connection() as conn:
            conn.execute(
                """
                INSERT INTO extractions_ia
                    (traite_id, fournisseur, modele, succes, reponse_brute, erreur, duree_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (str(traite_id), provider, model, success, raw_response, error, duration_ms),
            )
    except Exception:
        logger.exception("Échec d'écriture dans extractions_ia pour la traite %s", traite_id)


def list_extractions(traite_id: uuid.UUID) -> list[dict]:
    """Raw-SQL read path to match the raw-SQL write path — used by tests
    and available for any future diagnostics endpoint. Returned dict keys
    are the real (French) column names, taken from the DB cursor itself."""
    with _connection() as conn:
        cur = conn.execute(
            """
            SELECT id, traite_id, fournisseur, modele, succes, reponse_brute, erreur, duree_ms, cree_le
            FROM extractions_ia
            WHERE traite_id = %s
            ORDER BY cree_le ASC
            """,
            (str(traite_id),),
        )
        columns = [desc.name for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
