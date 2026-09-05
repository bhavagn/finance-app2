"""Transaction-level running-balance walk — only valid for formats that print a per-row balance
(i.e. savings; cards print no running balance and skip this entirely).

This is the sign/parse-bug detector (finance-app-spec.md §5: transaction-level reconciliation
catches sign/parse bugs a statement-level total can't, e.g. two errors that cancel out). Kept at
zero tolerance by default — strictness here is the whole point.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, List, Tuple

ZERO_TOLERANCE = Decimal("0.00")


@dataclass
class RowMismatch:
    txn: Any
    expected_balance: Decimal
    printed_balance: Decimal


@dataclass
class WalkResult:
    final_balance: Decimal
    mismatches: List[RowMismatch]


def walk(opening: Decimal, txns, per_row_tol: Decimal = ZERO_TOLERANCE) -> WalkResult:
    """Replay the running balance through `txns` (in statement order), flagging any row whose
    printed balance_after doesn't match opening + cumulative signed amount, within `per_row_tol`.
    """
    running = opening
    mismatches: List[RowMismatch] = []
    for txn in txns:
        running += txn.amount
        if txn.balance_after is not None and abs(running - txn.balance_after) > per_row_tol:
            mismatches.append(RowMismatch(txn=txn, expected_balance=running, printed_balance=txn.balance_after))
    return WalkResult(final_balance=running, mismatches=mismatches)
