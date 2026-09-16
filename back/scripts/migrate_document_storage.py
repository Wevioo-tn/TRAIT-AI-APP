"""Copy legacy scans into PostgreSQL BYTEA without deleting source files.

Run after `alembic upgrade head`, inside the backend with its old uploads volume
mounted. Use --dry-run first. Re-running skips already migrated documents.
"""
import argparse
import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, undefer

from app.core.config import get_settings
from app.db.models.traite import TraiteDocument
from app.services.storage import read_legacy_content

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    checked: int = 0
    migrated: int = 0
    failed: int = 0
    remaining: int = 0


def migrate_documents(engine: Engine, *, dry_run: bool = False, batch_size: int = 100) -> MigrationResult:
    """Process bounded ID batches, committing and verifying one document at a time."""
    if batch_size < 1:
        raise ValueError("Batch size must be positive.")
    result = MigrationResult()
    cursor = None
    while True:
        with Session(engine) as session:
            query = select(TraiteDocument.id).where(TraiteDocument.content.is_(None))
            if cursor is not None:
                query = query.where(TraiteDocument.id > cursor)
            ids = session.scalars(query.order_by(TraiteDocument.id).limit(batch_size)).all()
        if not ids:
            break
        for document_id in ids:
            cursor = document_id
            try:
                with Session(engine) as session, session.begin():
                    document = session.scalar(
                        select(TraiteDocument)
                        .where(TraiteDocument.id == document_id)
                        .options(undefer(TraiteDocument.content))
                        .with_for_update()
                    )
                    # A concurrent upload or migration may already have replaced it.
                    if document is None or document.content is not None:
                        continue
                    if not document.fichier_chemin:
                        raise ValueError("Legacy document has no source path.")
                    content = read_legacy_content(document.fichier_chemin, document.taille_octets)
                    result.checked += 1
                    if not dry_run:
                        document.content = content
                        session.flush()
                        persisted = session.scalar(
                            select(TraiteDocument.content).where(TraiteDocument.id == document_id)
                        )
                        if persisted is None or hashlib.sha256(persisted).digest() != hashlib.sha256(content).digest():
                            raise ValueError("Database content verification failed.")
                if not dry_run:
                    result.migrated += 1
            except (OSError, ValueError):
                result.failed += 1
                # No file contents or credentials are included in the log.
                logger.exception("Could not migrate document %s", document_id)
        # Failed rows are retried on the next invocation, never in a busy loop.
    with Session(engine) as session:
        result.remaining = session.scalar(
            select(func.count()).select_from(TraiteDocument).where(TraiteDocument.content.is_(None))
        ) or 0
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Check source files without writing database content.")
    parser.add_argument("--batch-size", type=int, default=100, help="Number of document IDs fetched at a time.")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    logging.basicConfig(level=logging.INFO)
    # Use the application's database, not a potentially unrelated Alembic override.
    engine = create_engine(get_settings().database_url)
    try:
        result = migrate_documents(engine, dry_run=args.dry_run, batch_size=args.batch_size)
    finally:
        engine.dispose()
    print(
        f"Checked: {result.checked}; migrated: {result.migrated}; "
        f"failed: {result.failed}; remaining legacy documents: {result.remaining}."
    )
    return 1 if result.failed or (not args.dry_run and result.remaining) else 0


if __name__ == "__main__":
    raise SystemExit(main())
