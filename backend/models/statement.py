"""Mirrors `statements` — printed totals as reconciliation ground truth, plus pipeline status."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .enums import ReconState, StatementStatus


class Statement(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: Optional[UUID] = None
    account_id: UUID
    user_id: UUID
    file_hash: str
    storage_path: str
    template_id: Optional[int] = None

    period_start: Optional[date] = None
    period_end: Optional[date] = None
    statement_date: Optional[date] = None
    due_date: Optional[date] = None

    opening_balance: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    closing_balance: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    previous_dues: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    total_purchases: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    total_payments: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    finance_charges: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    total_due: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    minimum_due: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    available_credit: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    reward_points_closing: Optional[int] = None

    status: StatementStatus = StatementStatus.UPLOADED
    recon_status: Optional[ReconState] = None
    recon_diff: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    parse_completeness: Optional[Decimal] = Field(default=None, max_digits=5, decimal_places=2)

    layout_signature: Optional[str] = None
