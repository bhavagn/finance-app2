"""The canonical transaction — the contract the whole pipeline passes rows through as.

Mirrors the immutable `transactions` table exactly, minus `fingerprint` (a DB-generated column;
never set it from Python) and `created_at` (DB-assigned).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import TxnDirection


class Transaction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: Optional[UUID] = None
    statement_id: UUID
    account_id: UUID
    user_id: UUID

    txn_date: date
    posting_date: Optional[date] = None
    value_date: Optional[date] = None

    raw_description: str
    bank_ref: Optional[str] = None

    direction: TxnDirection
    # Sign convention: amount < 0 = money out, > 0 = money in. Never float.
    amount: Decimal = Field(max_digits=14, decimal_places=2)
    currency: str = "INR"

    balance_after: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    source_page: Optional[int] = None
    source_row: Optional[int] = None

    @model_validator(mode="after")
    def _amount_sign_matches_direction(self) -> "Transaction":
        if self.direction is TxnDirection.DEBIT and self.amount >= 0:
            raise ValueError("debit transactions must have amount < 0 (money out)")
        if self.direction is TxnDirection.CREDIT and self.amount <= 0:
            raise ValueError("credit transactions must have amount > 0 (money in)")
        return self
