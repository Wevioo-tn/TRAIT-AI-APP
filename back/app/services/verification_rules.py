"""Server-side port of the design mockup's `bloque` / `reco` computation.

This exact logic used to live only in the mockup's frontend JavaScript
(`renderVals()`). Porting it here — as a pure function taking plain data,
no DB/HTTP dependency — makes it the single source of truth: the API
enforces it when a decision is submitted, and the same function backs
whatever the frontend eventually renders, so the two can never drift apart
the way "duplicated business rules in two languages" usually do.
"""
from dataclasses import dataclass

from app.db.models.traite import StatutVerification, VerificationCode, VerificationManuelle


@dataclass(frozen=True)
class Recommendation:
    title: str
    detail: str


@dataclass(frozen=True)
class BlockingState:
    blocked: bool
    reason: str | None
    recommendation: Recommendation


def evaluate_verifications(verifications: list[VerificationManuelle]) -> BlockingState:
    total = len(VerificationCode)
    by_code = {v.code_verification: v for v in verifications}

    check_count = sum(1 for v in by_code.values() if v.statut is not None)
    ko_count = sum(1 for v in by_code.values() if v.statut == StatutVerification.ANOMALIE)
    drawer_signature = by_code.get(VerificationCode.SIG_TIREUR)
    drawer_signature_ok = drawer_signature is not None and drawer_signature.statut == StatutVerification.CONFORME

    blocked = check_count < total or ko_count > 0 or not drawer_signature_ok

    if ko_count > 0:
        reason = "Anomalie constatée sur une zone de contrôle humain"
        recommendation = Recommendation(
            "Signaler une fraude potentielle",
            "Une zone de signature ou de cachet est en anomalie. Geler la traite et "
            "transmettre à la conformité avant tout financement.",
        )
    elif check_count < total:
        reason = f"Vérifications manuelles incomplètes ({check_count} / {total})"
        recommendation = Recommendation(
            "Terminer les vérifications manuelles",
            f"Les {total - check_count} zone(s) restantes doivent être statuées avant toute décision.",
        )
    elif not drawer_signature_ok:
        # Unreachable with today's 2-value StatutVerification domain: if
        # check_count == total and ko_count == 0, every zone (drawer
        # signature included) must be CONFORME. It was equally unreachable
        # in the source mockup's 'ok'/'ko'/null domain, for the same
        # reason. Kept — not deleted — in case a third statut is ever
        # introduced, and because it documents the intent precisely (this
        # is the "signature not yet cleared" case, distinct from "anomaly
        # found").
        reason = "Signature du tireur non levée sur l'original"
        recommendation = Recommendation(
            "Renvoyer pour complément",
            "Signature du tireur absente : demander à l'adhérent une traite régularisée.",
        )
    else:
        reason = None
        recommendation = Recommendation(
            "Valider la traite",
            "Tous les contrôles automatiques et manuels sont levés. Écarts résiduels "
            "non bloquants documentés dans le dossier.",
        )

    return BlockingState(blocked=blocked, reason=reason, recommendation=recommendation)
