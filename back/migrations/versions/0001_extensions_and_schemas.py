"""extensions and schemas

Revision ID: 0001
Revises:
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # gen_random_uuid() for our own primary keys.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # Local stand-in for the external IMX referential (see app/db/models/imx.py).
    op.execute("CREATE SCHEMA IF NOT EXISTS imx")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS imx CASCADE")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
