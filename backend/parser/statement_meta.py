"""Statement-level metadata: the From/To period, and opening/closing balance.

HDFC savings statements don't always print an explicit opening balance; when they don't, it's
derived from the first transaction row: opening = first_row.balance_after -/+ its signed amount.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Tuple

from normalize.amounts import parse_indian_amount
from normalize.dates import parse_ddmmyy
from normalize.text_clean import clean_text

if TYPE_CHECKING:
    from models import Transaction

_PERIOD_RE = re.compile(
    r"FROM\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4}).{0,20}?TO\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})",
    re.IGNORECASE | re.DOTALL,
)
_OPENING_LABEL_RE = re.compile(r"OPENING\s*BALANCE\s*[:\-]?\s*([\d,]+\.\d{2})", re.IGNORECASE)
_CLOSING_LABEL_RE = re.compile(r"CLOSING\s*BALANCE\s*[:\-]?\s*([\d,]+\.\d{2})", re.IGNORECASE)


def extract_period(full_text: str) -> Optional[Tuple[date, date]]:
    """Extract the statement's (period_start, period_end) from a "From : dd/mm/yy To : dd/mm/yy" label."""
    match = _PERIOD_RE.search(clean_text(full_text))
    if not match:
        return None
    return parse_ddmmyy(match.group(1)), parse_ddmmyy(match.group(2))


def extract_printed_opening_balance(full_text: str) -> Optional[Decimal]:
    """Extract an explicitly printed "Opening Balance : <amount>" figure, if the statement has one."""
    match = _OPENING_LABEL_RE.search(clean_text(full_text))
    return parse_indian_amount(match.group(1)) if match else None


def extract_printed_closing_balance(full_text: str) -> Optional[Decimal]:
    """Extract an explicitly printed "Closing Balance : <amount>" figure, if the statement has one."""
    match = _CLOSING_LABEL_RE.search(clean_text(full_text))
    return parse_indian_amount(match.group(1)) if match else None


def derive_opening_balance(full_text: str, first_txn: Optional["Transaction"]) -> Optional[Decimal]:
    """Printed opening balance if present, else derived from the first row: balance_after - signed amount."""
    printed = extract_printed_opening_balance(full_text)
    if printed is not None:
        return printed
    if first_txn is None or first_txn.balance_after is None:
        return None
    return (first_txn.balance_after - first_txn.amount).quantize(Decimal("0.01"))


def derive_closing_balance(full_text: str, last_txn: Optional["Transaction"]) -> Optional[Decimal]:
    """Printed closing balance if present, else the last row's running balance."""
    printed = extract_printed_closing_balance(full_text)
    if printed is not None:
        return printed
    if last_txn is None:
        return None
    return last_txn.balance_after
