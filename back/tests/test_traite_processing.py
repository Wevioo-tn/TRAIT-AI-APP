"""Sprint 4 — execute_analysis: the real orchestration logic, exercised
directly against the test DB. No Celery, no HTTP — see test_analyse_endpoint.py
for the API layer and test_extraction.py / test_nlp_matching.py for the pure
building blocks this composes.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models.imx import Adherent, Debiteur, StatutContrat
from app.db.models.traite import (
    AuditLogEntry,
    ChampExtrait,
    Face,
    RapprochementNlp,
    RoleNlp,
    Traite,
    TraiteDocument,
    TraiteStatut,
    VerificationCode,
    VerificationManuelle,
)
from app.services.extraction import (
    CHAMP_DATE_CREATION,
    CHAMP_ECHEANCE,
    CHAMP_MONTANT_CHIFFRES,
    CHAMP_NUMERO_LCN,
    ExtractionResult,
    FieldCandidate,
    StubExtractor,
)
from app.services.traite_processing import _parse_date, _parse_montant, execute_analysis


class _BrokenExtractor:
    """Simulates a real extraction-backend failure (Sprint 8) — unreadable
    model response, network error, etc. — rather than guessing how such a
    failure behaves."""

    def extract(self, traite, recto, verso) -> ExtractionResult:
        raise ValueError("réponse du modèle illisible")


class _FakeExtractor:
    """Returns exactly the field candidates given to it — used to exercise
    canonical-identity promotion with values deliberately different from
    what's already on the traite (StubExtractor always echoes those back,
    which can't prove a real promotion happened)."""

    def __init__(self, fields: list[FieldCandidate]) -> None:
        self._fields = fields

    def extract(self, traite, recto, verso) -> ExtractionResult:
        return ExtractionResult(fields=self._fields, parties=[])


def _make_traite_with_documents(session, tmp_path, *, numero_lcn="011570763437") -> Traite:
    traite = Traite(
        numero_lcn=numero_lcn,
        montant=Decimal("8117.504"),
        date_echeance=date(2026, 8, 28),
        date_creation_traite=date(2026, 8, 5),
    )
    session.add(traite)
    session.flush()

    for code in VerificationCode:
        session.add(VerificationManuelle(traite_id=traite.id, code_verification=code))

    for face in (Face.RECTO, Face.VERSO):
        content = f"fake-scan-bytes-{face.value}".encode()
        file_path = tmp_path / f"{face.value}.jpg"
        file_path.write_bytes(content)
        session.add(
            TraiteDocument(
                traite_id=traite.id,
                face=face,
                fichier_nom=f"{face.value}.jpg",
                fichier_chemin=str(file_path),
                content_type="image/jpeg",
                taille_octets=len(content),
            )
        )
    session.flush()
    return traite


def _seed_referential(session) -> None:
    session.add(Adherent(code_adherent="ADH-1001", raison_sociale="ADACTIM", statut_contrat=StatutContrat.ACTIF))
    session.add(Debiteur(code_debiteur="DEB-1001", raison_sociale="LA MÉDITERRANÉENNE", rib="11003000291700178836"))
    session.flush()


def test_missing_document_raises(db_session):
    traite = Traite(
        numero_lcn="000000000001",
        montant=Decimal("100.000"),
        date_echeance=date(2026, 9, 30),
        date_creation_traite=date(2026, 9, 1),
    )
    db_session.add(traite)
    db_session.flush()

    with pytest.raises(ValueError, match="recto"):
        execute_analysis(traite.id, db_session, StubExtractor())


def test_clean_analysis_with_matching_parties_yields_controle_manuel_requis(db_session, tmp_path):
    traite = _make_traite_with_documents(db_session, tmp_path)
    _seed_referential(db_session)

    extractor = StubExtractor(tireur_texte="ADACTIM", tire_texte="LA MÉDITERRANÉENNE")
    result = execute_analysis(traite.id, db_session, extractor)

    assert result.statut == TraiteStatut.CONTROLE_MANUEL_REQUIS
    assert result.code_adherent == "ADH-1001"
    assert result.code_debiteur == "DEB-1001"
    # The display-name properties the queue list depends on.
    assert result.tireur_nom == "ADACTIM"
    assert result.tire_nom == "LA MÉDITERRANÉENNE"

    fields = db_session.scalars(select(ChampExtrait).where(ChampExtrait.traite_id == traite.id)).all()
    assert len(fields) == 14  # 7 fields x 2 occurrences

    nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
    by_role = {n.role: n for n in nlp}
    assert by_role[RoleNlp.TIREUR].score == 100.0
    assert by_role[RoleNlp.TIRE].score >= 95.0
    assert RoleNlp.ORDRE in by_role


def test_known_fields_land_in_champs_extraits_correctly(db_session, tmp_path):
    traite = _make_traite_with_documents(db_session, tmp_path)
    _seed_referential(db_session)

    execute_analysis(traite.id, db_session, StubExtractor())

    montant_lettres = db_session.scalars(
        select(ChampExtrait).where(ChampExtrait.traite_id == traite.id, ChampExtrait.nom_champ == "montant_lettres")
    ).all()
    assert {c.valeur for c in montant_lettres} == {"Huit mille cent dix-sept dinars, 504 millimes"}


def test_missing_party_text_yields_ecarts_a_traiter(db_session, tmp_path):
    traite = _make_traite_with_documents(db_session, tmp_path)
    _seed_referential(db_session)

    result = execute_analysis(traite.id, db_session, StubExtractor())  # no party text configured

    assert result.statut == TraiteStatut.ECARTS_A_TRAITER
    assert result.code_adherent is None
    assert result.code_debiteur is None


def test_low_confidence_match_yields_ecarts_a_traiter_but_still_records_the_best_guess(db_session, tmp_path):
    """Below-threshold matches aren't discarded: they're recorded as a
    tentative best guess for a human to review, exactly like the design
    mockup shows a low-percentage match rather than hiding it."""
    traite = _make_traite_with_documents(db_session, tmp_path)
    _seed_referential(db_session)

    extractor = StubExtractor(
        tireur_texte="UNE SOCIETE COMPLETEMENT DIFFERENTE ET SANS RAPPORT",
        tire_texte="LA MÉDITERRANÉENNE",
    )
    result = execute_analysis(traite.id, db_session, extractor)

    assert result.statut == TraiteStatut.ECARTS_A_TRAITER
    assert result.code_debiteur == "DEB-1001"  # the good match

    nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
    tireur_match = next(n for n in nlp if n.role == RoleNlp.TIREUR)
    assert tireur_match.score < 95.0
    # There's only one adherent seeded, so it's still the "best" (only)
    # candidate — recorded, just not good enough to auto-confirm.
    assert result.code_adherent == "ADH-1001"


def test_extraction_failure_marks_ecarts_a_traiter_with_audit_reason(db_session, tmp_path):
    """Caught live (Sprint 8): a real VLM's malformed/non-JSON response
    left uncaught would strand the traite in EN_COURS_OCR forever, with no
    signal for a human to act on. Must resolve to an honest terminal state
    with the real failure reason recorded, not hang."""
    traite = _make_traite_with_documents(db_session, tmp_path)

    result = execute_analysis(traite.id, db_session, _BrokenExtractor())

    assert result.statut == TraiteStatut.ECARTS_A_TRAITER

    entries = db_session.scalars(
        select(AuditLogEntry).where(AuditLogEntry.traite_id == traite.id, AuditLogEntry.action == "analyse_echouee")
    ).all()
    assert len(entries) == 1
    assert "illisible" in entries[0].details["erreur"]

    # No half-written extraction data from the failed attempt.
    fields = db_session.scalars(select(ChampExtrait).where(ChampExtrait.traite_id == traite.id)).all()
    assert fields == []


def _pair(nom_champ: str, valeur: str) -> list[FieldCandidate]:
    return [FieldCandidate(nom_champ, 1, valeur), FieldCandidate(nom_champ, 2, valeur)]


class TestCanonicalIdentityPromotion:
    """Once the queue screen stopped collecting a bordereau intake, a
    traite is created with placeholder numero_lcn/montant/dates (see
    create_traite) — these tests prove execute_analysis replaces them with
    what was actually read off the scan, closing the gap that showed up
    live as two different "N° L-CN" values on the same analysis screen."""

    def test_coherent_extracted_identity_is_promoted_onto_the_traite(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path, numero_lcn="000000000001")
        extractor = _FakeExtractor(
            [
                *_pair(CHAMP_NUMERO_LCN, "008857459455"),
                *_pair(CHAMP_MONTANT_CHIFFRES, "2 520,000"),  # space-grouped, comma decimal — seen live
                *_pair(CHAMP_ECHEANCE, "2025-09-30"),
                *_pair(CHAMP_DATE_CREATION, "2025-01-02"),
            ]
        )

        result = execute_analysis(traite.id, db_session, extractor)

        assert result.numero_lcn == "008857459455"
        assert result.montant == Decimal("2520.000")
        assert result.date_echeance == date(2025, 9, 30)
        assert result.date_creation_traite == date(2025, 1, 2)

    def test_incoherent_extracted_numero_lcn_is_not_promoted(self, db_session, tmp_path):
        """Two disagreeing OCR occurrences are already flagged as an écart
        for manual review — promoting either one would be arbitrary."""
        traite = _make_traite_with_documents(db_session, tmp_path, numero_lcn="000000000002")
        extractor = _FakeExtractor(
            [FieldCandidate(CHAMP_NUMERO_LCN, 1, "111111111111"), FieldCandidate(CHAMP_NUMERO_LCN, 2, "222222222222")]
        )

        result = execute_analysis(traite.id, db_session, extractor)

        assert result.numero_lcn == "000000000002"

    def test_extracted_numero_lcn_colliding_with_another_traite_is_not_promoted(self, db_session, tmp_path):
        _make_traite_with_documents(db_session, tmp_path, numero_lcn="999999999999")
        traite = _make_traite_with_documents(db_session, tmp_path, numero_lcn="000000000003")
        extractor = _FakeExtractor([*_pair(CHAMP_NUMERO_LCN, "999999999999")])

        result = execute_analysis(traite.id, db_session, extractor)

        assert result.numero_lcn == "000000000003"  # kept, not swapped for a duplicate

    def test_unparseable_montant_text_is_not_promoted(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path, numero_lcn="000000000004")
        original_montant = traite.montant
        extractor = _FakeExtractor([*_pair(CHAMP_MONTANT_CHIFFRES, "illisible")])

        result = execute_analysis(traite.id, db_session, extractor)

        assert result.montant == original_montant

    def test_montant_exceeding_column_precision_is_not_promoted(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path, numero_lcn="000000000005")
        original_montant = traite.montant
        extractor = _FakeExtractor([*_pair(CHAMP_MONTANT_CHIFFRES, "999999999999999")])  # 15 digits

        result = execute_analysis(traite.id, db_session, extractor)

        assert result.montant == original_montant

    def test_unparseable_date_text_is_not_promoted(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path, numero_lcn="000000000006")
        original_echeance = traite.date_echeance
        extractor = _FakeExtractor([*_pair(CHAMP_ECHEANCE, "trente septembre")])

        result = execute_analysis(traite.id, db_session, extractor)

        assert result.date_echeance == original_echeance

    def test_partial_extraction_promotes_only_what_was_coherently_read(self, db_session, tmp_path):
        """numero_lcn read cleanly, montant illegible — one promotes, the
        other keeps its placeholder, independently of each other."""
        traite = _make_traite_with_documents(db_session, tmp_path, numero_lcn="000000000007")
        original_montant = traite.montant
        extractor = _FakeExtractor([*_pair(CHAMP_NUMERO_LCN, "008857459455")])

        result = execute_analysis(traite.id, db_session, extractor)

        assert result.numero_lcn == "008857459455"
        assert result.montant == original_montant


class TestParseHelpers:
    """Pure unit tests for the OCR-text parsing helpers — no DB, no HTTP."""

    def test_parse_montant_space_grouped_comma_decimal(self):
        assert _parse_montant("2 520,000") == Decimal("2520.000")

    def test_parse_montant_plain_dot_decimal(self):
        assert _parse_montant("2520.000") == Decimal("2520.000")

    def test_parse_montant_thousands_dot_comma_decimal(self):
        assert _parse_montant("2.520,000") == Decimal("2520.000")

    def test_parse_montant_currency_suffix_is_stripped(self):
        assert _parse_montant("2520.000 DT") == Decimal("2520.000")

    def test_parse_montant_unparseable_returns_none(self):
        assert _parse_montant("illisible") is None

    def test_parse_date_iso_format(self):
        assert _parse_date("2025-09-30") == date(2025, 9, 30)

    def test_parse_date_falls_back_to_slash_format(self):
        assert _parse_date("30/09/2025") == date(2025, 9, 30)

    def test_parse_date_unparseable_returns_none(self):
        assert _parse_date("trente septembre") is None
