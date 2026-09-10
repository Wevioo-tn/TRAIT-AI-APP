"""Server-side port of the design mockup's `bloque` / `reco` computation.

This exact logic used to live only in the mockup's frontend JavaScript
(`renderVals()`). Porting it here — as a pure function taking plain data,
no DB/HTTP dependency — makes it the single source of truth: the API
enforces it when a decision is submitted, and the same function backs
whatever the frontend eventually renders, so the two can never drift apart
the way "duplicated business rules in two languages" usually do.

Extended (not just the manual checks any more) after a real bug found
live: POST .../decisions (type=validee) only ever called this with the 4
manual checkboxes — a traite with a real, unresolved automatic écart
(RIB-confirmed débiteur but an incoherent scanned name, a montant
chiffres/lettres mismatch, ...) could be genuinely validated through the
API the moment those 4 boxes were ticked, while the UI's own "Valider la
traite" banner falsely claimed "tous les contrôles automatiques... sont
levés". ``traite_statut`` closes that gap: ``ECARTS_A_TRAITER`` already
means, precisely, "execute_analysis found at least one unresolved
automatic écart" (see traite_processing.py's ``clean`` computation) — no
new computation needed, just actually checking it here. Deliberately
narrow: this blocks on THIS traite's own écarts, never on
``debtor_coverage``/``control_rollup`` (débiteur-wide, explicitly
informational per the coverage story — not revisited here)."""
from dataclasses import dataclass

from app.db.models.traite import StatutVerification, TraiteStatut, VerificationCode, VerificationManuelle


@dataclass(frozen=True)
class Recommendation:
    title: str
    detail: str


@dataclass(frozen=True)
class BlockingState:
    blocked: bool
    reason: str | None
    recommendation: Recommendation


def evaluate_verifications(verifications: list[VerificationManuelle], traite_statut: TraiteStatut) -> BlockingState:
    total = len(VerificationCode)
    by_code = {v.code_verification: v for v in verifications}

    check_count = sum(1 for v in by_code.values() if v.statut is not None)
    ko_count = sum(1 for v in by_code.values() if v.statut == StatutVerification.ANOMALIE)
    drawer_signature = by_code.get(VerificationCode.SIG_TIREUR)
    drawer_signature_ok = drawer_signature is not None and drawer_signature.statut == StatutVerification.CONFORME
    automatic_ecarts = traite_statut == TraiteStatut.ECARTS_A_TRAITER

    blocked = check_count < total or ko_count > 0 or not drawer_signature_ok or automatic_ecarts

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
    elif automatic_ecarts:
        # Manual checks are all clean, but execute_analysis's own
        # automatic reconciliation (RIB/nom, champs dupliqués, montant,
        # code-barres) hasn't cleared this traite — see this module's
        # docstring for the live bug this branch closes.
        reason = "Écarts automatiques non résolus (OCR/NLP)"
        recommendation = Recommendation(
            "Résoudre les écarts avant validation",
            "Le contrôle automatique (OCR/NLP) a détecté des écarts non résolus sur "
            "cette traite — consulter le tableau de cohérence des champs dupliqués et "
            "le rapprochement NLP avant de valider.",
        )
    else:
        reason = None
        recommendation = Recommendation(
            "Valider la traite",
            "Tous les contrôles automatiques et manuels sont levés.",
        )

    return BlockingState(blocked=blocked, reason=reason, recommendation=recommendation)
