"""Pure unit tests for evaluate_verifications — no DB, no HTTP.

Covers every reachable combination of the mockup's bloque/reco logic. One
branch (sig_tireur statued but not conforme, while everything else passes)
is unreachable given today's 2-value StatutVerification domain — it was
equally unreachable in the source mockup for the same reason — so it isn't
(and can't honestly be) exercised here; see the comment in
verification_rules.py.
"""
from app.db.models.traite import StatutVerification, VerificationCode, VerificationManuelle
from app.services.verification_rules import evaluate_verifications

CONFORME = StatutVerification.CONFORME
ANOMALIE = StatutVerification.ANOMALIE


def _verifs(**statuts: StatutVerification | None) -> list[VerificationManuelle]:
    """Build the 4 mandatory verification rows; unspecified codes default to
    unstatued (None), matching a freshly created traite."""
    return [
        VerificationManuelle(code_verification=code, statut=statuts.get(code.value))
        for code in VerificationCode
    ]


def test_all_unset_is_blocked_as_incomplete():
    state = evaluate_verifications(_verifs())
    assert state.blocked is True
    assert state.reason == "Vérifications manuelles incomplètes (0 / 4)"
    assert state.recommendation.title == "Terminer les vérifications manuelles"


def test_partially_statued_is_blocked_as_incomplete():
    state = evaluate_verifications(_verifs(sigTire=CONFORME, accept=CONFORME))
    assert state.blocked is True
    assert state.reason == "Vérifications manuelles incomplètes (2 / 4)"


def test_missing_only_sig_tireur_is_still_incomplete_not_a_special_case():
    state = evaluate_verifications(_verifs(sigTire=CONFORME, accept=CONFORME, endos=CONFORME))
    assert state.blocked is True
    assert state.reason == "Vérifications manuelles incomplètes (3 / 4)"


def test_all_conforme_including_sig_tireur_unblocks_validation():
    state = evaluate_verifications(
        _verifs(sigTire=CONFORME, accept=CONFORME, sigTireur=CONFORME, endos=CONFORME)
    )
    assert state.blocked is False
    assert state.reason is None
    assert state.recommendation.title == "Valider la traite"


def test_anomaly_on_a_non_signature_zone_blocks_and_recommends_fraud():
    state = evaluate_verifications(
        _verifs(sigTire=CONFORME, accept=ANOMALIE, sigTireur=CONFORME, endos=CONFORME)
    )
    assert state.blocked is True
    assert state.reason == "Anomalie constatée sur une zone de contrôle humain"
    assert state.recommendation.title == "Signaler une fraude potentielle"


def test_anomaly_on_sig_tireur_itself_blocks_and_recommends_fraud():
    state = evaluate_verifications(
        _verifs(sigTire=CONFORME, accept=CONFORME, sigTireur=ANOMALIE, endos=CONFORME)
    )
    assert state.blocked is True
    assert state.reason == "Anomalie constatée sur une zone de contrôle humain"


def test_anomaly_takes_priority_over_incomplete_when_both_are_true():
    state = evaluate_verifications(_verifs(sigTire=ANOMALIE))
    assert state.blocked is True
    assert state.reason == "Anomalie constatée sur une zone de contrôle humain"
