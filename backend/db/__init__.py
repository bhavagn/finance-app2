"""Supabase access layer: service-role client (client.py) and typed repositories (repositories.py)."""
from .client import get_service_client
from .repositories import (
    insert_transactions,
    set_statement_status,
    upsert_account,
    upsert_statement,
    upsert_transaction_enrichment,
)

__all__ = [
    "get_service_client",
    "insert_transactions",
    "set_statement_status",
    "upsert_account",
    "upsert_statement",
    "upsert_transaction_enrichment",
]
