"""Orchestrates a traite's OCR/NLP analysis: extraction -> persistence ->
NLP matching -> statut transition.

Deliberately synchronous (plain SQLAlchemy ``Session``, not the async
engine) since this is designed to run inside a Celery worker, where
synchronous, straight-line code is simpler to reason about than mixing
event loops into a task queue.
"""
import logging
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.imx import Adherent, Debiteur
from app.db.models.traite import (
    AuditLogEntry,
    ChampExtrait,
    Face,
    RapprochementNlp,
    RoleNlp,
    SourceChamp,
    Traite,
    TraiteDocument,
    TraiteStatut,
)
from app.services.extraction import (
    CHAMP_DATE_CREATION,
    CHAMP_ECHEANCE,
    CHAMP_MONTANT_CHIFFRES,
    CHAMP_NUMERO_LCN,
    ROLE_ORDRE,
    ROLE_TIRE,
    ROLE_TIREUR,
    Extractor,
)
from app.services.nlp_matching import best_match

logger = logging.getLogger(__name__)

# Numeric(14, 3): 14 total digits, 3 after the decimal point -> at most 11
# integer digits. A montant read from a scan that doesn't fit is a garbled
# OCR read, not a real amount — skip promoting it rather than let it hit
# the DB constraint at commit time, far from where the real cause is.
_MAX_MONTANT = Decimal(10) ** 11


def _read_document(traite_id: uuid.UUID, documents: list[TraiteDocument], face: Face) -> bytes:
    document = next((d for d in documents if d.face == face), None)
    if document is None:
        raise ValueError(f"Document {face.value} manquant pour la traite {traite_id}.")
    return Path(document.fichier_chemin).read_bytes()


def _parse_montant(text: str) -> Decimal | None:
    """OCR'd amounts show up with whatever grouping/decimal convention the
    document itself uses (seen live: "2 520,000" — space-grouped, comma
    decimal). Strips everything but digits/separators/sign, then treats
    the right-most of ',' or '.' as the decimal separator; a lone comma is
    read as decimal (French/Tunisian convention), not thousands. Returns
    None rather than raising on anything that still doesn't parse — a
    malformed read must never crash the pipeline, only skip promotion."""
    cleaned = re.sub(r"[^\d,.\-]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".") if cleaned.rfind(",") > cleaned.rfind(".") else cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date(text: str) -> date | None:
    """The extraction prompt asks for AAAA-MM-JJ, but a real model doesn't
    always comply — fall back to the DD/MM/YYYY format the document itself
    prints before giving up (never raises)."""
    text = text.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _promote_canonical_identity(traite: Traite, by_field: dict[str, list[str | None]], session: Session) -> None:
    """Once extraction succeeds, its readings become the traite's own
    numero_lcn/montant/date_echeance/date_creation_traite — closing the
    loop left open since the queue screen stopped collecting a bordereau
    intake at creation time (those fields start out as server-generated
    placeholders, see create_traite). Promoted only when a field's two OCR
    occurrences agree: an incoherent field is already flagged as an écart
    for manual review, so picking one of two conflicting readings would be
    arbitrary, not authoritative. A parse failure or a numero_lcn collision
    with an existing traite is logged and skipped — never allowed to crash
    the pipeline, the same "honest fallback" discipline as an outright
    extraction failure."""

    def _coherent_value(nom_champ: str) -> str | None:
        values = by_field.get(nom_champ, [])
        if len(values) != 2 or values[0] != values[1] or values[0] is None:
            return None
        return values[0]

    numero_lcn = _coherent_value(CHAMP_NUMERO_LCN)
    if numero_lcn is not None:
        numero_lcn = numero_lcn.strip()
    if numero_lcn and len(numero_lcn) <= 20:
        collision = session.scalar(
            select(Traite.id).where(Traite.numero_lcn == numero_lcn, Traite.id != traite.id)
        )
        if collision is None:
            traite.numero_lcn = numero_lcn
        else:
            logger.warning(
                "Numéro L-CN extrait %r pour la traite %s entre en collision avec la traite %s — conservé tel quel.",
                numero_lcn,
                traite.id,
                collision,
            )

    montant_text = _coherent_value(CHAMP_MONTANT_CHIFFRES)
    montant = _parse_montant(montant_text) if montant_text is not None else None
    if montant is not None and 0 < montant < _MAX_MONTANT:
        traite.montant = montant

    echeance_text = _coherent_value(CHAMP_ECHEANCE)
    echeance = _parse_date(echeance_text) if echeance_text is not None else None
    if echeance is not None:
        traite.date_echeance = echeance

    date_creation_text = _coherent_value(CHAMP_DATE_CREATION)
    date_creation_traite = _parse_date(date_creation_text) if date_creation_text is not None else None
    if date_creation_traite is not None:
        traite.date_creation_traite = date_creation_traite


def execute_analysis(traite_id: uuid.UUID, session: Session, extractor: Extractor) -> Traite:
    """Runs one full analysis pass and leaves the traite in its resulting
    statut. Caller is responsible for the transaction (commit/rollback)."""
    traite = session.get(Traite, traite_id)
    if traite is None:
        raise ValueError(f"Traite {traite_id} introuvable.")

    recto = _read_document(traite_id, traite.documents, Face.RECTO)
    verso = _read_document(traite_id, traite.documents, Face.VERSO)

    # A real extraction backend (Sprint 8) is an external system that can
    # genuinely fail — a network error, a malformed/non-JSON model
    # response (real models don't always follow the "respond only with
    # JSON" instruction). Left uncaught, that would strand the traite in
    # EN_COURS_OCR forever with no signal for a human to act on — worse
    # than an honest "needs review" outcome.
    try:
        result = extractor.extract(traite, recto, verso)
    except Exception as exc:
        logger.warning("Échec d'extraction pour la traite %s : %s", traite_id, exc)
        traite.statut = TraiteStatut.ECARTS_A_TRAITER
        session.add(
            AuditLogEntry(
                traite_id=traite_id,
                utilisateur="system",
                action="analyse_echouee",
                details={"erreur": str(exc)},
            )
        )
        return traite

    for field in result.fields:
        session.add(
            ChampExtrait(
                traite_id=traite_id,
                nom_champ=field.field_name,
                occurrence=field.occurrence,
                valeur=field.value,
                source=SourceChamp.OCR,
            )
        )

    # Coherence of the duplicated fields: do the two occurrences agree?
    # Both-None counts as coherent — nothing to compare, not a contradiction
    # (see extraction.py for what's genuinely knowable without real OCR).
    by_field: dict[str, list[str | None]] = {}
    for field in result.fields:
        by_field.setdefault(field.field_name, []).append(field.value)
    inconsistencies = sorted(name for name, values in by_field.items() if len(set(values)) > 1)

    _promote_canonical_identity(traite, by_field, session)

    drawer_text = next((p.scanned_value for p in result.parties if p.role == ROLE_TIREUR), None)
    drawee_text = next((p.scanned_value for p in result.parties if p.role == ROLE_TIRE), None)
    payee_text = next((p.scanned_value for p in result.parties if p.role == ROLE_ORDRE), None)

    adherents = session.scalars(select(Adherent)).all()
    debiteurs = session.scalars(select(Debiteur)).all()

    drawer_match = best_match(drawer_text, [(a.code_adherent, a.raison_sociale) for a in adherents])
    drawee_match = best_match(drawee_text, [(d.code_debiteur, d.raison_sociale) for d in debiteurs])

    session.add(
        RapprochementNlp(
            traite_id=traite_id,
            role=RoleNlp.TIREUR,
            valeur_scan=drawer_text or "",
            valeur_referentiel=drawer_match.reference_value,
            score=drawer_match.score,
            code_adherent_matche=drawer_match.code,
        )
    )
    session.add(
        RapprochementNlp(
            traite_id=traite_id,
            role=RoleNlp.TIRE,
            valeur_scan=drawee_text or "",
            valeur_referentiel=drawee_match.reference_value,
            score=drawee_match.score,
            code_debiteur_matche=drawee_match.code,
        )
    )
    # "Ordre" (bénéficiaire déclaré) isn't matched against a referential —
    # validating it needs a contracts data model this project doesn't have.
    # Recorded as scanned text only, for now.
    session.add(
        RapprochementNlp(
            traite_id=traite_id,
            role=RoleNlp.ORDRE,
            valeur_scan=payee_text or "",
            valeur_referentiel=None,
            score=0,
        )
    )

    traite.code_adherent = drawer_match.code
    traite.code_debiteur = drawee_match.code

    threshold = get_settings().nlp_match_threshold
    clean = not inconsistencies and drawer_match.score >= threshold and drawee_match.score >= threshold
    traite.statut = TraiteStatut.CONTROLE_MANUEL_REQUIS if clean else TraiteStatut.ECARTS_A_TRAITER

    session.add(
        AuditLogEntry(
            traite_id=traite_id,
            utilisateur="system",
            action="analyse_terminee",
            details={
                "incoherences": inconsistencies,
                "score_tireur": drawer_match.score,
                "score_tire": drawee_match.score,
                "statut": traite.statut.value,
            },
        )
    )

    return traite
