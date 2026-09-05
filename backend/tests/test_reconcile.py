"""Unit tests for reconcile/ — synthetic only, no PDF, no DB.

Pins down the tri-state classifier, the three statement equations, the row-level walk, and the
composition rule in reconcile_statement (statement-level diff and row-level walk can disagree —
the more severe one wins).
"""
from decimal import Decimal
from types import SimpleNamespace

from models.enums import ReconState
from reconcile import (
    card_dues_diff,
    classify,
    prev_plus_purch_diff,
    reconcile_statement,
    running_balance_diff,
    walk,
)


def _txn(amount: str, balance_after: str):
    return SimpleNamespace(amount=Decimal(amount), balance_after=Decimal(balance_after))


# --- classify -----------------------------------------------------------------------------------


def test_classify_exact_zero_is_reconciled():
    assert classify(Decimal("0")) == ReconState.RECONCILED


def test_classify_small_diff_is_warning():
    assert classify(Decimal("0.38")) == ReconState.RECONCILED_WITH_WARNING


def test_classify_large_diff_is_unreconciled():
    assert classify(Decimal("500")) == ReconState.UNRECONCILED


def test_classify_boundary_at_tolerance_is_warning():
    assert classify(Decimal("1.00")) == ReconState.RECONCILED_WITH_WARNING


def test_classify_just_past_boundary_is_unreconciled():
    assert classify(Decimal("1.01")) == ReconState.UNRECONCILED


def test_classify_negative_diff_uses_magnitude():
    assert classify(Decimal("-0.38")) == ReconState.RECONCILED_WITH_WARNING
    assert classify(Decimal("-500")) == ReconState.UNRECONCILED


# --- statement_eq ---------------------------------------------------------------------------------


def test_card_dues_diff_millennia_shaped_038_miss_is_a_warning():
    # Modeled on finance-app-spec.md §8: HDFC Millennia ••9670, recon diff ₹0.38 (GST billed next cycle).
    diff = card_dues_diff(
        previous_dues=Decimal("0.00"),
        total_payments=Decimal("0.00"),
        total_purchases=Decimal("52368.42"),
        finance_charges=Decimal("0.76"),
        total_due=Decimal("52368.80"),
    )
    assert diff == Decimal("0.38")
    assert classify(diff) == ReconState.RECONCILED_WITH_WARNING


def test_prev_plus_purch_diff_closes_exactly():
    # Modeled on finance-app-spec.md §8: ICICI Amazon Pay ••2004, total due ₹6,663.26, exact.
    diff = prev_plus_purch_diff(
        previous_dues=Decimal("2000.00"),
        total_purchases=Decimal("5663.26"),
        total_payments=Decimal("1000.00"),
        total_due=Decimal("6663.26"),
    )
    assert diff == Decimal("0")
    assert classify(diff) == ReconState.RECONCILED


def test_prev_plus_purch_diff_with_nonzero_cash_advances():
    diff = prev_plus_purch_diff(
        previous_dues=Decimal("2000.00"),
        total_purchases=Decimal("5000.00"),
        total_payments=Decimal("1000.00"),
        total_due=Decimal("6663.26"),
        cash_advances=Decimal("663.26"),
    )
    assert diff == Decimal("0")


def test_running_balance_diff_sign_indicates_direction_of_miss():
    # computed - printed_target: closing printed too high -> negative diff.
    assert running_balance_diff(Decimal("100"), Decimal("160"), Decimal("50")) == Decimal("-10")
    assert running_balance_diff(Decimal("100"), Decimal("140"), Decimal("50")) == Decimal("10")
    assert running_balance_diff(Decimal("100"), Decimal("150"), Decimal("50")) == Decimal("0")


# --- row_balance ----------------------------------------------------------------------------------


def test_row_balance_walk_happy_path_has_no_mismatches():
    txns = [_txn("-100.00", "900.00"), _txn("200.00", "1100.00"), _txn("-50.00", "1050.00")]
    result = walk(Decimal("1000.00"), txns)
    assert result.final_balance == Decimal("1050.00")
    assert result.mismatches == []


def test_row_balance_walk_flags_a_mismatch():
    txns = [_txn("-100.00", "850.00")]  # true running is 900.00, printed says 850.00
    result = walk(Decimal("1000.00"), txns)
    assert result.final_balance == Decimal("900.00")
    assert len(result.mismatches) == 1
    mismatch = result.mismatches[0]
    assert mismatch.expected_balance == Decimal("900.00")
    assert mismatch.printed_balance == Decimal("850.00")


# --- reconcile_statement ----------------------------------------------------------------------------


def test_reconcile_statement_running_balance_happy_path():
    txns = [_txn("-100.00", "900.00"), _txn("200.00", "1100.00"), _txn("-50.00", "1050.00")]
    stmt_meta = SimpleNamespace(opening_balance=Decimal("1000.00"), closing_balance=Decimal("1050.00"))

    result = reconcile_statement("running_balance", stmt_meta, txns)

    assert result.recon_status == ReconState.RECONCILED
    assert result.recon_diff == Decimal("0")
    assert result.row_mismatches == []


def test_reconcile_statement_row_walk_overrides_a_clean_equation():
    """The important one: statement-level nets to zero, but two rows' balance_after are wrong in
    canceling directions (+50 then -50) - the row walk must still fail the statement.
    """
    txns = [
        _txn("-100.00", "950.00"),   # true running 900.00, printed 950.00 -> off by +50
        _txn("200.00", "1050.00"),   # true running 1100.00, printed 1050.00 -> off by -50 (cancels)
        _txn("-50.00", "1050.00"),   # true running 1050.00, printed matches
    ]
    # opening + signed_sum == closing exactly: 1000 + (-100+200-50) == 1050
    stmt_meta = SimpleNamespace(opening_balance=Decimal("1000.00"), closing_balance=Decimal("1050.00"))

    result = reconcile_statement("running_balance", stmt_meta, txns)

    assert result.recon_diff == Decimal("0")  # the statement-level equation alone looks clean
    assert len(result.row_mismatches) == 2  # but the row walk isn't fooled
    assert result.recon_status == ReconState.UNRECONCILED  # more severe wins


def test_reconcile_statement_card_dues():
    stmt_meta = SimpleNamespace(
        previous_dues=Decimal("0.00"),
        total_payments=Decimal("0.00"),
        total_purchases=Decimal("52368.42"),
        finance_charges=Decimal("0.76"),
        total_due=Decimal("52368.80"),
    )
    result = reconcile_statement("card_dues", stmt_meta, [])
    assert result.recon_status == ReconState.RECONCILED_WITH_WARNING
    assert result.recon_diff == Decimal("0.38")
    assert result.row_mismatches == []


def test_reconcile_statement_prev_plus_purch():
    stmt_meta = SimpleNamespace(
        previous_dues=Decimal("2000.00"),
        total_purchases=Decimal("5663.26"),
        total_payments=Decimal("1000.00"),
        total_due=Decimal("6663.26"),
    )
    result = reconcile_statement("prev_plus_purch", stmt_meta, [])
    assert result.recon_status == ReconState.RECONCILED
    assert result.recon_diff == Decimal("0")
