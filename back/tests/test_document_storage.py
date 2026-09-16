"""BYTEA persistence, transaction safety, and resumable legacy migration."""
import asyncio
import importlib
import uuid
from datetime import date
from decimal import Decimal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.traite import Face, Traite, TraiteDocument
from app.services.storage import read_document_content, read_legacy_content
from app.services.traite_processing import _read_document
from scripts.migrate_document_storage import migrate_documents


async def upload(client, bill_id, content=b"\x00\xff\x80original-scan", **params):
    return await client.post(
        f"/api/traites/{bill_id}/documents", params={"face": "recto", **params},
        files={"file": ("scan.jpg", content, "image/jpeg")},
    )


async def test_binary_round_trip_without_disk_and_metadata_does_not_load_bytes(client, sync_engine, tmp_path):
    bill_id = (await client.post("/api/traites", json={})).json()["id"]
    response = await upload(client, bill_id)
    assert response.status_code == 201
    assert "content" not in response.json()
    assert list(tmp_path.iterdir()) == []
    with Session(sync_engine) as session:
        document = session.scalar(select(TraiteDocument))
        assert "content" in inspect(document).unloaded
        assert document.fichier_chemin is None
        assert document.content == b"\x00\xff\x80original-scan"
        assert _read_document(uuid.UUID(bill_id), [document], Face.RECTO) == document.content
    downloaded = await client.get(f"/api/traites/{bill_id}/documents/recto")
    assert downloaded.content == b"\x00\xff\x80original-scan"
    assert downloaded.headers["cache-control"] == "private, no-store"
    detail = (await client.get(f"/api/traites/{bill_id}")).json()
    assert "content" not in detail["documents"][0]


async def test_failed_replacement_keeps_original_bytes_and_metadata(client, sync_engine, monkeypatch):
    bill_id = (await client.post("/api/traites", json={})).json()["id"]
    original = (await upload(client, bill_id, b"original")).json()

    async def failed_audit(*args, **kwargs):
        raise RuntimeError("Simulated audit failure")

    monkeypatch.setattr("app.api.routes.traites.log_action", failed_audit)
    with pytest.raises(RuntimeError, match="Simulated audit failure"):
        await upload(client, bill_id, b"replacement", replace="true")
    with Session(sync_engine) as session:
        document = session.scalar(select(TraiteDocument))
        assert str(document.id) == original["id"]
        assert document.content == b"original"
        assert document.taille_octets == len(b"original")


async def test_concurrent_uploads_of_same_face_have_one_winner(client):
    bill_id = (await client.post("/api/traites", json={})).json()["id"]
    responses = await asyncio.gather(upload(client, bill_id, b"first"), upload(client, bill_id, b"second"))
    assert sorted(r.status_code for r in responses) == [201, 409]
    downloaded = await client.get(f"/api/traites/{bill_id}/documents/recto")
    assert downloaded.content in (b"first", b"second")


def add_legacy_document(engine, path, content):
    with Session(engine) as session, session.begin():
        bill = Traite(numero_lcn=uuid.uuid4().hex[:20], montant=Decimal("1.000"),
                      date_echeance=date(2027, 1, 1), date_creation_traite=date(2026, 1, 1))
        session.add(bill)
        session.flush()
        document = TraiteDocument(traite_id=bill.id, face=Face.RECTO, fichier_nom=path.name,
                                 fichier_chemin=str(path), content_type="image/jpeg", taille_octets=len(content))
        session.add(document)
        session.flush()
        return document.id, bill.id


async def test_legacy_download_backfill_and_download_after_file_removal(client, sync_engine, tmp_path):
    source = tmp_path / "legacy.jpg"
    source.write_bytes(b"legacy-data")
    document_id, bill_id = add_legacy_document(sync_engine, source, b"legacy-data")
    assert (await client.get(f"/api/traites/{bill_id}/documents/recto")).content == b"legacy-data"
    preview = migrate_documents(sync_engine, dry_run=True, batch_size=1)
    assert (preview.checked, preview.migrated, preview.remaining) == (1, 0, 1)
    with Session(sync_engine) as session:
        assert session.get(TraiteDocument, document_id).content is None
    result = migrate_documents(sync_engine, batch_size=1)
    assert (result.migrated, result.failed, result.remaining) == (1, 0, 0)
    assert source.read_bytes() == b"legacy-data"
    source.unlink()
    assert (await client.get(f"/api/traites/{bill_id}/documents/recto")).content == b"legacy-data"
    assert migrate_documents(sync_engine).migrated == 0


def test_backfill_reports_missing_and_corrupt_files_without_losing_other_documents(
    sync_engine, clean_app_tables, tmp_path, monkeypatch,
):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    good = tmp_path / "good.jpg"
    good.write_bytes(b"good")
    short = tmp_path / "truncated.jpg"
    short.write_bytes(b"x")
    missing = tmp_path / "missing.jpg"
    good_id, _ = add_legacy_document(sync_engine, good, b"good")
    short_id, _ = add_legacy_document(sync_engine, short, b"complete")
    missing_id, _ = add_legacy_document(sync_engine, missing, b"missing")
    result = migrate_documents(sync_engine, batch_size=1)
    assert (result.migrated, result.failed, result.remaining) == (1, 2, 2)
    with Session(sync_engine) as session:
        assert session.get(TraiteDocument, good_id).content == b"good"
        assert session.get(TraiteDocument, short_id).content is None
        assert session.get(TraiteDocument, missing_id).content is None
    short.write_bytes(b"complete")
    missing.write_bytes(b"missing")
    result = migrate_documents(sync_engine)
    assert (result.migrated, result.failed, result.remaining) == (2, 0, 0)


def test_legacy_reader_rejects_paths_outside_upload_root(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    source = tmp_path / "outside.jpg"
    source.write_bytes(b"outside")
    with pytest.raises(ValueError, match="outside UPLOAD_DIR"):
        read_legacy_content(str(source), 7)


async def test_missing_legacy_content_returns_controlled_error(client, sync_engine, tmp_path):
    _, bill_id = add_legacy_document(sync_engine, tmp_path / "missing.jpg", b"missing")
    response = await client.get(f"/api/traites/{bill_id}/documents/recto")
    assert response.status_code == 503
    assert response.json()["detail"] == "Document content is unavailable."


def test_database_content_is_authoritative_even_when_legacy_path_exists():
    document = TraiteDocument(content=b"", fichier_chemin="/unavailable/old.jpg", taille_octets=0)
    assert read_document_content(document) == b""


async def test_database_constraints_and_downgrade_protect_document_content(client, sync_engine, monkeypatch):
    bill_id = (await client.post("/api/traites", json={})).json()["id"]
    await upload(client, bill_id)
    with sync_engine.connect() as connection:
        column_type = connection.scalar(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='traite_documents' AND column_name='content'"
        ))
        assert column_type == "bytea"
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(text("UPDATE traite_documents SET taille_octets=999"))
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(text("UPDATE traite_documents SET content=NULL, fichier_chemin=NULL"))
        migration = importlib.import_module("migrations.versions.f6a9c2d4e8b1_document_binary_content")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="Cannot downgrade"):
            migration.downgrade()
