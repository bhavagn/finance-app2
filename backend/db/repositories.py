"""Typed insert/upsert helpers for the tables the pipeline writes to.

All writes go through the service-role client (client.py) and therefore bypass RLS — every helper
here sets `user_id` explicitly rather than relying on `auth.uid()`. This module only performs writes;
it does not decide *whether* a status transition is legal — that state-machine logic lives in
pipeline.py, per the module boundaries in finance-app-spec.md §6 ("logic stays out of the DB").
"""
from __future__ import annotations

from typing import Any, Optional, Sequence
from uuid import UUID

from models import Account, ReconState, Statement, StatementStatus, Transaction, TransactionEnrichment

from .client import get_service_client


def _payload(model: Any, *, exclude: Optional[set[str]] = None) -> dict:
    return model.model_dump(mode="json", exclude_none=True, exclude=exclude or set())


def upsert_account(account: Account) -> dict:
    """Insert an account, or return the existing row on (user_id, issuer_id, statement_type, last4) conflict."""
    payload = _payload(account, exclude={"id"})
    resp = (
        get_service_client()
        .table("accounts")
        .upsert(payload, on_conflict="user_id,issuer_id,statement_type,last4")
        .execute()
    )
    return resp.data[0]


def upsert_statement(statement: Statement) -> dict:
    """Insert a statement, or return the existing row on (account_id, file_hash) conflict — the re-upload dedup."""
    payload = _payload(statement, exclude={"id"})
    resp = (
        get_service_client()
        .table("statements")
        .upsert(payload, on_conflict="account_id,file_hash")
        .execute()
    )
    return resp.data[0]


def set_statement_status(
    statement_id: UUID,
    status: StatementStatus,
    *,
    recon_status: Optional[ReconState] = None,
    recon_diff: Optional[Any] = None,
    parse_completeness: Optional[Any] = None,
) -> dict:
    """Move a statement to a new pipeline status, optionally recording reconciliation results alongside it."""
    update: dict = {"status": status.value}
    if recon_status is not None:
        update["recon_status"] = recon_status.value
    if recon_diff is not None:
        update["recon_diff"] = str(recon_diff)
    if parse_completeness is not None:
        update["parse_completeness"] = str(parse_completeness)

    resp = (
        get_service_client()
        .table("statements")
        .update(update)
        .eq("id", str(statement_id))
        .execute()
    )
    return resp.data[0]


def insert_transactions(transactions: Sequence[Transaction]) -> list[dict]:
    """Bulk-insert immutable parsed transactions.

    Never updates an existing row: re-parsing the same statement relies on the DB's
    (account_id, fingerprint) unique constraint to silently dedupe instead.
    """
    if not transactions:
        return []
    payload = [_payload(txn, exclude={"id"}) for txn in transactions]
    resp = get_service_client().table("transactions").insert(payload).execute()
    return resp.data


def upsert_transaction_enrichment(enrichment: TransactionEnrichment) -> dict:
    """Insert/update the mutable enrichment overlay, keyed by (account_id, fingerprint) — never by
    transaction id — so re-parsing a statement never orphans a user's categories/corrections.
    """
    payload = _payload(enrichment, exclude={"id"})
    resp = (
        get_service_client()
        .table("transaction_enrichment")
        .upsert(payload, on_conflict="account_id,fingerprint")
        .execute()
    )
    return resp.data[0]
