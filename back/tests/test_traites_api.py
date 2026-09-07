"""Sprint 1 — Traites API: list, detail, create."""
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.traite import AuditLogEntry, VerificationCode

VALID_PAYLOAD = {
    "numero_lcn": "011570763437",
    "montant": "8117.504",
    "date_echeance": "2026-08-28",
    "date_creation_traite": "2026-08-05",
}


async def test_create_traite_seeds_four_verification_slots(client):
    response = await client.post("/api/traites", json=VALID_PAYLOAD)
    assert response.status_code == 201

    body = response.json()
    assert body["numero_lcn"] == "011570763437"
    assert body["statut"] == "À traiter"
    codes = {v["code_verification"] for v in body["verifications_manuelles"]}
    assert codes == {c.value for c in VerificationCode}
    assert all(v["statut"] is None for v in body["verifications_manuelles"])
    # Nothing populates these until the OCR/NLP pipeline (Sprint 4) exists.
    assert body["champs_extraits"] == []
    assert body["rapprochements_nlp"] == []
    assert body["decisions"] == []


async def test_create_traite_rejects_duplicate_numero_lcn(client):
    first = await client.post("/api/traites", json=VALID_PAYLOAD)
    assert first.status_code == 201

    duplicate = await client.post("/api/traites", json=VALID_PAYLOAD)
    assert duplicate.status_code == 409


async def test_create_traite_rejects_non_positive_montant(client):
    payload = {**VALID_PAYLOAD, "montant": "0"}
    response = await client.post("/api/traites", json=payload)
    assert response.status_code == 422


async def test_create_traite_without_any_intake_generates_placeholders(client):
    """The queue screen creates a traite from just the recto/verso scans
    now (no bordereau intake form) — an empty body must still succeed,
    with the server filling in a unique numero_lcn and today's dates."""
    response = await client.post("/api/traites", json={})
    assert response.status_code == 201

    body = response.json()
    assert body["numero_lcn"].startswith("AUTO-")
    assert body["montant"] == "0.001"
    today = date.today().isoformat()
    assert body["date_echeance"] == today
    assert body["date_creation_traite"] == today


async def test_create_traite_with_blank_strings_generates_placeholders_too(client):
    """A client that serializes an untouched form as empty strings (rather
    than omitting the keys) must get the same server-generated defaults,
    not a 422 — see TraiteCreate's blank-string validator."""
    response = await client.post(
        "/api/traites",
        json={"numero_lcn": "", "montant": "", "date_echeance": "", "date_creation_traite": ""},
    )
    assert response.status_code == 201
    assert response.json()["numero_lcn"].startswith("AUTO-")


async def test_create_traite_generated_numero_lcn_is_unique_across_calls(client):
    first = await client.post("/api/traites", json={})
    second = await client.post("/api/traites", json={})
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["numero_lcn"] != second.json()["numero_lcn"]


async def test_create_traite_partial_intake_keeps_provided_values(client):
    """Providing some fields (e.g. a real numero_lcn known up front) but
    not others is honored field-by-field, not all-or-nothing."""
    response = await client.post("/api/traites", json={"numero_lcn": "PARTIAL-0001"})
    assert response.status_code == 201
    body = response.json()
    assert body["numero_lcn"] == "PARTIAL-0001"
    assert body["montant"] == "0.001"  # still generated


async def test_create_traite_writes_audit_log_entry(client, sync_engine):
    created = await client.post("/api/traites", json=VALID_PAYLOAD)
    traite_id = uuid.UUID(created.json()["id"])

    with Session(sync_engine) as session:
        entries = session.scalars(
            select(AuditLogEntry).where(AuditLogEntry.traite_id == traite_id)
        ).all()
    assert len(entries) == 1
    assert entries[0].action == "traite_creee"


async def test_get_traite_returns_detail(client):
    created = await client.post("/api/traites", json=VALID_PAYLOAD)
    traite_id = created.json()["id"]

    response = await client.get(f"/api/traites/{traite_id}")
    assert response.status_code == 200
    assert response.json()["numero_lcn"] == "011570763437"


async def test_get_traite_404_for_unknown_id(client):
    response = await client.get("/api/traites/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_list_traites_filters_by_statut(client):
    await client.post("/api/traites", json=VALID_PAYLOAD)
    other = {**VALID_PAYLOAD, "numero_lcn": "999999999999"}
    await client.post("/api/traites", json=other)

    response = await client.get("/api/traites", params={"statut": "À traiter"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(item["statut"] == "À traiter" for item in body["items"])


async def test_list_traites_paginates(client):
    for i in range(3):
        payload = {**VALID_PAYLOAD, "numero_lcn": f"00000000000{i}"}
        await client.post("/api/traites", json=payload)

    response = await client.get("/api/traites", params={"page": 1, "per_page": 2})
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["per_page"] == 2


async def test_list_traites_sorted_by_reception_ascending(client):
    first = await client.post("/api/traites", json={**VALID_PAYLOAD, "numero_lcn": "111111111111"})
    second = await client.post("/api/traites", json={**VALID_PAYLOAD, "numero_lcn": "222222222222"})

    response = await client.get("/api/traites")
    ids_in_order = [item["id"] for item in response.json()["items"]]
    assert ids_in_order == [first.json()["id"], second.json()["id"]]


async def test_traite_read_exposes_null_tireur_and_tire_names_before_analysis(client):
    created = await client.post("/api/traites", json=VALID_PAYLOAD)
    body = created.json()
    assert body["code_adherent"] is None
    assert body["tireur_nom"] is None
    assert body["code_debiteur"] is None
    assert body["tire_nom"] is None

    listed = await client.get("/api/traites")
    assert listed.json()["items"][0]["tireur_nom"] is None


async def test_counts_endpoint_reports_every_statut_including_zero(client):
    response = await client.get("/api/traites/counts")
    assert response.status_code == 200
    body = response.json()
    assert set(body["par_statut"].keys()) == {
        "À traiter", "En cours OCR", "Écarts à traiter", "Contrôle manuel requis",
        "Renvoyée", "Fraude signalée", "Validée",
    }
    assert all(count == 0 for count in body["par_statut"].values())


async def test_counts_endpoint_reflects_created_traites(client):
    await client.post("/api/traites", json=VALID_PAYLOAD)
    await client.post("/api/traites", json={**VALID_PAYLOAD, "numero_lcn": "222222222222"})

    response = await client.get("/api/traites/counts")
    assert response.json()["par_statut"]["À traiter"] == 2
