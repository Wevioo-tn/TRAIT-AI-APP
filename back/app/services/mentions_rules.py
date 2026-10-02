"""Derived read-models for the analysis screen: "mentions obligatoires"
and the date-rule checks. Computed at read time from champs_extraits /
rapprochements_nlp / verifications_manuelles — never stored, for the same
reason noted on the ORM models: storing them would duplicate facts that
already live elsewhere and could drift out of sync.

This is the Sprint 4 item carried forward once a Traite -> imx.factures
link exists (``find_matching_invoice``) to make the "avance sur facture"
date rule computable at all.

Scope note: the design's "Mentions obligatoires" panel is a legal-presence
checklist of 8 items — distinct from (and not a re-listing of) the
"Contrôle de cohérence des champs dupliqués" table already built in
Sprint 4, which compares OCR occurrences against each other, not legal
presence. Of the 8, 6 are built here (Nom du tiré, Échéance, Lieu de
paiement, Date et lieu de création, Nom du bénéficiaire, Signature du
tireur). Two are not: "Dénomination lettre de change" and "Mandat pur et
simple de payer" have no data source without dedicated template-matching
this project doesn't have — listing them would mean inventing a
presence/absence neither OCR nor NLP actually determined, which is exactly
what this project has avoided doing everywhere else.
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.imx import Facture
from app.db.models.traite import (
    ChampExtrait,
    RapprochementNlp,
    StatutVerification,
    Traite,
    VerificationCode,
    VerificationManuelle,
)
from app.services.extraction import CHAMP_DATE_CREATION, CHAMP_ECHEANCE, CHAMP_LIEU_CREATION, CHAMP_RIB_TIRE, ROLE_ORDRE, ROLE_TIRE
from app.services.traite_processing import _parse_date


@dataclass(frozen=True)
class Mention:
    code: str
    label: str
    value: str | None
    status: str  # "ok" | "warn" | "absent"


@dataclass(frozen=True)
class DateRule:
    label: str
    value_a: str | None
    value_b: str | None
    ok: bool | None  # None = undetermined (e.g. no matching invoice)


def _field_value(fields: list[ChampExtrait], field_name: str) -> str | None:
    for field in sorted(fields, key=lambda item: item.occurrence):
        if field.nom_champ == field_name and field.valeur:
            return field.valeur
    return None


def evaluate_mandatory_mentions(
    traite: Traite,
    fields: list[ChampExtrait],
    nlp: list[RapprochementNlp],
    verifications: list[VerificationManuelle],
) -> list[Mention]:
    scanned_name = next((n.valeur_scan for n in nlp if n.role.value == ROLE_TIRE and n.valeur_scan), None)
    mentions = [
        Mention("nom_tire", "Nom du tiré", scanned_name, "ok" if scanned_name else "absent"),
    ]

    due_date = _field_value(fields, CHAMP_ECHEANCE)
    mentions.append(Mention("echeance", "Échéance", due_date, "ok" if due_date else "absent"))

    rib = _field_value(fields, CHAMP_RIB_TIRE) or traite.domiciliation
    mentions.append(Mention("lieu_paiement", "Lieu de paiement (RIB / domiciliation)", rib, "ok" if rib else "absent"))

    place = _field_value(fields, CHAMP_LIEU_CREATION)
    creation_date = _field_value(fields, CHAMP_DATE_CREATION)
    if place and creation_date:
        mentions.append(Mention("date_lieu_creation", "Date et lieu de création", f"{place}, {creation_date}", "ok"))
    elif place or creation_date:
        mentions.append(
            Mention("date_lieu_creation", "Date et lieu de création", place or creation_date, "warn")
        )
    else:
        mentions.append(Mention("date_lieu_creation", "Date et lieu de création", None, "absent"))

    payee = next((n.valeur_scan for n in nlp if n.role.value == ROLE_ORDRE and n.valeur_scan), None)
    mentions.append(Mention("beneficiaire", "Nom du bénéficiaire (ordre)", payee, "ok" if payee else "absent"))

    drawer_signature = next((v for v in verifications if v.code_verification == VerificationCode.SIG_TIREUR), None)
    if drawer_signature is not None and drawer_signature.statut == StatutVerification.CONFORME:
        mentions.append(Mention("signature_tireur", "Signature du tireur", "Contrôlée conforme", "ok"))
    elif drawer_signature is not None and drawer_signature.statut == StatutVerification.ANOMALIE:
        mentions.append(Mention("signature_tireur", "Signature du tireur", "Anomalie relevée", "warn"))
    elif traite.visual_marks is not None:
        detected = traite.visual_marks.get("has_signature_tireur", False)
        stamp = traite.visual_marks.get("has_cachet_tireur", False)
        detail = "Signature détectée" if detected else "Signature non détectée avec certitude"
        detail += "; cachet détecté" if stamp else "; cachet non détecté avec certitude"
        mentions.append(Mention("signature_tireur", "Signature du tireur",
                                detail + " — à vérifier manuellement", "warn"))
    else:
        mentions.append(Mention("signature_tireur", "Signature du tireur", "Non encore statuée", "absent"))

    return mentions


def evaluate_date_rules(
    traite: Traite, invoice: Facture | None, fields: list[ChampExtrait] | None = None,
) -> list[DateRule]:
    """Use extracted dates when supplied; conflicting/unreadable dates are unknown.

    Main-record dates are only a fallback for callers without extraction data,
    never a replacement for missing OCR dates in the analysis screen.
    """
    def extracted_date(name: str) -> date | None:
        values = [f.valeur for f in fields or [] if f.nom_champ == name and f.valeur]
        parsed = [_parse_date(value) for value in values]
        return parsed[0] if parsed and None not in parsed and len(set(parsed)) == 1 else None

    creation = traite.date_creation_traite if fields is None else extracted_date(CHAMP_DATE_CREATION)
    due = traite.date_echeance if fields is None else extracted_date(CHAMP_ECHEANCE)
    today = date.today()

    def rule(
        label: str,
        left: date | None,
        right: date | None,
        *,
        reverse: bool = False,
        strict: bool = False,
    ) -> DateRule:
        if left is None or right is None:
            verdict = None
        elif reverse:
            verdict = left > right if strict else left >= right
        else:
            verdict = left < right if strict else left <= right

        return DateRule(
            label, left.isoformat() if left else None, right.isoformat() if right else None,
            verdict,
        )

    return [
        rule("Date de création ≤ date du jour", creation, today),
        rule("Date de création < date d'échéance", creation, due, strict=True),
        rule("Date du jour ≤ date d'échéance", today, due),
        rule("Date de création ≥ date de la facture rapprochée",
             creation if invoice else None, invoice.date_facture if invoice else None, reverse=True),
    ]


async def find_matching_invoice(session: AsyncSession, traite: Traite) -> Facture | None:
    """Best-effort match: among the invoices between the resolved
    adherent/debiteur pair, the one whose montant_net is closest to this
    traite's montant. Simple and deterministic; genuinely ambiguous only
    when two invoices for the same pair have near-identical amounts, which
    a human reviewing the "avance sur facture" panel would catch anyway."""
    if traite.code_adherent is None or traite.code_debiteur is None:
        return None

    candidates = (
        await session.execute(
            select(Facture).where(
                Facture.code_adherent == traite.code_adherent,
                Facture.code_debiteur == traite.code_debiteur,
            )
        )
    ).scalars().all()

    if not candidates:
        return None
    return min(candidates, key=lambda f: abs(f.montant_net - traite.montant))
