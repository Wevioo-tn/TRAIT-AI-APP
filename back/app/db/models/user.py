"""Local application users — replaces the earlier real LDAP bind (see
BACKLOG.md's Sprint 7 notes for that history) with a users table in this
app's own database, per an explicit call to drop the LDAP dependency and
keep the stack simpler. See app/services/local_auth.py for how a password
is actually verified against ``password_hash`` — never in this module.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, uuid_pk


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # An Argon2id hash (see app/services/password_hash.py) — the encoded
    # string already carries the algorithm/salt/parameters, so no separate
    # salt column is needed. Never a plain-text password, ever.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
