"""Sprint 4/11 — proves the background-task *wrapper* itself works: its own
engine creation, the SYNC_DATABASE_URL_OVERRIDE env var, and its commit —
not just execute_analysis in isolation (see test_traite_processing.py for
that).

Calls the function directly rather than via BackgroundTasks.add_task, so no
running FastAPI app is needed here — see the docstring in
app/tasks/traite_processing.py for why that's a legitimate way to test its
logic (it's a plain function, not a decorated task).
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.traite import Face, Traite, TraiteDocument, TraiteStatut, VerificationCode, VerificationManuelle
from app.tasks.traite_processing import run_traite_analysis


def test_task_processes_traite_end_to_end(sync_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNC_DATABASE_URL_OVERRIDE", get_settings().database_url_test)

    with Session(sync_engine) as session:
        traite = Traite(
            numero_lcn="777700001111",
            montant=Decimal("250.000"),
            date_echeance=date(2026, 10, 1),
            date_creation_traite=date(2026, 9, 1),
        )
        session.add(traite)
        session.flush()
        for code in VerificationCode:
            session.add(VerificationManuelle(traite_id=traite.id, code_verification=code))
        for face in (Face.RECTO, Face.VERSO):
            path = tmp_path / f"{face.value}.jpg"
            path.write_bytes(b"data")
            session.add(
                TraiteDocument(
                    traite_id=traite.id,
                    face=face,
                    fichier_nom=f"{face.value}.jpg",
                    fichier_chemin=str(path),
                    content_type="image/jpeg",
                    taille_octets=4,
                )
            )
        session.commit()
        traite_id = traite.id

    try:
        run_traite_analysis(str(traite_id))

        with Session(sync_engine) as session:
            traite = session.get(Traite, traite_id)
            # Default StubExtractor (no party text configured) -> no NLP
            # match -> écarts. The honest outcome given today's capability,
            # not a "clean" demo result.
            assert traite.statut == TraiteStatut.ECARTS_A_TRAITER
    finally:
        with sync_engine.begin() as connection:
            connection.execute(text("TRUNCATE traites CASCADE"))
