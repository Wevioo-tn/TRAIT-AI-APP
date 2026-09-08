"""Pure unit tests for best_match, plus match_debiteur_by_rib — the one
function in this module that does talk to the DB (see nlp_matching.py's
docstring for why that's a deliberate exception)."""
from app.db.models.imx import Debiteur
from app.services.nlp_matching import best_match, match_debiteur_by_rib


def test_exact_match_scores_100():
    result = best_match("ADACTIM", [("ADH-1001", "ADACTIM")])
    assert result.code == "ADH-1001"
    assert result.score == 100.0


def test_picks_the_best_of_several_candidates():
    result = best_match(
        "ADACTIM",
        [("ADH-0001", "SOTUMAG"), ("ADH-1001", "ADACTIM"), ("ADH-0002", "STE TEXTIS")],
    )
    assert result.code == "ADH-1001"
    assert result.score == 100.0


def test_accent_only_difference_scores_high_but_not_enough_to_auto_confirm():
    # Missing accents (exactly the kind of noise real OCR introduces) score
    # 88.89 with WRatio — clearly the right match, but *below* the design's
    # 95% auto-confirm threshold. Real accented input would need to be this
    # exact string to hit 95+; see BACKLOG.md re: accent-normalization.
    result = best_match("LA MEDITERRANEENNE", [("DEB-1001", "LA MÉDITERRANÉENNE")])
    assert 85.0 <= result.score < 95.0


def test_unrelated_text_scores_low():
    result = best_match("SPG", [("ADH-1001", "ADACTIM")])
    assert result.score < 50.0


def test_no_scanned_text_returns_null_match():
    result = best_match(None, [("ADH-1001", "ADACTIM")])
    assert result.code is None
    assert result.score == 0.0


def test_no_candidates_returns_null_match():
    result = best_match("ADACTIM", [])
    assert result.code is None
    assert result.score == 0.0


def test_case_only_difference_scores_high_not_5():
    # Real bug, found live: WRatio is case-sensitive on its own — the exact
    # same name in a different case used to score 5.6, not ~100, before
    # best_match started casefolding both sides.
    result = best_match("la mediterraneenne", [("DEB-1001", "LA MEDITERRANEENNE")])
    assert result.score == 100.0


def test_case_and_accent_difference_still_below_auto_confirm_threshold():
    result = best_match("la mediterraneenne", [("DEB-1001", "LA MÉDITERRANÉENNE")])
    assert 85.0 <= result.score < 95.0


class TestMatchDebiteurByRib:
    """match_debiteur_by_rib — exact match only, against the real test DB."""

    def test_exact_rib_matches(self, db_session):
        db_session.add(Debiteur(code_debiteur="DEB-9001", raison_sociale="TEST SA", rib="99999999999999999901"))
        db_session.flush()

        result = match_debiteur_by_rib("99999999999999999901", db_session)

        assert result.code_debiteur == "DEB-9001"
        assert result.reference_value == "TEST SA"

    def test_near_exact_rib_does_not_match(self, db_session):
        """A single mistyped digit must never resolve to a guess — that's
        exactly the risk RIB-first identification exists to eliminate."""
        db_session.add(Debiteur(code_debiteur="DEB-9002", raison_sociale="TEST SA", rib="99999999999999999902"))
        db_session.flush()

        result = match_debiteur_by_rib("99999999999999999999", db_session)

        assert result.code_debiteur is None
        assert result.reference_value is None

    def test_absent_rib_returns_null_match(self, db_session):
        result = match_debiteur_by_rib("00000000000000000000", db_session)

        assert result.code_debiteur is None
        assert result.code_adherent is None
        assert result.reference_value is None

    def test_matched_code_adherent_comes_from_the_fk(self, db_session):
        from app.db.models.imx import Adherent, StatutContrat

        db_session.add(Adherent(code_adherent="ADH-9001", raison_sociale="TEST ADH", statut_contrat=StatutContrat.ACTIF))
        db_session.add(
            Debiteur(
                code_debiteur="DEB-9003",
                raison_sociale="TEST SA",
                rib="99999999999999999903",
                code_adherent="ADH-9001",
            )
        )
        db_session.flush()

        result = match_debiteur_by_rib("99999999999999999903", db_session)

        assert result.code_adherent == "ADH-9001"
