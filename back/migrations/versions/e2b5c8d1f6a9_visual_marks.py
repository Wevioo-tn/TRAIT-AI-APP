"""Persist visual signature/stamp presence separately from manual verification."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e2b5c8d1f6a9"
down_revision = "d3f7a1c9b2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("traites", sa.Column("visual_marks", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("traites", "visual_marks")
