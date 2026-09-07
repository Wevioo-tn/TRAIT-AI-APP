"""The Celery task wrapping execute_analysis.

Note this is deliberately *callable directly* for tests
(``launch_traite_analysis(str(traite_id))``, bypassing ``.delay()``) — a
``@celery_app.task``-decorated function is still a plain function; calling
it directly runs the body synchronously with no broker involved at all.
Only ``.delay()``/``.apply_async()`` need Redis. That's what lets the task
logic be tested without spinning up a broker.
"""
import os
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.traite_processing import execute_analysis
from app.services.vlm_extraction import get_extractor
from app.worker import celery_app


def _sync_database_url() -> str:
    """Same override pattern as migrations/env.py — lets tests point this
    at the test database without needing a real worker process."""
    return os.environ.get("SYNC_DATABASE_URL_OVERRIDE") or get_settings().database_url


@celery_app.task(name="traites.launch_analysis")
def launch_traite_analysis(traite_id_str: str) -> None:
    engine = create_engine(_sync_database_url(), future=True)
    try:
        with Session(engine) as session:
            execute_analysis(uuid.UUID(traite_id_str), session, get_extractor())
            session.commit()
    finally:
        engine.dispose()
