"""Audit trail write-through.

Every mutation in the API calls this so "toute action est horodatée et
tracée" (the design's own promise) is actually true instead of aspirational.

``user`` is the real authenticated username (from the request's JWT — see
app/api/deps.py) for every API-triggered call site. The one exception is
the Celery worker's own system-initiated actions (analysis
launched/succeeded/failed — see app/services/traite_processing.py), which
hardcode "system" since there's no HTTP-authenticated caller in that
context, not because authentication doesn't exist.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.traite import AuditLogEntry


async def log_action(
    session: AsyncSession,
    *,
    user: str,
    action: str,
    traite_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> None:
    session.add(
        AuditLogEntry(
            traite_id=traite_id,
            utilisateur=user,
            action=action,
            details=details,
        )
    )
