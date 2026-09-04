"""Enums mirroring the Postgres enum types used by transactions and transaction_enrichment."""
from __future__ import annotations

from enum import Enum


class TxnDirection(str, Enum):
    """Mirrors `txn_direction`. Must agree with the sign of `Transaction.amount`."""

    DEBIT = "debit"
    CREDIT = "credit"


class BucketKind(str, Enum):
    """Mirrors `bucket_kind` — the top-level economic bucket a transaction rolls up to."""

    SPEND = "spend"
    INCOME = "income"
    TRANSFER = "transfer"
    INVEST = "invest"
    EMI_REPAYMENT = "emi_repayment"
    ADJUSTMENT = "adjustment"
    FEE = "fee"


class PayMethod(str, Enum):
    """Mirrors `pay_method`. Orthogonal to category/bucket (a method, not a category)."""

    UPI = "upi"
    NEFT = "neft"
    IMPS = "imps"
    POS = "pos"
    ATM = "atm"
    ECS_ACH = "ecs_ach"
    EMI = "emi"
    AUTOPAY = "autopay"
    CARD = "card"
    OTHER = "other"


class EnrichSource(str, Enum):
    """Mirrors `enrich_source` — who last set an enrichment field, per the categorisation cascade."""

    RULE = "rule"
    MEMORY = "memory"
    MANUAL = "manual"
    MODEL = "model"
    ISSUER_HINT = "issuer_hint"
    NONE = "none"


class StatementKind(str, Enum):
    """Mirrors `statement_kind` — an account's statement type (parsers are keyed on issuer + this)."""

    SAVINGS = "savings"
    CURRENT = "current"
    CREDIT_CARD = "credit_card"


class StatementStatus(str, Enum):
    """Mirrors `stmt_status` — the pipeline state machine driven by pipeline.py."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    NEEDS_REVIEW = "needs_review"
    RECONCILED = "reconciled"
    ENRICHED = "enriched"
    FAILED = "failed"


class ReconState(str, Enum):
    """Mirrors `recon_state` — the tri-state reconciliation gate (±tolerance band, not hard binary)."""

    RECONCILED = "reconciled"
    RECONCILED_WITH_WARNING = "reconciled_with_warning"
    UNRECONCILED = "unreconciled"
