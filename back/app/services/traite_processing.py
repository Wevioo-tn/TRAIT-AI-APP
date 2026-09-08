"""Orchestrates a traite's OCR/NLP analysis: extraction -> persistence ->
NLP matching -> statut transition.

Deliberately synchronous (plain SQLAlchemy ``Session``, not the async
engine) since this is designed to run inside a FastAPI background task
(see app/tasks/traite_processing.py), where synchronous, straight-line code
is simpler to reason about than mixing event loops into a background job.
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
    MethodeIdentification,
    RapprochementNlp,
    RoleNlp,
    SourceChamp,
    Traite,
    TraiteDocument,
    TraiteStatut,
)
from app.services.extraction import (
    CHAMP_CLE_RIB,
    CHAMP_CODE_AGENCE,
    CHAMP_CODE_ETABLISSEMENT,
    CHAMP_DATE_CREATION,
    CHAMP_ECHEANCE,
    CHAMP_MONTANT_CHIFFRES,
    CHAMP_NUMERO_COMPTE,
    CHAMP_NUMERO_LCN,
    CHAMP_RIB_TIRE,
    ROLE_ORDRE,
    ROLE_TIRE,
    ROLE_TIREUR,
    Extractor,
)
from app.services.nlp_matching import best_match, match_debiteur_by_rib

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


def _canonicalize_rib(text: str | None) -> str | None:
    """Keeps digits only — same defensive posture as _parse_montant/
    _parse_date: a RIB read off a scan carries whatever block-grouping the
    document itself prints (spaces or hyphens between the établissement/
    agence/compte/clé segments). Returns None for anything with no digits
    at all, never raises."""
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    return digits or None


def _coherent(values: list[str | None]) -> str | None:
    """Two OCR occurrences of the same field agree on a real value: exactly
    two readings, equal, and not None. Both-None or a single reading isn't
    "coherent" here, it's "nothing usable" — an incoherent/partial field is
    already flagged as an écart for manual review elsewhere; promoting or
    trusting one of two disagreeing (or absent) readings would be
    arbitrary, not authoritative."""
    if len(values) != 2 or values[0] != values[1] or values[0] is None:
        return None
    return values[0]


def _coherent_rib_part(by_field: dict[str, list[str | None]], field_name: str) -> str | None:
    """Same 'two OCR occurrences agree' gate as every other duplicated
    field (see _coherent), but canonicalized (digits only) first — a
    RIB-shaped field can carry the same block-grouping noise (spaces,
    hyphens) whether it's read from the single dedicated RIB box
    (rib_tire) or from one of its 4 printed sub-fields, and that noise
    shouldn't register as a false disagreement between two genuinely
    identical readings."""
    return _coherent([_canonicalize_rib(v) for v in by_field.get(field_name, [])])


_INCOHERENCE_RIB_RECONSTITUE = "rib_tire_vs_reconstitution_4_segments"


def reconstruct_rib(
    code_etablissement: str | None,
    code_agence: str | None,
    numero_compte: str | None,
    cle_rib: str | None,
) -> str | None:
    """Rebuilds a 20-digit RIB from its 4 separately printed sub-fields —
    Code étab. (2 digits) / Code Agence (3) / N° de Compte (13) / Clé (2),
    UC-01 étape 4 of the functional spec — the same way a human teller
    reads them off 4 distinct boxes. Concatenates only when every segment
    canonicalizes to exactly its expected length; any segment missing or
    the wrong length after canonicalization returns None. A RIB guessed
    from an incomplete or mis-lengthed segment would be exactly the kind
    of partial reconstruction this project avoids everywhere else (see
    _canonicalize_rib, _parse_montant)."""
    segments = [
        (code_etablissement, 2),
        (code_agence, 3),
        (numero_compte, 13),
        (cle_rib, 2),
    ]
    canonical = [_canonicalize_rib(value) for value, _ in segments]
    if any(value is None or len(value) != expected_len for value, (_, expected_len) in zip(canonical, segments)):
        return None
    return "".join(canonical)


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

    numero_lcn = _coherent(by_field.get(CHAMP_NUMERO_LCN, []))
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

    montant_text = _coherent(by_field.get(CHAMP_MONTANT_CHIFFRES, []))
    montant = _parse_montant(montant_text) if montant_text is not None else None
    if montant is not None and 0 < montant < _MAX_MONTANT:
        traite.montant = montant

    echeance_text = _coherent(by_field.get(CHAMP_ECHEANCE, []))
    echeance = _parse_date(echeance_text) if echeance_text is not None else None
    if echeance is not None:
        traite.date_echeance = echeance

    date_creation_text = _coherent(by_field.get(CHAMP_DATE_CREATION, []))
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
    adherents_by_code = {a.code_adherent: a for a in adherents}

    # RIB first (UC-01, étape 4 of the functional spec: "Vérifier RIB 20
    # chiffres = RIB IMX débiteur") — only when both OCR occurrences of the
    # RIB agree, same "coherent" gate _promote_canonical_identity already
    # applies to numero_lcn/montant/dates. A near-identical-but-not-exact
    # RIB is not a match (see match_debiteur_by_rib) — it falls through to
    # the name-only path below exactly like no RIB at all.
    #
    # Two independent readings of the same 20-digit RIB feed this: the
    # single dedicated "RIB ou RIP du Tiré" box (rib_tire), and the 4
    # separately printed sub-fields reconstructed below (also UC-01, étape
    # 4) — two different zones of the form, not the same box read twice.
    rib_direct = _coherent_rib_part(by_field, CHAMP_RIB_TIRE)
    rib_reconstitue = reconstruct_rib(
        _coherent_rib_part(by_field, CHAMP_CODE_ETABLISSEMENT),
        _coherent_rib_part(by_field, CHAMP_CODE_AGENCE),
        _coherent_rib_part(by_field, CHAMP_NUMERO_COMPTE),
        _coherent_rib_part(by_field, CHAMP_CLE_RIB),
    )

    if rib_direct is not None and rib_reconstitue is not None and rib_direct != rib_reconstitue:
        # The two readings disagree — exactly as serious as any other
        # duplicated-field écart (numero_lcn, montant, ...), so it joins
        # the same inconsistencies list rather than a second, parallel
        # blocking mechanism. Neither reading is trusted enough on its own
        # to identify a débiteur here: picking one over the other would be
        # exactly the kind of guess RIB-first matching exists to avoid.
        inconsistencies.append(_INCOHERENCE_RIB_RECONSTITUE)
        inconsistencies.sort()
        rib = None
    else:
        # Either they agree (reconstructed from 2 independently-read
        # zones — more reliable than a single box) or only one of the two
        # is exploitable, which is still acceptable on its own.
        rib = rib_reconstitue or rib_direct

    rib_match = match_debiteur_by_rib(rib, session) if rib else None

    homonym_threshold = get_settings().rib_corroboration_min_score

    if rib_match is not None and rib_match.code_debiteur is not None:
        # The débiteur is certain — the RIB is a hard key, unique in
        # imx.debiteurs. From here, comparing names is corroboration, not
        # identification: it can flag a mismatch worth a human's attention,
        # but it never decides who the débiteur is (that already happened),
        # and it's a single comparison against *this* débiteur, never a
        # search across the whole table.
        code_debiteur = rib_match.code_debiteur
        drawee_corrob = best_match(drawee_text, [(code_debiteur, rib_match.reference_value)])
        drawee_score, drawee_reference, drawee_method = (
            drawee_corrob.score,
            drawee_corrob.reference_value,
            MethodeIdentification.RIB,
        )
        drawee_alert = drawee_score < homonym_threshold

        # code_adherent comes only from the débiteur's own FK — deliberately
        # not independently fuzzy-searched. Doing that here would reimport
        # exactly the "guess by name similarity" risk the RIB path exists to
        # remove; if IMX itself doesn't link this débiteur to an adhérent,
        # the adhérent is honestly unresolved, not guessed.
        code_adherent = rib_match.code_adherent
        adherent = adherents_by_code.get(code_adherent) if code_adherent else None
        if adherent is not None:
            drawer_corrob = best_match(drawer_text, [(code_adherent, adherent.raison_sociale)])
            drawer_score, drawer_reference = drawer_corrob.score, drawer_corrob.reference_value
        else:
            drawer_score, drawer_reference = 0.0, None
        drawer_method = MethodeIdentification.RIB
        drawer_alert = False
    else:
        # No exploitable RIB (illisible, occurrences en désaccord, ou
        # aucun débiteur ne le porte) — today's full-table fuzzy fallback.
        # Per design: a name-only match, however high its score, can never
        # by itself put a traite in CONTROLE_MANUEL_REQUIS (see below) —
        # it's a lead for a human to confirm, never an identification.
        drawer_match = best_match(drawer_text, [(a.code_adherent, a.raison_sociale) for a in adherents])
        drawee_match = best_match(drawee_text, [(d.code_debiteur, d.raison_sociale) for d in debiteurs])
        code_debiteur, code_adherent = drawee_match.code, drawer_match.code
        drawee_score, drawee_reference = drawee_match.score, drawee_match.reference_value
        drawer_score, drawer_reference = drawer_match.score, drawer_match.reference_value
        drawee_method = drawer_method = MethodeIdentification.NOM_SEUL
        drawee_alert = drawer_alert = False

    session.add(
        RapprochementNlp(
            traite_id=traite_id,
            role=RoleNlp.TIREUR,
            valeur_scan=drawer_text or "",
            valeur_referentiel=drawer_reference,
            score=drawer_score,
            code_adherent_matche=code_adherent,
            methode_identification=drawer_method,
            alerte_ecart_nom=drawer_alert,
        )
    )
    session.add(
        RapprochementNlp(
            traite_id=traite_id,
            role=RoleNlp.TIRE,
            valeur_scan=drawee_text or "",
            valeur_referentiel=drawee_reference,
            score=drawee_score,
            code_debiteur_matche=code_debiteur,
            methode_identification=drawee_method,
            alerte_ecart_nom=drawee_alert,
        )
    )
    # "Ordre" (bénéficiaire déclaré) isn't matched against a referential —
    # validating it needs a contracts data model this project doesn't have.
    # Recorded as scanned text only, for now (methode_identification stays
    # its NOM_SEUL default — never resolved by any hard key).
    session.add(
        RapprochementNlp(
            traite_id=traite_id,
            role=RoleNlp.ORDRE,
            valeur_scan=payee_text or "",
            valeur_referentiel=None,
            score=0,
        )
    )

    traite.code_adherent = code_adherent
    traite.code_debiteur = code_debiteur

    # Auto-confirm requires a débiteur identified by RIB (a hard key), a
    # corroborating name that isn't a homonym alert, an adhérent actually
    # resolved (via the FK above), and no duplicated-field inconsistency.
    # A name-only identification, at any score, never qualifies — see
    # "Repli nom-seul" in this story's own task description.
    clean = (
        not inconsistencies
        and drawee_method == MethodeIdentification.RIB
        and not drawee_alert
        and code_adherent is not None
    )
    traite.statut = TraiteStatut.CONTROLE_MANUEL_REQUIS if clean else TraiteStatut.ECARTS_A_TRAITER

    if drawee_alert:
        # Surfaced explicitly, not just via the boolean flag on the row
        # above — a reviewer scanning the audit log for this traite must
        # see the RIB/nom incohérence too, not just the two panels.
        session.add(
            AuditLogEntry(
                traite_id=traite_id,
                utilisateur="system",
                action="ecart_rib_nom",
                details={
                    "code_debiteur": code_debiteur,
                    "nom_referentiel": drawee_reference,
                    "nom_scanne": drawee_text,
                    "score_corroboration": drawee_score,
                },
            )
        )

    session.add(
        AuditLogEntry(
            traite_id=traite_id,
            utilisateur="system",
            action="analyse_terminee",
            details={
                "incoherences": inconsistencies,
                "score_tireur": drawer_score,
                "score_tire": drawee_score,
                "methode_identification_tire": drawee_method.value,
                "statut": traite.statut.value,
            },
        )
    )

    return traite
