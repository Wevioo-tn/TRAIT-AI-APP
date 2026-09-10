"""add_rib_role_nlp

Revision ID: c8e4b6f2a3d7
Revises: b7f3a2c9e1d4
Create Date: 2026-09-10 09:00:00.000000

TR-115 — a dedicated RapprochementNlp row (role='rib') so a reviewer sees
the actual RIB match explicitly (UC-01 étape 4) instead of only inferring
it from the "Identifié par RIB" badge under TIREUR/TIRE. See
app/services/traite_processing.py.

ALTER TYPE ... ADD VALUE must run outside the surrounding transaction on
older Postgres — Alembic's own migration transaction is fine on the
Postgres 16 this project runs (16-alpine, see docker-compose.yml), but
the new value can't be used in the SAME transaction that adds it. Not an
issue here since nothing in this migration inserts a row.

No autogenerate involved — hand-written, single ALTER TYPE statement.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c8e4b6f2a3d7'
down_revision: Union[str, None] = 'b7f3a2c9e1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLAlchemy's Enum column stores the Python enum member's *name*
    # (RoleNlp.RIB.name == "RIB"), not its .value ("rib") — confirmed
    # against the existing TIREUR/TIRE/ORDRE labels already in this type
    # (same convention methode_identification's RIB/NOM_SEUL values
    # already use, see a4d8e1f6c2b9). Adding lowercase 'rib' here would
    # silently never match what the ORM actually sends.
    op.execute("ALTER TYPE role_nlp ADD VALUE IF NOT EXISTS 'RIB'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Rebuilding the enum
    # without 'rib' would require rewriting every row/column using it —
    # deliberately not attempted here, same "irreversible enum growth"
    # tradeoff every Postgres project accepts once it adds an enum value.
    # A real rollback of this migration means restoring from a backup
    # taken before it ran, not running `alembic downgrade`.
    pass
