"""Debtor invoice-coverage check (BPMN Phase 3, étape 3 — "Contrôler la
couverture des factures par les IP par débiteur, seuil
Seuil_Ecart_Couverture").

Computed live, at read time (see routes/traites.py's ``_build_detail``)
— never during ``execute_analysis``. A debtor's coverage depends on
every other bill already known for them and on avoirs saisis entered
anywhere for them (see ``Traite.montant_avoirs_saisi``, TR-113), both of
which can change independently of this one bill's own last analysis. A
value frozen at analysis time would go stale the moment a sibling bill
or a saisie changes.

Scope limit, deliberate — read before touching this for a future
remise-grouping story: the full spec aggregates by "remise" (a batch
grouping, still deferred). This aggregates over *every* bill this app
currently knows about for the debtor instead of "this remise's bills
only" — real and actionable today, but that future story needs to
narrow the query below to one remise's bills, not rebuild this
calculation from scratch.
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.traite import Traite
from app.services.mentions_rules import find_matching_invoice
from app.services.traite_processing import PLACEHOLDER_BILL_AMOUNT


@dataclass(frozen=True)
class DebtorCoverage:
    total_bills_amount: Decimal
    total_invoices_net_amount: Decimal
    total_credit_notes_amount: Decimal
    gap: Decimal
    sufficient: bool


async def calculate_debtor_coverage(session: AsyncSession, debtor_code: str) -> DebtorCoverage:
    """Aggregates, across every bill this app currently knows about for
    ``debtor_code`` (not scoped to any one "remise" — see module
    docstring):

    - ``total_bills_amount``: sum of each bill's own montant, excluding
      any still stuck at ``PLACEHOLDER_BILL_AMOUNT`` (never promoted by a
      real OCR read — see ``traite_processing._promote_canonical_identity``;
      including it would sum in a meaningless sentinel, not a real amount).
    - ``total_invoices_net_amount``: sum of ``montant_net`` over the
      *distinct* IMX invoices reconciled to at least one of these bills
      (via the same ``find_matching_invoice`` each bill's own detail view
      already uses) — deduplicated by ``num_facture``, since more than one
      bill can reconcile to the same invoice and it must never be counted
      twice.
    - ``total_credit_notes_amount``: sum of ``montant_avoirs_saisi``
      (TR-113) over these bills — a deduction on top of whatever avoirs
      IMX's own ``montant_net`` already nets out, not a replacement for it.
    - ``gap``: ``(total_invoices_net_amount - total_credit_notes_amount)
      - total_bills_amount``.
    - ``sufficient``: ``abs(gap) <= Settings.coverage_gap_threshold``.
    """
    bills = (await session.execute(select(Traite).where(Traite.code_debiteur == debtor_code))).scalars().all()

    total_bills_amount = sum(
        (bill.montant for bill in bills if bill.montant != PLACEHOLDER_BILL_AMOUNT),
        Decimal("0.000"),
    )
    total_credit_notes_amount = sum(
        (bill.montant_avoirs_saisi for bill in bills if bill.montant_avoirs_saisi is not None),
        Decimal("0.000"),
    )

    invoices_by_num_facture = {}
    for bill in bills:
        invoice = await find_matching_invoice(session, bill)
        if invoice is not None:
            invoices_by_num_facture[invoice.num_facture] = invoice
    total_invoices_net_amount = sum(
        (Decimal(str(invoice.montant_net)) for invoice in invoices_by_num_facture.values()),
        Decimal("0.000"),
    )

    gap = (total_invoices_net_amount - total_credit_notes_amount) - total_bills_amount
    sufficient = abs(gap) <= get_settings().coverage_gap_threshold

    return DebtorCoverage(
        total_bills_amount=total_bills_amount,
        total_invoices_net_amount=total_invoices_net_amount,
        total_credit_notes_amount=total_credit_notes_amount,
        gap=gap,
        sufficient=sufficient,
    )
