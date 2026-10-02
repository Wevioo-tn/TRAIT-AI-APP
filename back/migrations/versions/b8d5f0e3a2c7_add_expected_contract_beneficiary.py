"""Store the beneficiary expected by the adherent's IMX contract.

Revision ID: b8d5f0e3a2c7
Revises: a7c4e9d2f1b6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d5f0e3a2c7"
down_revision: Union[str, None] = "a7c4e9d2f1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "adherents",
        sa.Column("beneficiaire_attendu", sa.String(length=255), nullable=True),
        schema="imx",
    )


def downgrade() -> None:
    op.drop_column("adherents", "beneficiaire_attendu", schema="imx")
