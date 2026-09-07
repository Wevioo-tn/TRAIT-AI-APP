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
from app.services.extraction import CHAMP_DATE_CREATION, CHAMP_ECHEANCE, CHAMP_LIEU_CREATION, CHAMP_RIB_TIRE, ROLE_ORDRE


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
    for field in fields:
        if field.nom_champ == field_name and field.valeur:
            return field.valeur
    return None


def evaluate_mandatory_mentions(
    traite: Traite,
    fields: list[ChampExtrait],
    nlp: list[RapprochementNlp],
    verifications: list[VerificationManuelle],
) -> list[Mention]:
    mentions = [
        Mention("nom_tire", "Nom du tiré", traite.tire_nom, "ok" if traite.tire_nom else "absent"),
    ]

    due_date = _field_value(fields, CHAMP_ECHEANCE)
    mentions.append(Mention("echeance", "Échéance", due_date, "ok" if due_date else "absent"))

    rib = _field_value(fields, CHAMP_RIB_TIRE)
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
    else:
        mentions.append(Mention("signature_tireur", "Signature du tireur", "Non encore statuée", "absent"))

    return mentions


def evaluate_date_rules(traite: Traite, invoice: Facture | None) -> list[DateRule]:
    today = date.today()
    rules = [
        DateRule(
            "Date de création ≤ date du jour",
            traite.date_creation_traite.isoformat(),
            today.isoformat(),
            traite.date_creation_traite <= today,
        ),
        DateRule(
            "Date de création ≤ date d'échéance",
            traite.date_creation_traite.isoformat(),
            traite.date_echeance.isoformat(),
            traite.date_creation_traite <= traite.date_echeance,
        ),
        DateRule(
            "Date du jour ≤ date d'échéance",
            today.isoformat(),
            traite.date_echeance.isoformat(),
            today <= traite.date_echeance,
        ),
    ]
    if invoice is not None:
        rules.append(
            DateRule(
                "Date de création ≥ date de la facture rapprochée",
                traite.date_creation_traite.isoformat(),
                invoice.date_facture.isoformat(),
                traite.date_creation_traite >= invoice.date_facture,
            )
        )
    else:
        rules.append(DateRule("Date de création ≥ date de la facture rapprochée", None, None, None))
    return rules


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
