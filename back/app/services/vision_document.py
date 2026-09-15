"""Strict vision output using the existing backend field contract."""

from pydantic import BaseModel, ConfigDict


def _rib_digits(value: str | None) -> str | None:
    """Accept exactly twenty ASCII digits, ignoring whitespace only."""
    compact = "".join(value.split()) if value else ""
    return compact if len(compact) == 20 and compact.isascii() and compact.isdigit() else None


def _format_rib(value: str | None) -> str | None:
    digits = _rib_digits(value)
    return f"{digits[:2]} {digits[2:5]} {digits[5:18]} {digits[18:]}" if digits else value


class Occurrences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    occurrence_1: str | None
    occurrence_2: str | None


class VisionDocument(BaseModel):
    """All keys are required; unreadable source values must be explicit nulls."""

    model_config = ConfigDict(extra="forbid", strict=True)

    numero_lcn: Occurrences
    montant_chiffres: Occurrences
    montant_lettres: Occurrences
    echeance: Occurrences
    date_creation: Occurrences
    rib_tire: Occurrences
    lieu_creation: Occurrences
    code_etablissement: Occurrences
    code_agence: Occurrences
    numero_compte: Occurrences
    cle_rib: Occurrences
    tireur_texte: str | None
    tire_texte: str | None
    ordre_texte: str | None
    domiciliation_texte: str | None

    has_signature_tire: bool
    has_cachet_tire: bool
    has_signature_tireur: bool
    has_cachet_tireur: bool
    has_acceptation_signature: bool
    has_acceptation_cachet: bool

    def with_reconstructed_rib(self) -> "VisionDocument":
        """Assemble the first structured source zone, never infer missing digits.

        Match the reference extractor's whitespace/ASCII checks. Component
        length and bank validation remain the responsibility of business rules.
        Missing second components are derived from a complete second RIB.
        They are not independent OCR evidence. Existing readings are preserved.
        """
        parts = (
            self.code_etablissement.occurrence_1,
            self.code_agence.occurrence_1,
            self.numero_compte.occurrence_1,
            self.cle_rib.occurrence_1,
        )
        digits = []
        for part in parts:
            if part is None:
                break
            value = "".join(part.split())
            if not value.isascii() or not value.isdigit():
                break
            digits.append(value)
        rib = Occurrences(
            occurrence_1=_format_rib(self.rib_tire.occurrence_1),
            occurrence_2=_format_rib("".join(digits) if len(digits) == 4 else None),
        )
        updates = {"rib_tire": rib}
        second = _rib_digits(rib.occurrence_2)
        for name, start, end in (
            ("code_etablissement", 0, 2), ("code_agence", 2, 5),
            ("numero_compte", 5, 18), ("cle_rib", 18, 20),
        ):
            original = getattr(self, name)
            values = original.model_dump()
            for key, value in values.items():
                compact = "".join(value.split()) if value else ""
                if len(compact) == end - start and compact.isascii() and compact.isdigit():
                    values[key] = compact
            if second and not values["occurrence_2"]:
                values["occurrence_2"] = second[start:end]
            updates[name] = Occurrences(**values)
        return self.model_copy(update=updates)
