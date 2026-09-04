"""Smoke test: the models package imports cleanly and a canonical transaction round-trips."""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from models import Transaction, TxnDirection


def test_construct_debit_transaction():
    txn = Transaction(
        statement_id=uuid4(),
        account_id=uuid4(),
        user_id=uuid4(),
        txn_date=date(2026, 8, 1),
        raw_description="UPI-SAFEGOLD@YBL-000000000000-000000000000-DR",
        bank_ref="000000000000",
        direction=TxnDirection.DEBIT,
        amount=Decimal("-1500.00"),
    )
    assert txn.amount < 0
    assert txn.currency == "INR"


def test_construct_credit_transaction():
    txn = Transaction(
        statement_id=uuid4(),
        account_id=uuid4(),
        user_id=uuid4(),
        txn_date=date(2026, 8, 2),
        raw_description="NEFT CR SALARY",
        direction=TxnDirection.CREDIT,
        amount=Decimal("50000.00"),
    )
    assert txn.amount > 0


def test_direction_amount_sign_mismatch_rejected():
    with pytest.raises(ValidationError):
        Transaction(
            statement_id=uuid4(),
            account_id=uuid4(),
            user_id=uuid4(),
            txn_date=date(2026, 8, 1),
            raw_description="bad sign",
            direction=TxnDirection.DEBIT,
            amount=Decimal("100.00"),
        )
