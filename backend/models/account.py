"""Mirrors `accounts` — a (product_name + last4) instance owned by a user, under one issuer."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .enums import StatementKind


class Account(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: Optional[UUID] = None
    user_id: UUID
    issuer_id: str
    statement_type: StatementKind
    product_name: Optional[str] = None
    last4: str

    billing_cycle_day: Optional[int] = None
    credit_limit: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    cash_limit: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
