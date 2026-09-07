"""Fuzzy matching of a scanned party name against an IMX referential table.

This part is fully real regardless of what feeds it text: given any scanned
string and any list of (code, raison_sociale) candidates, this returns a
genuine best-match score via rapidfuzz — independent of the OCR/extraction
question tracked separately in extraction.py.
"""
from dataclasses import dataclass

from rapidfuzz import fuzz


@dataclass(frozen=True)
class MatchResult:
    code: str | None
    reference_value: str | None
    score: float


def best_match(scanned_value: str | None, candidates: list[tuple[str, str]]) -> MatchResult:
    """Best fuzzy match of ``scanned_value`` against ``candidates`` (code,
    raison_sociale) pairs. Returns a null match (score 0) if there is
    nothing to compare — no scanned text, or no candidates."""
    if not scanned_value or not candidates:
        return MatchResult(code=None, reference_value=None, score=0.0)

    best_code: str | None = None
    best_ref: str | None = None
    best_score = 0.0
    for code, raison_sociale in candidates:
        score = fuzz.WRatio(scanned_value, raison_sociale)
        if score > best_score:
            best_code, best_ref, best_score = code, raison_sociale, score

    return MatchResult(code=best_code, reference_value=best_ref, score=round(best_score, 2))
