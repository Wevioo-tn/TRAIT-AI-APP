"""Local username/password authentication against this app's own ``users``
table — replaces the earlier real LDAP bind (see BACKLOG.md's Sprint 7
notes for that history) per an explicit call to drop the LDAP dependency
and keep the stack simpler.

Argon2 verification (app/services/password_hash.py) is deliberately slow,
CPU-bound work — run off the event loop via ``run_in_threadpool``, the
same reason the earlier LDAP bind was, and the same reason the blocking
disk I/O in storage.py is.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db.models.user import User
from app.services.password_hash import verify_dummy_password, verify_password


async def authenticate(session: AsyncSession, username: str, password: str) -> bool:
    if not username or not password:
        return False

    user = await session.scalar(select(User).where(User.username == username, User.is_active.is_(True)))
    if user is None:
        # Same "authentication failed" outcome as a wrong password (see
        # routes/auth.py) — and now roughly the same timing too, via the
        # dummy verify below, so a response-time side-channel can't be
        # used to enumerate valid usernames either.
        await run_in_threadpool(verify_dummy_password, password)
        return False

    return await run_in_threadpool(verify_password, user.password_hash, password)
