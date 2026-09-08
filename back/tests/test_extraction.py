"""Pure unit tests for StubExtractor — no DB, no HTTP.

Confirms exactly what the stub does and doesn't fabricate: known traite
fields come back consistent across both occurrences; genuinely unknown
fields (RIB, lieu, parties) come back empty unless explicitly configured.
"""
from datetime import date
from decimal import Decimal

from app.db.models.traite import Traite
from app.services.extraction import (
    CHAMP_CLE_RIB,
    CHAMP_CODE_AGENCE,
    CHAMP_CODE_ETABLISSEMENT,
    CHAMP_DATE_CREATION,
    CHAMP_ECHEANCE,
    CHAMP_LIEU_CREATION,
    CHAMP_MONTANT_CHIFFRES,
    CHAMP_MONTANT_LETTRES,
    CHAMP_NUMERO_COMPTE,
    CHAMP_NUMERO_LCN,
    CHAMP_RIB_TIRE,
    ROLE_DOMICILIATION,
    ROLE_ORDRE,
    ROLE_TIRE,
    ROLE_TIREUR,
    StubExtractor,
)


def _traite() -> Traite:
    return Traite(
        numero_lcn="011570763437",
        montant=Decimal("8117.504"),
        date_echeance=date(2026, 8, 28),
        date_creation_traite=date(2026, 8, 5),
    )


def _values(fields, field_name):
    return [f.value for f in fields if f.field_name == field_name]


def test_known_fields_are_consistent_across_both_occurrences():
    result = StubExtractor().extract(_traite(), b"recto", b"verso")

    assert _values(result.fields, CHAMP_NUMERO_LCN) == ["011570763437", "011570763437"]
    assert _values(result.fields, CHAMP_MONTANT_CHIFFRES) == ["8117.504", "8117.504"]
    assert _values(result.fields, CHAMP_ECHEANCE) == ["2026-08-28", "2026-08-28"]
    assert _values(result.fields, CHAMP_DATE_CREATION) == ["2026-08-05", "2026-08-05"]


def test_montant_en_lettres_is_really_computed_not_placeholder():
    result = StubExtractor().extract(_traite(), b"recto", b"verso")
    values = _values(result.fields, CHAMP_MONTANT_LETTRES)
    assert values == ["Huit mille cent dix-sept dinars, 504 millimes"] * 2


def test_genuinely_unknown_fields_are_reported_as_absent():
    result = StubExtractor().extract(_traite(), b"recto", b"verso")
    assert _values(result.fields, CHAMP_RIB_TIRE) == [None, None]
    assert _values(result.fields, CHAMP_LIEU_CREATION) == [None, None]


def test_rib_subfields_are_reported_as_absent():
    """Same honest-fallback treatment as rib_tire itself — the 4 RIB
    sub-fields (UC-01, étape 4) aren't knowable without real OCR either."""
    result = StubExtractor().extract(_traite(), b"recto", b"verso")
    assert _values(result.fields, CHAMP_CODE_ETABLISSEMENT) == [None, None]
    assert _values(result.fields, CHAMP_CODE_AGENCE) == [None, None]
    assert _values(result.fields, CHAMP_NUMERO_COMPTE) == [None, None]
    assert _values(result.fields, CHAMP_CLE_RIB) == [None, None]


def test_party_text_defaults_to_none_without_explicit_configuration():
    result = StubExtractor().extract(_traite(), b"recto", b"verso")
    by_role = {p.role: p.scanned_value for p in result.parties}
    assert by_role == {ROLE_TIREUR: None, ROLE_TIRE: None, ROLE_ORDRE: None, ROLE_DOMICILIATION: None}


def test_party_text_can_be_configured_for_testing_realistic_scenarios():
    extractor = StubExtractor(
        tireur_texte="ADACTIM",
        tire_texte="LA MEDITERRANEENNE",
        ordre_texte="SPG",
        domiciliation_texte="Agence Centrale, 2036 Ariana",
    )
    result = extractor.extract(_traite(), b"recto", b"verso")
    by_role = {p.role: p.scanned_value for p in result.parties}
    assert by_role == {
        ROLE_TIREUR: "ADACTIM",
        ROLE_TIRE: "LA MEDITERRANEENNE",
        ROLE_ORDRE: "SPG",
        ROLE_DOMICILIATION: "Agence Centrale, 2036 Ariana",
    }
