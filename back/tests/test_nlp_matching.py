"""Pure unit tests for best_match — no DB, no HTTP."""
from app.services.nlp_matching import best_match


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
