"""extractions_ia audit log (Sprint 8/9)

Written as raw SQL (``op.execute``), not the SQLAlchemy-Core DDL builder
(``op.create_table``) the other migrations use — deliberately: this table
is never written or read through the ORM at all (see
app/services/extraction_log.py), so its own DDL stays raw SQL too rather
than mixing a SQLAlchemy-generated schema with a hand-written psycopg data
path.

Revision ID: a91f3c2d8e07
Revises: 530cfcd7d929
Create Date: 2026-09-03 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a91f3c2d8e07'
down_revision: Union[str, None] = '530cfcd7d929'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE extractions_ia (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            traite_id UUID NOT NULL REFERENCES traites(id) ON DELETE CASCADE,
            fournisseur VARCHAR(30) NOT NULL,
            modele VARCHAR(120) NOT NULL,
            succes BOOLEAN NOT NULL,
            reponse_brute TEXT,
            erreur TEXT,
            duree_ms INTEGER NOT NULL,
            cree_le TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_extractions_ia_traite_id ON extractions_ia (traite_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_extractions_ia_traite_id")
    op.execute("DROP TABLE IF EXISTS extractions_ia")
