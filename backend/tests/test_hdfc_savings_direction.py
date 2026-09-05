"""Synthetic unit tests for direction resolution — no PDF needed.

Exercises parser.templates.hdfc_savings._resolve_direction directly, confirming the running-balance
delta is the source of truth and column position is only a fallback/cross-check (see finance-app-spec.md
§5: transaction-level reconciliation is what catches sign/parse bugs a column-position guess can't).
"""
from decimal import Decimal

from models.enums import TxnDirection
from parser.templates.hdfc_savings import _Word, _classify_by_column, _resolve_direction

# Sits squarely in the deposit column range (DEPOSIT_X1_RANGE = (530, 565)) — column position
# alone would call any amount at this x1 a CREDIT.
_DEPOSIT_COLUMN_WORD = _Word(text="500.00", x0=520.0, x1=548.2, top=100.0)
# Sits squarely in the withdrawal column range (WITHDRAWAL_X1_RANGE = (455, 485)).
_WITHDRAWAL_COLUMN_WORD = _Word(text="500.00", x0=440.0, x1=470.2, top=100.0)


def test_delta_overrides_a_misleading_column_position():
    """A real debit whose amount happens to sit at a deposit-column x1 must still resolve as DEBIT."""
    assert _classify_by_column(_DEPOSIT_COLUMN_WORD) is TxnDirection.CREDIT

    magnitude = Decimal("500.00")
    prev_balance = Decimal("10000.00")
    balance_after = Decimal("9500.00")  # balance dropped by exactly `magnitude` -> a real debit

    direction = _resolve_direction(magnitude, balance_after, prev_balance, _DEPOSIT_COLUMN_WORD)
    assert direction is TxnDirection.DEBIT


def test_delta_confirms_a_correctly_positioned_credit():
    magnitude = Decimal("500.00")
    prev_balance = Decimal("10000.00")
    balance_after = Decimal("10500.00")  # balance rose by exactly `magnitude` -> a real credit

    direction = _resolve_direction(magnitude, balance_after, prev_balance, _DEPOSIT_COLUMN_WORD)
    assert direction is TxnDirection.CREDIT


def test_falls_back_to_column_when_delta_does_not_confirm():
    # Balance moved by something other than the parsed magnitude - the delta can't confirm this
    # row, so column position (deposit, in this case) is used instead.
    magnitude = Decimal("500.00")
    prev_balance = Decimal("10000.00")
    balance_after = Decimal("10050.00")  # moved by 50, not 500

    direction = _resolve_direction(magnitude, balance_after, prev_balance, _DEPOSIT_COLUMN_WORD)
    assert direction is TxnDirection.CREDIT


def test_row_one_with_no_opening_balance_falls_back_to_column():
    magnitude = Decimal("500.00")
    direction = _resolve_direction(magnitude, Decimal("9500.00"), None, _WITHDRAWAL_COLUMN_WORD)
    assert direction is TxnDirection.DEBIT


def test_row_one_with_no_opening_balance_and_no_column_match_defaults_to_debit():
    magnitude = Decimal("500.00")
    unclassifiable_word = _Word(text="500.00", x0=200.0, x1=210.0, top=100.0)  # nowhere near either column
    direction = _resolve_direction(magnitude, Decimal("9500.00"), None, unclassifiable_word)
    assert direction is TxnDirection.DEBIT
