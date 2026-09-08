"""rapprochement_identification_method

Revision ID: a4d8e1f6c2b9
Revises: 49a3fe136ee4
Create Date: 2026-09-08 12:00:00.000000

RIB-first débiteur identification (per your call — see UC-01 étape 4 of the
functional spec): rapprochements_nlp now records *how* each role's
code_*_matche was actually resolved (rib | nom_seul) plus an explicit flag
for a RIB-matched débiteur whose scanned name corroboration comes back
suspiciously low. See app/services/traite_processing.py and
app/services/nlp_matching.py.

Autogenerate would also propose dropping `extractions_ia` here — the usual
false positive (see 49a3fe136ee4's docstring), not applicable since this
migration is hand-written and never touches that table at all.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a4d8e1f6c2b9'
down_revision: Union[str, None] = '49a3fe136ee4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    methode_identification = sa.Enum('RIB', 'NOM_SEUL', name='methode_identification')
    methode_identification.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'rapprochements_nlp',
        sa.Column('methode_identification', methode_identification, server_default='NOM_SEUL', nullable=False),
    )
    op.add_column(
        'rapprochements_nlp',
        sa.Column('alerte_ecart_nom', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('rapprochements_nlp', 'alerte_ecart_nom')
    op.drop_column('rapprochements_nlp', 'methode_identification')
    # Same reasoning as every other enum drop in this project's migrations
    # (see 0002_create_all_tables.py) — Postgres doesn't drop the type with
    # the column, and a downgrade-then-upgrade cycle (exactly what the test
    # suite does every run) fails the second time with "type already exists"
    # without this.
    op.execute("DROP TYPE IF EXISTS methode_identification")
