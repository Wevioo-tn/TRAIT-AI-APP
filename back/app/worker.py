"""Celery application instance. Run as a worker via:
    celery -A app.worker worker --loglevel=info
(see the `worker` service in docker-compose.yml).
"""
from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("trait_ai", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.broker_connection_retry_on_startup = True

# Explicit import rather than autodiscover_tasks(): with a single, known
# task module this is simpler and less surprising than Celery's discovery
# convention (autodiscover_tasks(["app.tasks"]) actually looks for an
# app.tasks.tasks submodule, not app.tasks itself — caught live, the worker
# started cleanly but listed zero registered tasks).
import app.tasks.traite_processing  # noqa: E402, F401
