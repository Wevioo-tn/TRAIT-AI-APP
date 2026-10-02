"""Pure unit tests for evaluate_mandatory_mentions / evaluate_date_rules — no DB, no HTTP."""
from datetime import date, timedelta
from decimal import Decimal

from app.db.models.imx import Debiteur, Facture, StatutFacture
from app.db.models.traite import (
    ChampExtrait,
    RapprochementNlp,
    RoleNlp,
    SourceChamp,
    StatutVerification,
    Traite,
    VerificationCode,
    VerificationManuelle,
)
from app.services.mentions_rules import evaluate_date_rules, evaluate_mandatory_mentions


def _field(nom_champ: str, valeur: str | None) -> ChampExtrait:
    return ChampExtrait(nom_champ=nom_champ, occurrence=1, valeur=valeur, source=SourceChamp.OCR)


def _traite(**overrides) -> Traite:
    # Dates default to offsets from today, not hardcoded absolutes — a
    # fixed date drifts into the past as real time passes and starts
    # failing date-rule tests for reasons unrelated to the logic under
    # test (caught exactly this way while building this suite).
    today = date.today()
    defaults = dict(
        numero_lcn="011570763437",
        montant=Decimal("8117.504"),
        date_echeance=today + timedelta(days=20),
        date_creation_traite=today - timedelta(days=5),
    )
    defaults.update(overrides)
    return Traite(**defaults)


def _invoice(**overrides) -> Facture:
    defaults = dict(
        num_facture="FA-26-0117",
        code_adherent="ADH-1001",
        code_debiteur="DEB-1001",
        montant_ttc=Decimal("8400.000"),
        montant_avoirs=Decimal("282.496"),
        date_facture=date(2026, 8, 7),
        statut=StatutFacture.ENCOURS,
    )
    defaults.update(overrides)
    invoice = Facture(**defaults)
    # montant_net is a DB-generated column (Computed) — simulate it here for
    # pure unit tests that never touch a real database.
    invoice.montant_net = invoice.montant_ttc - invoice.montant_avoirs
    return invoice


class TestEvaluateMandatoryMentions:
    def test_all_present_and_conforme(self):
        traite = _traite()
        traite.debiteur = Debiteur(code_debiteur="DEB-1001", raison_sociale="LA MÉDITERRANÉENNE", rib="x")
        fields = [
            _field("echeance", "2026-08-28"),
            _field("lieu_creation", "Tunis"),
            _field("date_creation", "2026-08-05"),
            _field("rib_tire", "11003000291700178836"),
        ]
        nlp = [RapprochementNlp(role=RoleNlp.TIRE, valeur_scan="Scanned debtor", score=0),
               RapprochementNlp(role=RoleNlp.ORDRE, valeur_scan="SPG", score=Decimal("0"))]
        verifs = [
            VerificationManuelle(code_verification=VerificationCode.SIG_TIREUR, statut=StatutVerification.CONFORME)
        ]

        mentions = evaluate_mandatory_mentions(traite, fields, nlp, verifs)
        statuses = {m.code: m.status for m in mentions}
        assert all(s == "ok" for s in statuses.values())
        # 6 of the design's 8 mentions obligatoires — see module docstring
        # for the 2 that have no data source without dedicated OCR.
        assert len(mentions) == 6

    def test_nom_tire_absent_before_nlp_resolution(self):
        mentions = evaluate_mandatory_mentions(_traite(), fields=[], nlp=[], verifications=[])
        nom_tire = next(m for m in mentions if m.code == "nom_tire")
        assert nom_tire.status == "absent"

    def test_missing_champ_reported_as_absent_not_invented(self):
        mentions = evaluate_mandatory_mentions(_traite(), fields=[], nlp=[], verifications=[])
        lieu_paiement = next(m for m in mentions if m.code == "lieu_paiement")
        assert lieu_paiement.status == "absent"
        assert lieu_paiement.value is None

    def test_date_et_lieu_creation_partial_is_a_warning(self):
        fields = [_field("lieu_creation", "Tunis")]  # date_creation missing
        mentions = evaluate_mandatory_mentions(_traite(), fields, nlp=[], verifications=[])
        combo = next(m for m in mentions if m.code == "date_lieu_creation")
        assert combo.status == "warn"

    def test_signature_tireur_anomalie_is_warn_not_absent(self):
        verifs = [VerificationManuelle(code_verification=VerificationCode.SIG_TIREUR, statut=StatutVerification.ANOMALIE)]
        mentions = evaluate_mandatory_mentions(_traite(), fields=[], nlp=[], verifications=verifs)
        sig = next(m for m in mentions if m.code == "signature_tireur")
        assert sig.status == "warn"

    def test_signature_tireur_not_yet_statued_is_absent(self):
        verifs = [VerificationManuelle(code_verification=VerificationCode.SIG_TIREUR, statut=None)]
        mentions = evaluate_mandatory_mentions(_traite(), fields=[], nlp=[], verifications=verifs)
        sig = next(m for m in mentions if m.code == "signature_tireur")
        assert sig.status == "absent"


class TestEvaluateDateRules:
    """Uses offsets from date.today() throughout, not hardcoded absolute
    dates — a fixed date like "2026-08-28" silently drifts into the past
    as real time passes and starts failing "today <= échéance" for reasons
    that have nothing to do with the logic under test (caught exactly this
    way while building this suite)."""

    def test_all_rules_ok_with_a_consistent_facture(self):
        today = date.today()
        traite = _traite(
            date_creation_traite=today - timedelta(days=5),
            date_echeance=today + timedelta(days=20),
        )
        invoice = _invoice(date_facture=today - timedelta(days=10))  # before creation: consistent

        rules = evaluate_date_rules(traite, invoice)
        assert len(rules) == 4
        assert all(r.ok is not False for r in rules)  # no violation

    def test_avance_sur_facture_detected_when_traite_created_before_invoice(self):
        today = date.today()
        traite = _traite(date_creation_traite=today - timedelta(days=5), date_echeance=today + timedelta(days=20))
        invoice = _invoice(date_facture=today - timedelta(days=2))  # after creation: advance on invoice

        rules = evaluate_date_rules(traite, invoice)
        advance = next(r for r in rules if "facture" in r.label)
        assert advance.ok is False

    def test_facture_not_resolved_yields_indeterminate_not_a_false_pass(self):
        traite = _traite()
        rules = evaluate_date_rules(traite, invoice=None)
        advance = next(r for r in rules if "facture" in r.label)
        assert advance.ok is None
        assert advance.value_a is None and advance.value_b is None

    def test_echeance_before_creation_is_flagged(self):
        today = date.today()
        traite = _traite(date_creation_traite=today, date_echeance=today - timedelta(days=30))
        rules = evaluate_date_rules(traite, invoice=None)
        rule = next(r for r in rules if r.label == "Date de création < date d'échéance")
        assert rule.ok is False

    def test_echeance_equal_to_creation_is_flagged(self):
        same_day = date.today()
        traite = _traite(date_creation_traite=same_day, date_echeance=same_day)
        rules = evaluate_date_rules(traite, invoice=None)
        rule = next(r for r in rules if r.label == "Date de création < date d'échéance")
        assert rule.ok is False


def test_scanned_name_presence_does_not_require_imx_match():
    bill = _traite()
    row = RapprochementNlp(role=RoleNlp.TIRE, valeur_scan="KAMEL JANDOUBI", score=0)
    mention = evaluate_mandatory_mentions(bill, [], [row], [])[0]
    assert mention.value == "KAMEL JANDOUBI"
    assert mention.status == "ok"
    bill.debiteur = Debiteur(code_debiteur="OTHER", raison_sociale="Different IMX name", rib="x")
    assert evaluate_mandatory_mentions(bill, [], [row], [])[0].value == "KAMEL JANDOUBI"
    assert evaluate_mandatory_mentions(bill, [], [], [])[0].status == "absent"


def test_detected_signature_is_not_manual_approval():
    bill = _traite()
    bill.visual_marks = {"has_signature_tireur": True, "has_cachet_tireur": False}
    mention = evaluate_mandatory_mentions(bill, [], [], [])[-1]
    assert mention.status == "warn"
    verification = VerificationManuelle(code_verification=VerificationCode.SIG_TIREUR,
                                        statut=StatutVerification.CONFORME)
    assert evaluate_mandatory_mentions(bill, [], [], [verification])[-1].status == "ok"
    verification.statut = StatutVerification.ANOMALIE
    assert evaluate_mandatory_mentions(bill, [], [], [verification])[-1].status == "warn"


def test_date_rules_use_transcribed_two_digit_years_not_main_record():
    fields = [_field("date_creation", "07/09/26"), _field("echeance", "30/09/25")]
    rules = evaluate_date_rules(_traite(), None, fields)
    assert rules[1].value_a == "2026-09-07"
    assert rules[1].value_b == "2025-09-30"
    assert rules[1].ok is False
    assert all(rule.ok is None for rule in evaluate_date_rules(_traite(), None, []))
    fields.append(ChampExtrait(nom_champ="echeance", occurrence=2, valeur="30/09/26", source=SourceChamp.OCR))
    assert evaluate_date_rules(_traite(), None, fields)[1].ok is None


def test_domiciliation_is_available_without_rib():
    bill = _traite()
    bill.domiciliation = "UBCI"
    mention = next(m for m in evaluate_mandatory_mentions(bill, [], [], []) if m.code == "lieu_paiement")
    assert mention.value == "UBCI"
    assert mention.status == "ok"
