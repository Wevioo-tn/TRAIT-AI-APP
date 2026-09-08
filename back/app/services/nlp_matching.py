"""Fuzzy matching of a scanned party name against an IMX referential table,
plus the RIB-exact lookup that identifies a débiteur with certainty.

Per UC-01, étape 4 of the functional spec ("Vérifier RIB 20 chiffres = RIB
IMX débiteur"), the RIB — not the name — is this project's real
identification key for a débiteur; see app/services/traite_processing.py
for how the two are combined (RIB first, name as corroboration only).

``best_match`` stays fully pure — no DB, no HTTP, exactly as before.
``match_debiteur_by_rib`` is the one deliberate exception: an exact lookup
against a column already unique in the database (imx.debiteurs.rib) is a
single indexed query, not something that benefits from pre-fetching every
débiteur just to filter it in Python.
"""
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.imx import Debiteur


@dataclass(frozen=True)
class MatchResult:
    code: str | None
    reference_value: str | None
    score: float


def best_match(scanned_value: str | None, candidates: list[tuple[str, str]]) -> MatchResult:
    """Best fuzzy match of ``scanned_value`` against ``candidates`` (code,
    raison_sociale) pairs. Returns a null match (score 0) if there is
    nothing to compare — no scanned text, or no candidates.

    Both sides are casefolded before scoring — WRatio is case-sensitive on
    its own (a real bug, not a hypothetical: "LA MEDITERRANEENNE" against
    its own string in lowercase scored 5.6, not ~100, before this fix), and
    case is exactly the kind of noise a real scan/OCR pass can introduce
    that has nothing to do with whether the name is actually the right one.
    """
    if not scanned_value or not candidates:
        return MatchResult(code=None, reference_value=None, score=0.0)

    best_code: str | None = None
    best_ref: str | None = None
    best_score = 0.0
    for code, raison_sociale in candidates:
        score = fuzz.WRatio(scanned_value.casefold(), raison_sociale.casefold())
        if score > best_score:
            best_code, best_ref, best_score = code, raison_sociale, score

    return MatchResult(code=best_code, reference_value=best_ref, score=round(best_score, 2))


@dataclass(frozen=True)
class RibMatchResult:
    code_debiteur: str | None
    code_adherent: str | None
    reference_value: str | None


def match_debiteur_by_rib(rib: str, session: Session) -> RibMatchResult:
    """Exact match only against imx.debiteurs.rib — a near-identical RIB is
    not a match, ever. Guessing the wrong débiteur off a single mistyped
    digit is exactly the risk this identification path exists to remove: a
    RIB that's merely *similar* to a real one gets an honest null result,
    the same as no RIB at all, never a best-effort guess."""
    debiteur = session.scalar(select(Debiteur).where(Debiteur.rib == rib))
    if debiteur is None:
        return RibMatchResult(code_debiteur=None, code_adherent=None, reference_value=None)
    return RibMatchResult(
        code_debiteur=debiteur.code_debiteur,
        code_adherent=debiteur.code_adherent,
        reference_value=debiteur.raison_sociale,
    )
