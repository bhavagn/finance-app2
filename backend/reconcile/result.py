"""The tri-state reconciliation classifier — the core abstraction the rest of reconcile/ builds on.

A ±tolerance band, not a hard binary (finance-app-spec.md §4.3): a tiny miss (e.g. GST billed next
cycle) still flows onward as a warning, only a real miss blocks the pipeline.
"""
from __future__ import annotations

from decimal import Decimal

from models.enums import ReconState

DEFAULT_TOLERANCE = Decimal("1.00")


def classify(diff: Decimal, tolerance: Decimal = DEFAULT_TOLERANCE) -> ReconState:
    """Classify a signed diff (computed - printed_target) into the tri-state gate.

    Exactly zero -> reconciled. Within tolerance (inclusive) -> reconciled_with_warning.
    Beyond tolerance -> unreconciled.
    """
    d = abs(diff)
    if d == 0:
        return ReconState.RECONCILED
    if d <= tolerance:
        return ReconState.RECONCILED_WITH_WARNING
    return ReconState.UNRECONCILED
