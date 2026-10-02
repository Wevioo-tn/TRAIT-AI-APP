"""Add a dedicated IMX reconciliation row for the drawee address.

Revision ID: a7c4e9d2f1b6
Revises: f6a9c2d4e8b1
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a7c4e9d2f1b6"
down_revision: Union[str, None] = "f6a9c2d4e8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SAEnum persists the Python member name, not RoleNlp.value.
    op.execute("ALTER TYPE role_nlp ADD VALUE IF NOT EXISTS 'ADRESSE_TIRE'")


def downgrade() -> None:
    # PostgreSQL cannot remove one enum value without rebuilding the type.
    pass
