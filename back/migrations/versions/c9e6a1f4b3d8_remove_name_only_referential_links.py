"""Remove historical IMX links created from fuzzy names without a RIB hit.

Revision ID: c9e6a1f4b3d8
Revises: b8d5f0e3a2c7
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c9e6a1f4b3d8"
down_revision: Union[str, None] = "b8d5f0e3a2c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Suggestions based on names remain readable (scan/reference/score),
    # but are not foreign-key links to IMX entities.
    op.execute(
        """
        UPDATE rapprochements_nlp
        SET code_adherent_matche = NULL,
            code_debiteur_matche = NULL
        WHERE methode_identification::text = 'NOM_SEUL'
        """
    )
    op.execute(
        """
        UPDATE traites AS t
        SET code_adherent = NULL,
            code_debiteur = NULL
        WHERE NOT EXISTS (
            SELECT 1
            FROM rapprochements_nlp AS r
            WHERE r.traite_id = t.id
              AND r.role::text = 'RIB'
              AND r.methode_identification::text = 'RIB'
              AND r.code_debiteur_matche IS NOT NULL
        )
        """
    )


def downgrade() -> None:
    # Removed links cannot be reconstructed safely from fuzzy suggestions.
    pass
