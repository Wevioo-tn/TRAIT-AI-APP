"""OCR/extraction accuracy pilot — runs one or more real bilingual FR/AR
traite scans through the actual running pipeline (real backend API,
whichever OCR_PROVIDER the backend is currently configured for) and
reports field-by-field accuracy against manually-supplied ground truth.

This is deliberately NOT a unit test: it hits the real, running `backend`
container over HTTP, exactly the path a real user's browser takes, per
this project's own validation discipline (BACKLOG.md — a clean run
against a synthetic/mocked path proves the plumbing, never accuracy).

Usage (from the host):
    docker compose exec backend python scripts/accuracy_pilot.py pilot_samples/manifest.json

Manifest format (JSON, list of samples):
[
  {
    "nom": "traite_001",
    "recto": "pilot_samples/traite_001_recto.jpg",
    "verso": "pilot_samples/traite_001_verso.jpg",
    "intake": {
      "numero_lcn": "011570763437",
      "montant": "8117.504",
      "date_echeance": "2026-08-28",
      "date_creation_traite": "2026-08-05"
    },
    "verite_terrain": {
      "rib_tire": "11003000291700178836",
      "lieu_creation": "TUNIS",
      "tireur_texte": "ADACTIM",
      "tire_texte": "LA MEDITERRANEENNE",
      "ordre_texte": "..."
    }
  }
]

`intake` fields are the ones this app declares at creation (never OCR'd —
see README's "Two databases" section); only `verite_terrain` fields are
genuinely being tested here (RIB, lieu, and the free-text party names),
since numero_lcn/montant/dates get echoed back for the duplicate-field
cross-check regardless of extraction quality. Add ground truth for the
duplicated fields too if you want to test OCR's reading of them, not just
their presence.
"""

import json
import sys
import time
from pathlib import Path

import httpx
import psycopg

API_BASE = "http://localhost:8000/api"
DATABASE_URL = "postgresql://trait:trait@postgres:5432/trait_ai"
LOGIN = {"username": "h.mansouri", "password": "secret123"}

CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf"}


def _content_type(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _login(client: httpx.Client) -> str:
    resp = client.post(f"{API_BASE}/auth/login", json=LOGIN)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _raw_extractions(traite_id: str) -> list[dict]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT fournisseur, modele, succes, reponse_brute, erreur, duree_ms, cree_le "
            "FROM extractions_ia WHERE traite_id = %s ORDER BY cree_le",
            (traite_id,),
        ).fetchall()
        cols = ["fournisseur", "modele", "succes", "reponse_brute", "erreur", "duree_ms", "cree_le"]
        return [dict(zip(cols, row)) for row in rows]


def _run_sample(client: httpx.Client, token: str, sample: dict, base_dir: Path) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    intake = sample["intake"]
    numero_lcn = f"{intake['numero_lcn']}-PILOT-{int(time.time())}"

    create_resp = client.post(
        f"{API_BASE}/traites",
        headers=headers,
        json={**intake, "numero_lcn": numero_lcn},
    )
    create_resp.raise_for_status()
    traite_id = create_resp.json()["id"]

    for face, key in (("recto", "recto"), ("verso", "verso")):
        file_path = base_dir / sample[key]
        content = file_path.read_bytes()
        upload_resp = client.post(
            f"{API_BASE}/traites/{traite_id}/documents",
            headers=headers,
            params={"face": face},
            files={"file": (file_path.name, content, _content_type(file_path))},
        )
        upload_resp.raise_for_status()

    analyse_resp = client.post(f"{API_BASE}/traites/{traite_id}/analyse", headers=headers)
    analyse_resp.raise_for_status()

    for _ in range(60):
        status_resp = client.get(f"{API_BASE}/traites/{traite_id}/status", headers=headers)
        status_resp.raise_for_status()
        if not status_resp.json()["en_cours"]:
            break
        time.sleep(2)
    else:
        raise TimeoutError(f"Traite {traite_id} still EN_COURS_OCR after 120s")

    detail_resp = client.get(f"{API_BASE}/traites/{traite_id}", headers=headers)
    detail_resp.raise_for_status()
    detail = detail_resp.json()

    return {
        "nom": sample["nom"],
        "traite_id": traite_id,
        "statut": detail["statut"],
        "champs_extraits": detail["champs_extraits"],
        "rapprochements_nlp": detail["rapprochements_nlp"],
        "verite_terrain": sample.get("verite_terrain", {}),
        "extractions_ia": _raw_extractions(traite_id),
    }


def _print_report(result: dict) -> None:
    print(f"\n=== {result['nom']} (traite {result['traite_id']}) — statut final : {result['statut']} ===")

    for log in result["extractions_ia"]:
        print(
            f"  [extractions_ia] {log['fournisseur']}/{log['modele']} succes={log['succes']} "
            f"duree={log['duree_ms']}ms erreur={log['erreur']!r}"
        )
        if not log["succes"]:
            print(f"    reponse_brute: {log['reponse_brute']!r}"[:500])

    print("  Champs extraits (occurrence_1 / occurrence_2) vs vérité terrain :")
    verite = result["verite_terrain"]
    by_champ: dict[str, dict[int, str | None]] = {}
    for c in result["champs_extraits"]:
        by_champ.setdefault(c["nom_champ"], {})[c["occurrence"]] = c["valeur"]
    for champ, occs in by_champ.items():
        attendu = verite.get(champ, "(non fourni)")
        print(f"    {champ:20s} occ1={occs.get(1)!r:30s} occ2={occs.get(2)!r:30s}  attendu={attendu!r}")

    print("  Rapprochement NLP :")
    for r in result["rapprochements_nlp"]:
        print(f"    role={r['role']:8s} valeur_scan={r['valeur_scan']!r} score={r.get('score_similarite')}")


def main() -> None:
    manifest_path = Path(sys.argv[1])
    base_dir = manifest_path.parent
    samples = json.loads(manifest_path.read_text(encoding="utf-8"))

    with httpx.Client(timeout=30) as client:
        token = _login(client)
        results = [_run_sample(client, token, sample, base_dir) for sample in samples]

    for result in results:
        _print_report(result)


if __name__ == "__main__":
    main()
