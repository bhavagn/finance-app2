"""Statement-level reconciliation equations — pure arithmetic on primitives.

Each returns the SIGNED diff (computed - printed_target): its sign tells you the direction of the
miss, not just the magnitude. Three models observed across real statements (finance-app-spec.md
§5): savings uses a per-row running balance, HDFC card uses prev - payments + purchases + finance,
ICICI card uses prev + purchases + cash - payments. All three are wired up now even though only
running_balance is exercised by the golden test this increment — the equations are one line each
and independent of the parser.
"""
from __future__ import annotations

from decimal import Decimal


def running_balance_diff(opening: Decimal, closing: Decimal, signed_sum: Decimal) -> Decimal:
    """Savings: opening + sum(signed amounts) should equal closing."""
    return (opening + signed_sum) - closing


def card_dues_diff(
    previous_dues: Decimal,
    total_payments: Decimal,
    total_purchases: Decimal,
    finance_charges: Decimal,
    total_due: Decimal,
) -> Decimal:
    """HDFC card: prev_dues - payments + purchases + finance_charges should equal total_due."""
    return (previous_dues - total_payments + total_purchases + finance_charges) - total_due


def prev_plus_purch_diff(
    previous_dues: Decimal,
    total_purchases: Decimal,
    total_payments: Decimal,
    total_due: Decimal,
    cash_advances: Decimal = Decimal("0"),
    # TODO: needs a column if a card ever shows a nonzero cash advance — statements has none yet.
) -> Decimal:
    """ICICI card: prev_dues + purchases + cash_advances - payments should equal total_due."""
    return (previous_dues + total_purchases + cash_advances - total_payments) - total_due
