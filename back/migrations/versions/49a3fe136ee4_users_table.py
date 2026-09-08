"""users_table

Revision ID: 49a3fe136ee4
Revises: a91f3c2d8e07
Create Date: 2026-09-08 09:09:31.998430

Local username/password login (app/db/models/user.py, app/services/
local_auth.py) replacing the earlier real LDAP bind — see BACKLOG.md's
Sprint 7 notes for that history.

Autogenerate also proposed dropping `extractions_ia` — a false positive,
stripped by hand from both upgrade()/downgrade() below: that table is
deliberately raw-SQL-only (see 0004_extractions_ia_log.py and
app/services/extraction_log.py), never modeled as a SQLAlchemy class, so
it's invisible to Base.metadata and autogenerate always reads that as "this
table should be removed." Expect this same false positive on every future
autogenerate too — this isn't a one-off to fix, it's the permanent cost of
that table's raw-SQL design (see README.md's "Raw extraction audit log"
section for why that tradeoff was made anyway).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '49a3fe136ee4'
down_revision: Union[str, None] = 'a91f3c2d8e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )


def downgrade() -> None:
    op.drop_table('users')
