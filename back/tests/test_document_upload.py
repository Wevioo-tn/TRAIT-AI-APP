"""Sprint 2 — document upload/download."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.traite import AuditLogEntry

TRAITE_PAYLOAD = {
    "numero_lcn": "011570763437",
    "montant": "8117.504",
    "date_echeance": "2026-08-28",
    "date_creation_traite": "2026-08-05",
}


async def _create_traite(client) -> str:
    response = await client.post("/api/traites", json=TRAITE_PAYLOAD)
    return response.json()["id"]


async def test_upload_recto_and_verso(client):
    traite_id = await _create_traite(client)

    recto = await client.post(
        f"/api/traites/{traite_id}/documents",
        params={"face": "recto"},
        files={"file": ("recto.jpg", b"fake-jpeg-bytes", "image/jpeg")},
    )
    assert recto.status_code == 201
    body = recto.json()
    assert body["face"] == "recto"
    assert body["fichier_nom"] == "recto.jpg"
    assert body["taille_octets"] == len(b"fake-jpeg-bytes")

    verso = await client.post(
        f"/api/traites/{traite_id}/documents",
        params={"face": "verso"},
        files={"file": ("verso.pdf", b"%PDF-fake", "application/pdf")},
    )
    assert verso.status_code == 201

    detail = await client.get(f"/api/traites/{traite_id}")
    faces = {d["face"] for d in detail.json()["documents"]}
    assert faces == {"recto", "verso"}


async def test_upload_rejects_unknown_traite(client):
    response = await client.post(
        "/api/traites/00000000-0000-0000-0000-000000000000/documents",
        params={"face": "recto"},
        files={"file": ("recto.jpg", b"data", "image/jpeg")},
    )
    assert response.status_code == 404


async def test_upload_rejects_unsupported_content_type(client):
    traite_id = await _create_traite(client)
    response = await client.post(
        f"/api/traites/{traite_id}/documents",
        params={"face": "recto"},
        files={"file": ("recto.exe", b"data", "application/x-msdownload")},
    )
    assert response.status_code == 422


async def test_upload_rejects_oversized_file(client, monkeypatch):
    import app.api.routes.traites as traites_routes

    monkeypatch.setattr(traites_routes.settings, "max_upload_size_bytes", 10)

    traite_id = await _create_traite(client)
    response = await client.post(
        f"/api/traites/{traite_id}/documents",
        params={"face": "recto"},
        files={"file": ("recto.jpg", b"this-is-more-than-ten-bytes", "image/jpeg")},
    )
    assert response.status_code == 413


async def test_upload_duplicate_face_without_replace_is_rejected(client):
    traite_id = await _create_traite(client)
    first = {"file": ("recto.jpg", b"v1", "image/jpeg")}
    second = {"file": ("recto-v2.jpg", b"v2", "image/jpeg")}

    ok = await client.post(f"/api/traites/{traite_id}/documents", params={"face": "recto"}, files=first)
    assert ok.status_code == 201

    conflict = await client.post(f"/api/traites/{traite_id}/documents", params={"face": "recto"}, files=second)
    assert conflict.status_code == 409


async def test_upload_duplicate_face_with_replace_overwrites(client):
    traite_id = await _create_traite(client)
    first = {"file": ("recto.jpg", b"v1", "image/jpeg")}
    second = {"file": ("recto-v2.jpg", b"v2", "image/jpeg")}

    await client.post(f"/api/traites/{traite_id}/documents", params={"face": "recto"}, files=first)
    replaced = await client.post(
        f"/api/traites/{traite_id}/documents", params={"face": "recto", "replace": "true"}, files=second
    )
    assert replaced.status_code == 201
    assert replaced.json()["fichier_nom"] == "recto-v2.jpg"

    detail = await client.get(f"/api/traites/{traite_id}")
    recto_docs = [d for d in detail.json()["documents"] if d["face"] == "recto"]
    assert len(recto_docs) == 1
    assert recto_docs[0]["fichier_nom"] == "recto-v2.jpg"


async def test_download_document_returns_content(client):
    traite_id = await _create_traite(client)
    content = b"this-is-the-scanned-bytes"
    await client.post(
        f"/api/traites/{traite_id}/documents",
        params={"face": "recto"},
        files={"file": ("recto.jpg", content, "image/jpeg")},
    )

    response = await client.get(f"/api/traites/{traite_id}/documents/recto")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "image/jpeg"


async def test_download_missing_document_returns_404(client):
    traite_id = await _create_traite(client)
    response = await client.get(f"/api/traites/{traite_id}/documents/verso")
    assert response.status_code == 404


async def test_upload_writes_audit_log_entry(client, sync_engine):
    traite_id = await _create_traite(client)
    await client.post(
        f"/api/traites/{traite_id}/documents",
        params={"face": "recto"},
        files={"file": ("recto.jpg", b"data", "image/jpeg")},
    )

    with Session(sync_engine) as session:
        entries = session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.traite_id == uuid.UUID(traite_id),
                AuditLogEntry.action == "document_televerse",
            )
        ).all()
    assert len(entries) == 1
    assert entries[0].details["face"] == "recto"
