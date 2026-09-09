"""Debtor per-rubrique control rollup (BPMN Phase 2, étape 10 —
"Visualiser le résultat OK/KO par rubrique sur l'écran principal").

Computed live, at read time — same reasoning as coverage.py: a debtor's
rollup depends on every bill known for them, which can change
independently of this one bill's own last analysis. Reuses each bill's
own already-computed verdicts (evaluate_mandatory_mentions,
evaluate_date_rules, compute_inconsistencies, the RIB-based
identification already recorded on rapprochements_nlp — TR-102) rather
than inventing new per-rubrique criteria.

Scope limit, deliberate — same as coverage.py: the full spec aggregates
by "remise" (a batch grouping, still deferred). This aggregates over
*every* bill this app currently knows about for the debtor instead of
"this remise's bills only" — real and actionable today, but a future
remise-grouping story needs to narrow the query below to one remise's
bills, not rebuild this calculation from scratch.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.traite import MethodeIdentification, RoleNlp, Traite
from app.services.coverage import calculate_debtor_coverage
from app.services.mentions_rules import evaluate_date_rules, evaluate_mandatory_mentions, find_matching_invoice
from app.services.traite_processing import compute_inconsistencies


@dataclass(frozen=True)
class DebtorControlRollup:
    mandatory_mentions_ok: bool
    duplicated_fields_ok: bool
    date_rules_ok: bool
    identification_ok: bool
    coverage_ok: bool


async def calculate_debtor_control_rollup(session: AsyncSession, debtor_code: str) -> DebtorControlRollup:
    """One bool per rubrique, true only if *every* bill this app
    currently knows about for ``debtor_code`` passes it (not scoped to
    any one "remise" — see module docstring):

    - ``mandatory_mentions_ok``: every bill's evaluate_mandatory_mentions
      result has no "absent"/"warn" mention.
    - ``duplicated_fields_ok``: every bill's compute_inconsistencies,
      recomputed from its own persisted ChampExtrait rows (never
      duplicating that logic by hand — see compute_inconsistencies'
      docstring), is empty.
    - ``date_rules_ok``: every bill's evaluate_date_rules has no rule
      with ``ok=False``. A rule with ``ok=None`` (no matching invoice to
      judge it against) is skipped — no data to judge, not a failure.
    - ``identification_ok``: every bill's tireur AND tiré
      RapprochementNlp rows were resolved via RIB (TR-102), not
      name-only, and carry no alerte_ecart_nom. A bill missing either row
      entirely counts as not resolved — no data doesn't default to "ok"
      here, unlike date_rules_ok's own deliberate exception above.
    - ``coverage_ok``: reuses calculate_debtor_coverage(...).sufficient
      directly — never recomputed here.
    """
    bills = (
        await session.execute(
            select(Traite)
            .where(Traite.code_debiteur == debtor_code)
            .options(
                selectinload(Traite.champs_extraits),
                selectinload(Traite.rapprochements_nlp),
                selectinload(Traite.verifications_manuelles),
                selectinload(Traite.debiteur),
            )
        )
    ).scalars().all()

    mandatory_mentions_ok = True
    duplicated_fields_ok = True
    date_rules_ok = True
    identification_ok = True

    for bill in bills:
        mentions = evaluate_mandatory_mentions(
            bill, bill.champs_extraits, bill.rapprochements_nlp, bill.verifications_manuelles
        )
        if any(mention.status in ("absent", "warn") for mention in mentions):
            mandatory_mentions_ok = False

        by_field: dict[str, list[str | None]] = {}
        for field in bill.champs_extraits:
            by_field.setdefault(field.nom_champ, []).append(field.valeur)
        if compute_inconsistencies(by_field):
            duplicated_fields_ok = False

        invoice = await find_matching_invoice(session, bill)
        if any(rule.ok is False for rule in evaluate_date_rules(bill, invoice)):
            date_rules_ok = False

        nlp_by_role = {row.role: row for row in bill.rapprochements_nlp}
        for role in (RoleNlp.TIREUR, RoleNlp.TIRE):
            row = nlp_by_role.get(role)
            if row is None or row.methode_identification != MethodeIdentification.RIB or row.alerte_ecart_nom:
                identification_ok = False

    coverage = await calculate_debtor_coverage(session, debtor_code)

    return DebtorControlRollup(
        mandatory_mentions_ok=mandatory_mentions_ok,
        duplicated_fields_ok=duplicated_fields_ok,
        date_rules_ok=date_rules_ok,
        identification_ok=identification_ok,
        coverage_ok=coverage.sufficient,
    )
