"""row_balance, statement_eq, result (tolerance -> tri-state reconciled | reconciled_with_warning |
unreconciled), composed here into reconcile_statement — the module's one entry point.

Pure logic only: no DB, no PDF, no I/O anywhere in this package. Money is Decimal throughout.
reconcile_statement is the only place that adapts a domain object (stmt_meta, txns) into the
primitives result.py/statement_eq.py/row_balance.py operate on, so the core stays unit-testable
without constructing full domain objects (see finance-app-spec.md §4.3, §5, §6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, List, Sequence

from models.enums import ReconState

from .result import DEFAULT_TOLERANCE, classify
from .row_balance import RowMismatch, WalkResult, walk
from .statement_eq import card_dues_diff, prev_plus_purch_diff, running_balance_diff

__all__ = [
    "ReconciliationResult",
    "reconcile_statement",
    "classify",
    "running_balance_diff",
    "card_dues_diff",
    "prev_plus_purch_diff",
    "walk",
    "RowMismatch",
    "WalkResult",
]

_SEVERITY = {
    ReconState.RECONCILED: 0,
    ReconState.RECONCILED_WITH_WARNING: 1,
    ReconState.UNRECONCILED: 2,
}


def _more_severe(a: ReconState, b: ReconState) -> ReconState:
    return a if _SEVERITY[a] >= _SEVERITY[b] else b


@dataclass
class ReconciliationResult:
    """Maps directly onto statements.recon_status / statements.recon_diff."""

    recon_status: ReconState
    recon_diff: Decimal
    row_mismatches: List[RowMismatch] = field(default_factory=list)


def reconcile_statement(
    formula: str,
    stmt_meta: Any,
    txns: Sequence[Any],
    *,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> ReconciliationResult:
    """Reconcile one statement.

    `formula` selects the equation: "running_balance" (savings — also runs the row-level walk and
    takes the MORE SEVERE of the two, since a statement can net to zero while two row errors cancel),
    "card_dues" (HDFC card), or "prev_plus_purch" (ICICI card; cards print no running balance, so no
    row walk). `stmt_meta` is duck-typed — a `models.Statement` or anything exposing the same
    attributes — this function is the only place that reads them; result.py/statement_eq.py/
    row_balance.py stay pure on primitives.
    """
    if formula == "running_balance":
        opening: Decimal = stmt_meta.opening_balance
        closing: Decimal = stmt_meta.closing_balance
        signed_sum = sum((t.amount for t in txns), Decimal("0"))

        diff = running_balance_diff(opening, closing, signed_sum)
        statement_state = classify(diff, tolerance)

        row_result = walk(opening, txns)
        row_state = ReconState.RECONCILED if not row_result.mismatches else ReconState.UNRECONCILED

        return ReconciliationResult(
            recon_status=_more_severe(statement_state, row_state),
            recon_diff=diff,
            row_mismatches=row_result.mismatches,
        )

    if formula == "card_dues":
        diff = card_dues_diff(
            previous_dues=stmt_meta.previous_dues,
            total_payments=stmt_meta.total_payments,
            total_purchases=stmt_meta.total_purchases,
            finance_charges=stmt_meta.finance_charges,
            total_due=stmt_meta.total_due,
        )
        return ReconciliationResult(recon_status=classify(diff, tolerance), recon_diff=diff)

    if formula == "prev_plus_purch":
        diff = prev_plus_purch_diff(
            previous_dues=stmt_meta.previous_dues,
            total_purchases=stmt_meta.total_purchases,
            total_payments=stmt_meta.total_payments,
            total_due=stmt_meta.total_due,
            cash_advances=getattr(stmt_meta, "cash_advances", Decimal("0")),
        )
        return ReconciliationResult(recon_status=classify(diff, tolerance), recon_diff=diff)

    raise ValueError(f"unknown reconciliation formula: {formula!r}")
