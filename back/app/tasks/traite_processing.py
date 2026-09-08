"""Wraps execute_analysis for use as a FastAPI background task (see
routes/traites.py's lancer_analyse, which calls this via
``BackgroundTasks.add_task``) — replaces the earlier Celery task, per an
explicit call to drop the separate `worker` process/Redis broker entirely
and run analysis inside the `backend` process instead. See BACKLOG.md's
Sprint 4/9 notes for that history.

Known, accepted tradeoff of this design (not a bug): a background task
lives only as long as the `backend` process that started it. If that
process restarts (a deploy, a dev `--reload` triggered by a file change,
a crash) while a task is running, the task is simply lost — no retry, no
record beyond whatever `execute_analysis` had already committed. The
earlier Celery+Redis setup queued durably across restarts; this one
doesn't. Deliberately accepted for simplicity — see BACKLOG.md's Sprint
11 notes for the actual choice and reasoning if this ever needs
revisiting.

Still a plain function, not a decorated task — calling it directly (as
the tests do) just runs the body synchronously, same as before.
"""
import os
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.traite_processing import execute_analysis
from app.services.vlm_extraction import get_extractor


def _sync_database_url() -> str:
    """Same override pattern as migrations/env.py — lets tests point this
    at the test database without a real background task actually running
    through the app's normal (dev) DATABASE_URL."""
    return os.environ.get("SYNC_DATABASE_URL_OVERRIDE") or get_settings().database_url


def run_traite_analysis(traite_id_str: str) -> None:
    engine = create_engine(_sync_database_url(), future=True)
    try:
        with Session(engine) as session:
            execute_analysis(uuid.UUID(traite_id_str), session, get_extractor())
            session.commit()
    finally:
        engine.dispose()
