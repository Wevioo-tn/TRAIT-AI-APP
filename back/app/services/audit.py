"""Audit trail write-through.

Every mutation in the API calls this so "toute action est horodatée et
tracée" (the design's own promise) is actually true instead of aspirational.

``utilisateur`` is hardcoded to "system" by callers for now — there is no
authentication yet (Sprint 7 / LDAP). This is a known, temporary gap, not a
silent omission.
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
