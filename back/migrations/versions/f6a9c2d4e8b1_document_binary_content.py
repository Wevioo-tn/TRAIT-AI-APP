"""Store document payloads in PostgreSQL, retaining legacy paths for backfill."""
from alembic import op
import sqlalchemy as sa

revision = "f6a9c2d4e8b1"
down_revision = "e2b5c8d1f6a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("traite_documents", sa.Column("content", sa.LargeBinary(), nullable=True))
    op.alter_column("traite_documents", "fichier_chemin", existing_type=sa.String(500), nullable=True)
    op.create_check_constraint(
        "ck_traite_documents_storage", "traite_documents",
        "content IS NOT NULL OR fichier_chemin IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_traite_documents_content_size", "traite_documents",
        "content IS NULL OR octet_length(content) = taille_octets",
    )


def downgrade() -> None:
    # Never silently discard scans or assume the old volume is still available.
    if op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM traite_documents WHERE content IS NOT NULL)"
    )).scalar():
        raise RuntimeError(
            "Cannot downgrade while database-backed documents exist. "
            "Export and verify their files before clearing content, or restore a pre-migration backup."
        )
    op.drop_constraint("ck_traite_documents_content_size", "traite_documents", type_="check")
    op.drop_constraint("ck_traite_documents_storage", "traite_documents", type_="check")
    op.alter_column("traite_documents", "fichier_chemin", existing_type=sa.String(500), nullable=False)
    op.drop_column("traite_documents", "content")
