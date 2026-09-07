"""Field/party extraction from a traite's uploaded scans.

``Extractor`` is the seam between "the async pipeline, state machine, and
NLP matching are real and fully tested" and "what actually reads the image
is a separate, not-yet-built concern." Real zone-aware OCR needs its own
evaluated effort (accuracy pilot, possibly a cloud provider with a
data-residency decision — tracked in BACKLOG.md); nothing here should
pretend otherwise.

``StubExtractor`` is today's implementation. Where a value is genuinely
known without reading the image at all — the traite's own numero_lcn,
montant, dates — it reports that value for both OCR "occurrences",
honestly simulating the case where the scan agrees with what was declared
at intake. Where nothing is knowable without real OCR (RIB, lieu de
création, and the tireur/tiré/ordre free text used for NLP matching), it
reports nothing (``None``) by default rather than inventing plausible-
looking fake text. Callers that need to exercise the matching logic against
realistic input (tests, smoke tests) construct a ``StubExtractor`` with
explicit values — that's a deliberate test seam, not a hidden default.
"""
from dataclasses import dataclass, field
from typing import Protocol

from app.db.models.traite import Traite
from app.services.nombres import amount_to_words

# Field-name values — the "Contrôle de cohérence des champs dupliqués"
# table's nom_champ column. The constant names below are English; the
# string values are the actual DB business keys and stay unchanged.
CHAMP_NUMERO_LCN = "numero_lcn"
CHAMP_MONTANT_CHIFFRES = "montant_chiffres"
CHAMP_MONTANT_LETTRES = "montant_lettres"
CHAMP_ECHEANCE = "echeance"
CHAMP_RIB_TIRE = "rib_tire"
CHAMP_LIEU_CREATION = "lieu_creation"
CHAMP_DATE_CREATION = "date_creation"

ROLE_TIREUR = "tireur"
ROLE_TIRE = "tire"
ROLE_ORDRE = "ordre"


@dataclass(frozen=True)
class FieldCandidate:
    field_name: str
    occurrence: int
    value: str | None


@dataclass(frozen=True)
class PartyCandidate:
    role: str
    scanned_value: str | None


@dataclass(frozen=True)
class ExtractionResult:
    fields: list[FieldCandidate] = field(default_factory=list)
    parties: list[PartyCandidate] = field(default_factory=list)


class Extractor(Protocol):
    def extract(self, traite: Traite, recto: bytes, verso: bytes) -> ExtractionResult: ...


class StubExtractor:
    """Deterministic placeholder — see module docstring for what is and
    isn't honestly simulated.

    Takes the same ``(traite, recto, verso)`` signature a real implementation
    would need — it just doesn't look at ``recto``/``verso`` at all, since it
    does no actual image processing. That's the point: the interface shape
    is right for a real OCR engine to drop in later without every caller
    changing.
    """

    def __init__(
        self,
        tireur_texte: str | None = None,
        tire_texte: str | None = None,
        ordre_texte: str | None = None,
    ) -> None:
        self._tireur_texte = tireur_texte
        self._tire_texte = tire_texte
        self._ordre_texte = ordre_texte

    def extract(self, traite: Traite, recto: bytes, verso: bytes) -> ExtractionResult:
        amount_str = f"{traite.montant:.3f}"
        amount_words = amount_to_words(traite.montant)
        due_date_str = traite.date_echeance.isoformat()
        creation_date_str = traite.date_creation_traite.isoformat()

        def _pair(field_name: str, value: str | None) -> list[FieldCandidate]:
            return [
                FieldCandidate(field_name, 1, value),
                FieldCandidate(field_name, 2, value),
            ]

        fields = [
            *_pair(CHAMP_NUMERO_LCN, traite.numero_lcn),
            *_pair(CHAMP_MONTANT_CHIFFRES, amount_str),
            *_pair(CHAMP_MONTANT_LETTRES, amount_words),
            *_pair(CHAMP_ECHEANCE, due_date_str),
            *_pair(CHAMP_DATE_CREATION, creation_date_str),
            # Genuinely unknown without real OCR — reported as absent
            # rather than guessed.
            *_pair(CHAMP_RIB_TIRE, None),
            *_pair(CHAMP_LIEU_CREATION, None),
        ]

        parties = [
            PartyCandidate(ROLE_TIREUR, self._tireur_texte),
            PartyCandidate(ROLE_TIRE, self._tire_texte),
            PartyCandidate(ROLE_ORDRE, self._ordre_texte),
        ]

        return ExtractionResult(fields=fields, parties=parties)
