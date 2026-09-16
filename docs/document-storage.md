# PostgreSQL document storage

## Behavior

New uploads store the original bytes in `public.traite_documents.content`, a
PostgreSQL `BYTEA` column. Images and PDFs use the same storage mechanism; OCR
support for PDF is unchanged. No Base64 encoding or MongoDB service is involved.

- File metadata and bytes are committed with the upload audit entry in one transaction.
- Replacement updates the existing document atomically. A failed transaction preserves
  the previous document. This is replacement, not document version history.
- Uploads for the same bill are serialized to prevent concurrent duplicate faces.
- The existing authenticated download URL returns the original bytes and MIME type.
- Metadata JSON does not contain the image payload. ORM metadata queries defer the
  binary column; only download and OCR load it.
- The existing 15 MiB upload limit still applies. Files are read with a bounded size.
- Database constraints require a content payload or legacy path, and require binary
  payload length to match the recorded size.

`fichier_chemin` is now nullable and retained only for compatibility with old uploads.
New uploads set it to null. For an old record with null `content`, download and OCR
read the old file from `UPLOAD_DIR`. A missing or size-mismatched file is not returned
as a successful download. Once `content` is populated, it is authoritative and the
file path is no longer used.

## Fresh installation

Apply `alembic upgrade head` before using the backend. No backfill is needed when
there are no existing documents. The current Dockerfiles already include `scripts/`
and `migrations/`; no new dependency or frontend change is needed.

## Existing staging installation

Run from the project root on the staging server. The database must remain available.
Take a database backup and preserve a copy of the old uploads volume before starting.
This procedure affects application availability: use a maintenance window.

1. Deploy the updated source. Stop the backend so an old process cannot write more
   filesystem documents while migration is running. Build the new image:

   ```bash
   docker compose -f docker-compose.staging.yml stop backend
   docker compose -f docker-compose.staging.yml build backend
   ```

2. Apply the additive schema migration using a one-off container:

   ```bash
   docker compose -f docker-compose.staging.yml run --rm --no-deps backend alembic upgrade head
   ```

   Revision `f6a9c2d4e8b1` adds the binary column and constraints. It does not read
   files during DDL migration, so it also works on fresh databases and DB-only hosts.

3. Check that all legacy files are accessible and match their recorded sizes:

   ```bash
   docker compose -f docker-compose.staging.yml run --rm --no-deps backend python -m scripts.migrate_document_storage --dry-run
   ```

   A dry run never writes document bytes. Its remaining count is expected to stay
   unchanged. Fix any reported file or path errors before continuing. `UPLOAD_DIR`
   must match the mounted root used by the stored paths, normally `/app/uploads`.
   Paths outside that directory are rejected, including symlinks resolving outside it.

4. Copy and verify the original bytes:

   ```bash
   docker compose -f docker-compose.staging.yml run --rm --no-deps backend python -m scripts.migrate_document_storage
   ```

   The command processes ID batches (default 100) and commits one document at a time.
   It verifies the SHA-256 digest of bytes read back from PostgreSQL before commit.
   It skips previously migrated documents and can be rerun after an interruption.
   Missing or size-mismatched files are reported; successful rows remain migrated.
   A nonzero exit status means migration is incomplete or an error occurred.
   Fix the cause and rerun. The script never deletes source files or changes their metadata.

5. Confirm there are no legacy rows remaining, then start the updated backend:

   ```bash
   docker compose -f docker-compose.staging.yml run --rm --no-deps backend python -m scripts.migrate_document_storage
   docker compose -f docker-compose.staging.yml up -d --no-deps backend
   docker compose -f docker-compose.staging.yml logs --tail=100 backend
   ```

   A completed rerun prints `migrated: 0`, `failed: 0` and
   `remaining legacy documents: 0`. Through the application, check downloads of
   both faces of an old bill, then upload and analyze a new bill. No data migration
   has been performed on your staging server by merely updating the source code.

For development or production, use the corresponding Compose filename in these commands.
The migration command reads the application's `DATABASE_URL`. If you deliberately set
`ALEMBIC_DATABASE_URL`, ensure it targets the same database before running schema migration.

## Backup and recovery

After all rows have binary content, a full PostgreSQL backup includes document bytes
alongside application data. Use your normal full database backup/restore procedure
(for example, a full `pg_dump` custom-format backup). Schema-only or selected-table
backups are not sufficient. Restore into an isolated database and verify document
downloads as part of backup testing.

Until backfill finishes, back up both PostgreSQL and the old uploads volume. Keep
the volume mounted during the transition; the repository intentionally retains it.
After migration and a verified backup, its mount is optional for document serving.
No automatic volume cleanup is included.

Database storage increases database, WAL and backup size. Image payloads are kept out
of list/detail responses, but upload/download and OCR still load each requested file
into memory. The per-file size limit remains important.

Deleting document rows, including through the existing `clear-db.ps1` script's
`TRUNCATE traites CASCADE`, now deletes their stored bytes as well. Legacy files left
on disk are not automatically deleted.

## Rollback

Do not downgrade the schema or run the old filesystem-only application after new
database-backed uploads have been accepted. Old code cannot read those documents.
The migration refuses to downgrade while any row has binary content to prevent
silent data loss. An operational rollback requires either a verified pre-migration
backup (with its matching files) or an explicit export of all database documents to
verified legacy files before clearing the binary content and downgrading.

## Verification SQL

Run against the application database using your usual PostgreSQL administration tool:

```sql
SELECT count(*) AS total_documents,
       count(*) FILTER (WHERE content IS NOT NULL) AS database_documents,
       count(*) FILTER (WHERE content IS NULL) AS legacy_documents,
       coalesce(sum(octet_length(content)), 0) AS stored_bytes
FROM public.traite_documents;
```

Do not print raw `content` values into application logs or administration reports.
