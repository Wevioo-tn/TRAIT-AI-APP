"""Sprint 4 — execute_analysis: the real orchestration logic, exercised
directly against the test DB. No background task, no HTTP — see
test_analyse_endpoint.py for the API layer and test_extraction.py /
test_nlp_matching.py for the pure building blocks this composes.
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
    MethodeIdentification,
    RapprochementNlp,
    RoleNlp,
    Traite,
    TraiteDocument,
    TraiteStatut,
    VerificationCode,
    VerificationManuelle,
)
from app.services.extraction import (
    CHAMP_CLE_RIB,
    CHAMP_CODE_AGENCE,
    CHAMP_CODE_ETABLISSEMENT,
    CHAMP_DATE_CREATION,
    CHAMP_ECHEANCE,
    CHAMP_MONTANT_CHIFFRES,
    CHAMP_MONTANT_LETTRES,
    CHAMP_NUMERO_COMPTE,
    CHAMP_NUMERO_LCN,
    CHAMP_RIB_TIRE,
    ROLE_ORDRE,
    ROLE_TIRE,
    ROLE_TIREUR,
    ExtractionResult,
    FieldCandidate,
    PartyCandidate,
    StubExtractor,
)
from app.services.traite_processing import (
    _canonicalize_rib,
    _normalize_montant_lettres,
    _parse_date,
    _parse_montant,
    execute_analysis,
    reconstruct_rib,
)


class _BrokenExtractor:
    """Simulates a real extraction-backend failure (Sprint 8) — unreadable
    model response, network error, etc. — rather than guessing how such a
    failure behaves."""

    def extract(self, traite, recto, verso) -> ExtractionResult:
        raise ValueError("réponse du modèle illisible")


class _FakeExtractor:
    """Returns exactly the field/party candidates given to it — used to
    exercise canonical-identity promotion and RIB-first matching with
    values deliberately different from what's already on the traite
    (StubExtractor always echoes traite fields back and never emits a RIB
    or party text, neither of which can prove real promotion/matching
    happened)."""

    def __init__(self, fields: list[FieldCandidate], parties: list[PartyCandidate] | None = None) -> None:
        self._fields = fields
        self._parties = parties or []

    def extract(self, traite, recto, verso) -> ExtractionResult:
        return ExtractionResult(fields=self._fields, parties=self._parties)


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


RIB_DEB_1001 = "11003000291700178836"


def _seed_referential(session) -> None:
    session.add(Adherent(code_adherent="ADH-1001", raison_sociale="ADACTIM", statut_contrat=StatutContrat.ACTIF))
    session.add(
        Debiteur(
            code_debiteur="DEB-1001",
            raison_sociale="LA MÉDITERRANÉENNE",
            rib=RIB_DEB_1001,
            code_adherent="ADH-1001",  # matches real seed.py — needed for RIB-first tests to resolve the adhérent
        )
    )
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


def test_name_only_match_never_yields_controle_manuel_requis_even_at_100_score(db_session, tmp_path):
    """The main behavior change of the RIB-first story: without an
    exploitable RIB, a name-only match — however perfect its score — is a
    lead for a human to confirm, never an identification. Before this
    story, a 100%/95%+ name match alone used to resolve straight to
    CONTROLE_MANUEL_REQUIS; it must not any more."""
    traite = _make_traite_with_documents(db_session, tmp_path)
    _seed_referential(db_session)

    extractor = StubExtractor(tireur_texte="ADACTIM", tire_texte="LA MÉDITERRANÉENNE")
    result = execute_analysis(traite.id, db_session, extractor)

    assert result.statut == TraiteStatut.ECARTS_A_TRAITER
    assert result.code_adherent == "ADH-1001"
    assert result.code_debiteur == "DEB-1001"
    # The display-name properties the queue list depends on.
    assert result.tireur_nom == "ADACTIM"
    assert result.tire_nom == "LA MÉDITERRANÉENNE"

    fields = db_session.scalars(select(ChampExtrait).where(ChampExtrait.traite_id == traite.id)).all()
    assert len(fields) == 22  # 11 fields x 2 occurrences (7 original + 4 RIB sub-fields, TR-122)

    nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
    by_role = {n.role: n for n in nlp}
    assert by_role[RoleNlp.TIREUR].score == 100.0
    assert by_role[RoleNlp.TIREUR].methode_identification == MethodeIdentification.NOM_SEUL
    assert by_role[RoleNlp.TIRE].score >= 95.0
    assert by_role[RoleNlp.TIRE].methode_identification == MethodeIdentification.NOM_SEUL
    assert RoleNlp.ORDRE in by_role


class TestRibFirstIdentification:
    """RIB-first débiteur identification (UC-01, étape 4): the RIB, not the
    name, decides who the débiteur is; name comparison only ever
    corroborates a RIB match already made, and — the flip side — can never
    on its own produce an auto-confirm."""

    def _rib_pair(self, rib: str) -> list[FieldCandidate]:
        return [FieldCandidate(CHAMP_RIB_TIRE, 1, rib), FieldCandidate(CHAMP_RIB_TIRE, 2, rib)]

    def test_rib_match_with_corroborating_name_yields_controle_manuel_requis(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=self._rib_pair("11 003 000 2917 0017 8836"),  # spaced — proves canonicalization runs end to end
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        assert result.statut == TraiteStatut.CONTROLE_MANUEL_REQUIS
        assert result.code_debiteur == "DEB-1001"
        assert result.code_adherent == "ADH-1001"  # derived from the FK, not independently searched

        nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
        by_role = {n.role: n for n in nlp}
        assert by_role[RoleNlp.TIRE].methode_identification == MethodeIdentification.RIB
        assert by_role[RoleNlp.TIRE].alerte_ecart_nom is False
        assert by_role[RoleNlp.TIREUR].methode_identification == MethodeIdentification.RIB

    def test_incoherent_rib_occurrences_falls_back_to_name_only_and_never_auto_confirms(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=[
                FieldCandidate(CHAMP_RIB_TIRE, 1, RIB_DEB_1001),
                FieldCandidate(CHAMP_RIB_TIRE, 2, "00000000000000000000"),  # disagrees with occurrence 1
            ],
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        # Falls back to name-only — which, however good the score, can
        # never by itself auto-confirm (same rule as the no-RIB-at-all case).
        assert result.statut == TraiteStatut.ECARTS_A_TRAITER
        nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
        by_role = {n.role: n for n in nlp}
        assert by_role[RoleNlp.TIRE].methode_identification == MethodeIdentification.NOM_SEUL

    def test_rib_match_with_low_name_corroboration_flags_ecart_and_blocks_auto_confirm(self, db_session, tmp_path):
        """The RIB still identifies the débiteur with certainty — but a
        name that looks nothing like it is a real écart worth a human's
        attention, not something to auto-confirm past."""
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=self._rib_pair(RIB_DEB_1001),
            parties=[PartyCandidate(ROLE_TIRE, "SPG")],  # unrelated to "LA MÉDITERRANÉENNE"
        )
        result = execute_analysis(traite.id, db_session, extractor)

        assert result.statut == TraiteStatut.ECARTS_A_TRAITER
        assert result.code_debiteur == "DEB-1001"  # RIB still identifies the débiteur

        nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
        tire_row = next(n for n in nlp if n.role == RoleNlp.TIRE)
        assert tire_row.methode_identification == MethodeIdentification.RIB
        assert tire_row.alerte_ecart_nom is True
        # Real bug, found live: this exact "SPG" vs "LA MÉDITERRANÉENNE"
        # scores exactly 0.0, and best_match used to leave
        # valeur_referentiel at None in that case — the reviewer could see
        # the alert but not which name it was actually compared against
        # (see nlp_matching.py's own regression test for the root cause).
        assert tire_row.valeur_referentiel == "LA MÉDITERRANÉENNE"

        entries = db_session.scalars(
            select(AuditLogEntry).where(AuditLogEntry.traite_id == traite.id, AuditLogEntry.action == "ecart_rib_nom")
        ).all()
        assert len(entries) == 1
        assert entries[0].details["code_debiteur"] == "DEB-1001"

    def test_rib_identifies_correct_debiteur_despite_near_identical_homonym_in_referential(self, db_session, tmp_path):
        """Regression fixture, built directly here rather than depended on
        scripts/seed.py's current state (that pairing no longer exists
        there since Sprint 13): two legally distinct débiteurs with
        near-identical names and different RIBs — a real case already hit
        in this project. Name-only matching could plausibly confuse them;
        RIB cannot, because RIBs are exact and different."""
        traite = _make_traite_with_documents(db_session, tmp_path)
        db_session.add(Adherent(code_adherent="ADH-2001", raison_sociale="ADACTIM", statut_contrat=StatutContrat.ACTIF))
        db_session.add(
            Debiteur(
                code_debiteur="DEB-2001",
                raison_sociale="LA MEDITERRANEENNE",
                rib="10000000000000000001",
                code_adherent="ADH-2001",
            )
        )
        db_session.add(
            Debiteur(
                code_debiteur="DEB-2002",
                raison_sociale="LA MÉDITERRANÉENNE",
                rib="10000000000000000002",
                code_adherent="ADH-2001",
            )
        )
        db_session.flush()

        extractor = _FakeExtractor(
            fields=self._rib_pair("1000 0000 0000 0000 0002"),  # canonicalizes to DEB-2002's real RIB
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MEDITERRANEENNE"),  # the *other*, wrong-but-similar débiteur's name
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        assert result.code_debiteur == "DEB-2002"  # RIB-identified, not the accented near-homonym DEB-2001
        assert result.statut == TraiteStatut.CONTROLE_MANUEL_REQUIS  # accent-only mismatch, still well above the alert threshold

        nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
        tire_row = next(n for n in nlp if n.role == RoleNlp.TIRE)
        assert tire_row.code_debiteur_matche == "DEB-2002"
        assert tire_row.methode_identification == MethodeIdentification.RIB
        assert tire_row.alerte_ecart_nom is False


class TestRibRowAndOrdreCorroboration:
    """TR-115: an explicit RIB row in rapprochements_nlp (UC-01, étape 4),
    and a real (if scoped-down) check on "Payer à l'ordre de" against the
    resolved adhérent (Synthèse d'analyse : Traite, "cohérence avec
    contrat IMX" — no contracts model exists here, so this compares
    against the adhérent's own raison_sociale only, documented as a
    deliberate scope limit, not the full spec claim)."""

    def _rib_pair(self, rib: str) -> list[FieldCandidate]:
        return [FieldCandidate(CHAMP_RIB_TIRE, 1, rib), FieldCandidate(CHAMP_RIB_TIRE, 2, rib)]

    def test_rib_row_present_at_100_when_rib_matches(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=self._rib_pair(RIB_DEB_1001),
            parties=[PartyCandidate(ROLE_TIREUR, "ADACTIM"), PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE")],
        )
        execute_analysis(traite.id, db_session, extractor)

        nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
        rib_row = next(n for n in nlp if n.role == RoleNlp.RIB)
        assert rib_row.valeur_scan == RIB_DEB_1001
        assert rib_row.valeur_referentiel == RIB_DEB_1001
        assert rib_row.score == 100.0
        assert rib_row.code_debiteur_matche == "DEB-1001"
        assert rib_row.methode_identification == MethodeIdentification.RIB

    def test_rib_row_present_at_0_when_no_coherent_rib(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        result = execute_analysis(traite.id, db_session, StubExtractor())  # no RIB emitted at all

        nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
        rib_row = next(n for n in nlp if n.role == RoleNlp.RIB)
        assert rib_row.valeur_scan == ""
        assert rib_row.valeur_referentiel is None
        assert rib_row.score == 0.0
        assert rib_row.code_debiteur_matche is None
        assert result.statut == TraiteStatut.ECARTS_A_TRAITER

    def test_ordre_scored_against_resolved_adherent_once_debiteur_known(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=self._rib_pair(RIB_DEB_1001),
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
                PartyCandidate(ROLE_ORDRE, "ADACTIM"),  # matches the resolved adhérent exactly
            ],
        )
        execute_analysis(traite.id, db_session, extractor)

        nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
        ordre_row = next(n for n in nlp if n.role == RoleNlp.ORDRE)
        assert ordre_row.valeur_referentiel == "ADACTIM"
        assert ordre_row.score == 100.0
        assert ordre_row.code_adherent_matche == "ADH-1001"

    def test_ordre_mismatch_never_blocks_auto_confirm(self, db_session, tmp_path):
        """A low ordre/adhérent score is informational only — the spec
        doesn't say this écart should block, unlike the RIB/nom check on
        the tiré (TR-102)."""
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=self._rib_pair(RIB_DEB_1001),
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
                PartyCandidate(ROLE_ORDRE, "UNE SOCIETE SANS AUCUN RAPPORT"),
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
        ordre_row = next(n for n in nlp if n.role == RoleNlp.ORDRE)
        assert ordre_row.score < 50.0
        # Still auto-confirms — a bad ordre/adhérent score never affects statut.
        assert result.statut == TraiteStatut.CONTROLE_MANUEL_REQUIS

    def test_ordre_stays_unscored_when_no_debiteur_resolved(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(fields=[], parties=[PartyCandidate(ROLE_ORDRE, "ADACTIM")])
        execute_analysis(traite.id, db_session, extractor)

        nlp = db_session.scalars(select(RapprochementNlp).where(RapprochementNlp.traite_id == traite.id)).all()
        ordre_row = next(n for n in nlp if n.role == RoleNlp.ORDRE)
        assert ordre_row.valeur_referentiel is None
        assert ordre_row.score == 0.0


class TestRibReconstructionFromSubfields:
    """UC-01, étape 4: the RIB is also reconstructed from 4 separately
    printed sub-fields (Code étab./Code Agence/N° de Compte/Clé), compared
    against the direct rib_tire reading before either feeds match_debiteur_by_rib."""

    def _rib_pair(self, rib: str) -> list[FieldCandidate]:
        return [FieldCandidate(CHAMP_RIB_TIRE, 1, rib), FieldCandidate(CHAMP_RIB_TIRE, 2, rib)]

    def _subfield_pairs(self, code_etab: str, code_agence: str, numero_compte: str, cle: str) -> list[FieldCandidate]:
        return [
            FieldCandidate(CHAMP_CODE_ETABLISSEMENT, 1, code_etab),
            FieldCandidate(CHAMP_CODE_ETABLISSEMENT, 2, code_etab),
            FieldCandidate(CHAMP_CODE_AGENCE, 1, code_agence),
            FieldCandidate(CHAMP_CODE_AGENCE, 2, code_agence),
            FieldCandidate(CHAMP_NUMERO_COMPTE, 1, numero_compte),
            FieldCandidate(CHAMP_NUMERO_COMPTE, 2, numero_compte),
            FieldCandidate(CHAMP_CLE_RIB, 1, cle),
            FieldCandidate(CHAMP_CLE_RIB, 2, cle),
        ]

    def _incoherences_from_audit(self, session, traite_id) -> list[str]:
        entry = session.scalar(
            select(AuditLogEntry).where(AuditLogEntry.traite_id == traite_id, AuditLogEntry.action == "analyse_terminee")
        )
        return entry.details["incoherences"]

    def test_agreeing_readings_produce_no_inconsistency_and_use_the_confirmed_rib(self, db_session, tmp_path):
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=[
                *self._rib_pair(RIB_DEB_1001),
                *self._subfield_pairs("11", "003", "0002917001788", "36"),  # reconstructs to RIB_DEB_1001
            ],
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        assert "rib_tire_vs_reconstitution_4_segments" not in self._incoherences_from_audit(db_session, traite.id)
        assert result.statut == TraiteStatut.CONTROLE_MANUEL_REQUIS
        assert result.code_debiteur == "DEB-1001"
        assert result.cross_field_discrepancies == []  # TR-116: persisted snapshot, not just audit_log

    def test_disagreeing_readings_flag_an_inconsistency_and_block_auto_confirm(self, db_session, tmp_path):
        """Even though the name corroboration would otherwise be perfect,
        two disagreeing RIB readings must still block auto-confirm — same
        seriousness as any other duplicated-field écart."""
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=[
                *self._rib_pair(RIB_DEB_1001),
                *self._subfield_pairs("22", "222", "1111111111111", "22"),  # a different 20-digit RIB entirely
            ],
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        assert "rib_tire_vs_reconstitution_4_segments" in self._incoherences_from_audit(db_session, traite.id)
        assert result.statut == TraiteStatut.ECARTS_A_TRAITER
        assert result.cross_field_discrepancies == ["rib_tire_vs_reconstitution_4_segments"]

    def test_only_reconstructed_rib_exploitable_is_used_alone_without_false_disagreement(self, db_session, tmp_path):
        """rib_tire's own dedicated box illegible on this scan — the
        reconstructed RIB alone is still acceptable, not discarded as a
        "disagreement" against nothing."""
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=[
                FieldCandidate(CHAMP_RIB_TIRE, 1, None),
                FieldCandidate(CHAMP_RIB_TIRE, 2, None),
                *self._subfield_pairs("11", "003", "0002917001788", "36"),  # reconstructs to RIB_DEB_1001
            ],
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        assert "rib_tire_vs_reconstitution_4_segments" not in self._incoherences_from_audit(db_session, traite.id)
        assert result.statut == TraiteStatut.CONTROLE_MANUEL_REQUIS
        assert result.code_debiteur == "DEB-1001"
        assert result.cross_field_discrepancies == []


def test_known_fields_land_in_champs_extraits_correctly(db_session, tmp_path):
    traite = _make_traite_with_documents(db_session, tmp_path)
    _seed_referential(db_session)

    execute_analysis(traite.id, db_session, StubExtractor())

    montant_lettres = db_session.scalars(
        select(ChampExtrait).where(ChampExtrait.traite_id == traite.id, ChampExtrait.nom_champ == "montant_lettres")
    ).all()
    assert {c.valeur for c in montant_lettres} == {"Huit mille cent dix-sept dinars, 504 millimes"}


def test_domiciliation_is_persisted_when_the_model_returns_it(db_session, tmp_path):
    """TR-122 already extracted domiciliation_texte via the VLM prompt, but
    execute_analysis never read ROLE_DOMICILIATION from result.parties —
    the value arrived and was silently dropped. Now persisted as-is, no
    validation (a single, unique-occurrence attribute of the bill, not a
    duplicated field or a referential comparison)."""
    traite = _make_traite_with_documents(db_session, tmp_path)
    _seed_referential(db_session)

    extractor = StubExtractor(domiciliation_texte="UBCI Agence Paris, Tunis")
    result = execute_analysis(traite.id, db_session, extractor)

    assert result.domiciliation == "UBCI Agence Paris, Tunis"


def test_domiciliation_is_none_when_the_model_does_not_return_one(db_session, tmp_path):
    traite = _make_traite_with_documents(db_session, tmp_path)
    _seed_referential(db_session)

    result = execute_analysis(traite.id, db_session, StubExtractor())  # domiciliation_texte defaults to None

    assert result.domiciliation is None


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

    def test_canonicalize_rib_pure_digits_unchanged(self):
        assert _canonicalize_rib("11003000291700178836") == "11003000291700178836"

    def test_canonicalize_rib_strips_spaces(self):
        assert _canonicalize_rib("11 003 000 2917 0017 8836") == "11003000291700178836"

    def test_canonicalize_rib_strips_hyphens(self):
        assert _canonicalize_rib("11-003-000-2917-0017-8836") == "11003000291700178836"

    def test_canonicalize_rib_empty_returns_none(self):
        assert _canonicalize_rib("") is None

    def test_canonicalize_rib_none_returns_none(self):
        assert _canonicalize_rib(None) is None

    def test_reconstruct_rib_valid_segments(self):
        assert reconstruct_rib("11", "003", "0002917001788", "36") == "11003000291700178836"

    def test_reconstruct_rib_canonicalizes_each_segment_first(self):
        # A box's own reading can carry the same formatting noise as any
        # other RIB-shaped field — proven end to end against the real
        # sample in this story's live validation, not just here.
        assert reconstruct_rib("1 1", "0-0-3", "0002917001788", " 36 ") == "11003000291700178836"

    def test_reconstruct_rib_wrong_length_code_etablissement_returns_none(self):
        assert reconstruct_rib("111", "003", "0002917001788", "36") is None

    def test_reconstruct_rib_wrong_length_code_agence_returns_none(self):
        assert reconstruct_rib("11", "03", "0002917001788", "36") is None

    def test_reconstruct_rib_wrong_length_numero_compte_returns_none(self):
        assert reconstruct_rib("11", "003", "291700178836", "36") is None

    def test_reconstruct_rib_wrong_length_cle_returns_none(self):
        assert reconstruct_rib("11", "003", "0002917001788", "3") is None

    def test_reconstruct_rib_missing_segment_returns_none(self):
        assert reconstruct_rib("11", "003", None, "36") is None
        assert reconstruct_rib(None, None, None, None) is None

    def test_normalize_montant_lettres_case_insensitive(self):
        assert _normalize_montant_lettres("HUIT MILLE DINARS") == _normalize_montant_lettres("huit mille dinars")

    def test_normalize_montant_lettres_hyphen_vs_space(self):
        assert _normalize_montant_lettres("dix-sept") == _normalize_montant_lettres("dix sept")

    def test_normalize_montant_lettres_comma_present_or_absent(self):
        with_comma = "Huit mille cent dix-sept dinars, 504 millimes"
        without_comma = "huit mille cent dix sept dinars 504 millimes"
        assert _normalize_montant_lettres(with_comma) == _normalize_montant_lettres(without_comma)

    def test_normalize_montant_lettres_collapses_multiple_spaces(self):
        assert _normalize_montant_lettres("huit   mille  cent") == _normalize_montant_lettres("huit mille cent")


class TestMontantLettresVsChiffres:
    """montant_chiffres and montant_lettres each already get their own
    internal (occurrence 1 vs 2) coherence check — this cross-checks one
    against the other, per the spec's "conversion numérique -> cohérence
    stricte avec montant en chiffres" requirement."""

    def _rib_fields(self) -> list[FieldCandidate]:
        return [FieldCandidate(CHAMP_RIB_TIRE, 1, RIB_DEB_1001), FieldCandidate(CHAMP_RIB_TIRE, 2, RIB_DEB_1001)]

    def _incoherences_from_audit(self, session, traite_id) -> list[str]:
        entry = session.scalar(
            select(AuditLogEntry).where(AuditLogEntry.traite_id == traite_id, AuditLogEntry.action == "analyse_terminee")
        )
        return entry.details["incoherences"]

    def test_concordant_montants_add_no_inconsistency_and_do_not_block_an_otherwise_clean_match(
        self, db_session, tmp_path
    ):
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=[
                *self._rib_fields(),
                *_pair(CHAMP_MONTANT_CHIFFRES, "2520.000"),
                *_pair(CHAMP_MONTANT_LETTRES, "Deux mille cinq cent vingt dinars"),
            ],
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        assert "montant_lettres_vs_chiffres" not in self._incoherences_from_audit(db_session, traite.id)
        assert result.statut == TraiteStatut.CONTROLE_MANUEL_REQUIS
        assert result.cross_field_discrepancies == []

    def test_discordant_montants_flag_inconsistency_and_block_auto_confirm(self, db_session, tmp_path):
        """Even a RIB that matches cleanly must not auto-confirm past a
        montant_lettres that doesn't actually spell out montant_chiffres."""
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=[
                *self._rib_fields(),
                *_pair(CHAMP_MONTANT_CHIFFRES, "2520.000"),
                *_pair(CHAMP_MONTANT_LETTRES, "Trois mille dinars"),
            ],
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        assert "montant_lettres_vs_chiffres" in self._incoherences_from_audit(db_session, traite.id)
        assert result.statut == TraiteStatut.ECARTS_A_TRAITER
        assert result.cross_field_discrepancies == ["montant_lettres_vs_chiffres"]

    def test_internally_incoherent_montant_lettres_skips_cross_check(self, db_session, tmp_path):
        """One side already disagreeing with itself (its own 2 occurrences)
        is its own écart — no cross-check attempted on top, no false
        positive stacked onto an already-flagged field."""
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=[
                *_pair(CHAMP_MONTANT_CHIFFRES, "2520.000"),
                FieldCandidate(CHAMP_MONTANT_LETTRES, 1, "Deux mille cinq cent vingt dinars"),
                FieldCandidate(CHAMP_MONTANT_LETTRES, 2, "Trois mille dinars"),  # disagrees with its own occurrence 1
            ],
        )
        execute_analysis(traite.id, db_session, extractor)

        incoherences = self._incoherences_from_audit(db_session, traite.id)
        assert "montant_lettres_vs_chiffres" not in incoherences
        assert CHAMP_MONTANT_LETTRES in incoherences  # the field's own occurrence mismatch is still flagged

    def test_stub_extractor_real_fixture_has_no_montant_cross_check_regression(self, db_session, tmp_path):
        """StubExtractor always derives montant_lettres from the traite's
        own montant via the real amount_to_words (montant=8117.504 ->
        "Huit mille cent dix-sept dinars, 504 millimes", see
        test_known_fields_land_in_champs_extraits_correctly) — proven here
        to never trip the new cross-check."""
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        execute_analysis(traite.id, db_session, StubExtractor())

        assert "montant_lettres_vs_chiffres" not in self._incoherences_from_audit(db_session, traite.id)


class TestNumeroLcnVsCodeBarres:
    """Second, independent source for numero_lcn (Synthèse d'analyse :
    Traite, "N° L-CN" — "OCR texte haut droite + lecture code-barres bas =
    double vérification croisée"): the printed barcode, decoded directly
    off the raw recto bytes — independent of OCR_PROVIDER/the extractor
    used, so decode_barcode is monkeypatched at its call site rather than
    exercised through a real image here (see test_barcode_reading.py for
    the real decoding path)."""

    def _incoherences_from_audit(self, session, traite_id) -> list[str]:
        entry = session.scalar(
            select(AuditLogEntry).where(AuditLogEntry.traite_id == traite_id, AuditLogEntry.action == "analyse_terminee")
        )
        return entry.details["incoherences"]

    def test_concordant_barcode_adds_no_inconsistency(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setattr("app.services.traite_processing.decode_barcode", lambda recto: "011570763437")
        traite = _make_traite_with_documents(db_session, tmp_path)  # numero_lcn defaults to "011570763437"
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=[
                *_pair(CHAMP_NUMERO_LCN, "011570763437"),
                FieldCandidate(CHAMP_RIB_TIRE, 1, RIB_DEB_1001),
                FieldCandidate(CHAMP_RIB_TIRE, 2, RIB_DEB_1001),
            ],
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        assert "numero_lcn_vs_code_barres" not in self._incoherences_from_audit(db_session, traite.id)
        assert result.statut == TraiteStatut.CONTROLE_MANUEL_REQUIS
        assert result.cross_field_discrepancies == []

    def test_discordant_barcode_flags_inconsistency_and_blocks_auto_confirm(self, db_session, tmp_path, monkeypatch):
        """Even a RIB that matches cleanly must not auto-confirm past a
        barcode that disagrees with the OCR'd numero_lcn."""
        monkeypatch.setattr("app.services.traite_processing.decode_barcode", lambda recto: "999999999999")
        traite = _make_traite_with_documents(db_session, tmp_path)  # numero_lcn defaults to "011570763437"
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=[
                *_pair(CHAMP_NUMERO_LCN, "011570763437"),
                FieldCandidate(CHAMP_RIB_TIRE, 1, RIB_DEB_1001),
                FieldCandidate(CHAMP_RIB_TIRE, 2, RIB_DEB_1001),
            ],
            parties=[
                PartyCandidate(ROLE_TIREUR, "ADACTIM"),
                PartyCandidate(ROLE_TIRE, "LA MÉDITERRANÉENNE"),
            ],
        )
        result = execute_analysis(traite.id, db_session, extractor)

        assert "numero_lcn_vs_code_barres" in self._incoherences_from_audit(db_session, traite.id)
        assert result.statut == TraiteStatut.ECARTS_A_TRAITER
        assert result.cross_field_discrepancies == ["numero_lcn_vs_code_barres"]

    def test_no_barcode_detected_leaves_behavior_unchanged(self, db_session, tmp_path, monkeypatch):
        """Most real scans (cropped, rotated, low quality) won't have a
        decodable barcode at all — a missing bonus signal, not a
        discrepancy."""
        monkeypatch.setattr("app.services.traite_processing.decode_barcode", lambda recto: None)
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        execute_analysis(traite.id, db_session, StubExtractor())

        assert "numero_lcn_vs_code_barres" not in self._incoherences_from_audit(db_session, traite.id)

    def test_incoherent_numero_lcn_occurrences_skip_the_barcode_comparison(self, db_session, tmp_path, monkeypatch):
        """numero_lcn's own 2 OCR occurrences already disagree — that's its
        own écart; no barcode comparison is attempted on top of it."""
        monkeypatch.setattr("app.services.traite_processing.decode_barcode", lambda recto: "999999999999")
        traite = _make_traite_with_documents(db_session, tmp_path)
        _seed_referential(db_session)

        extractor = _FakeExtractor(
            fields=[
                FieldCandidate(CHAMP_NUMERO_LCN, 1, "011570763437"),
                FieldCandidate(CHAMP_NUMERO_LCN, 2, "000000000000"),  # disagrees with its own occurrence 1
            ],
        )
        execute_analysis(traite.id, db_session, extractor)

        assert "numero_lcn_vs_code_barres" not in self._incoherences_from_audit(db_session, traite.id)
