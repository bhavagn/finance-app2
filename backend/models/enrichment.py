"""The mutable enrichment overlay — mirrors `transaction_enrichment`.

Keyed by `fingerprint` (scoped to `account_id`), NOT `transaction.id`, so re-parsing a statement
never orphans a user's categories/corrections.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .enums import BucketKind, EnrichSource, PayMethod


class TransactionEnrichment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: Optional[UUID] = None
    user_id: UUID
    account_id: UUID
    fingerprint: str

    merchant_id: Optional[int] = None
    category_id: Optional[int] = None
    bucket: Optional[BucketKind] = None
    payment_method: Optional[PayMethod] = None

    confidence: Optional[Decimal] = Field(default=None, max_digits=4, decimal_places=3)
    source: EnrichSource = EnrichSource.NONE
    rule_id: Optional[int] = None

    is_forex: bool = False
    is_refund: bool = False
    transfer_id: Optional[UUID] = None
    emi_loan_id: Optional[UUID] = None

    notes: Optional[str] = None
    updated_by: Optional[EnrichSource] = None
    updated_at: Optional[datetime] = None
