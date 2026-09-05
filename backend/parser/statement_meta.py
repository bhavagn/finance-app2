"""Statement-level metadata: the From/To period, and opening/closing balance.

HDFC savings statements don't always print an explicit opening balance; when they don't, it's
derived from the first transaction row: opening = first_row.balance_after -/+ its signed amount.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
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


# --- credit-card aggregates ---------------------------------------------------------------------
#
# UNVERIFIED against a real fixture: no Millennia PDF was available while writing this. The label
# wording below is a best-effort guess at common HDFC card statement phrasing (mirrors the same
# situation the savings parser's column x1 ranges were in before the real PDF arrived and several
# had to be recalibrated) — expect these to need adjustment once checked against the real PDF.

_AMOUNT_CAPTURE = r"C?[\d,]+\.\d{2}"  # optional leading "C" currency-glyph substitution (see normalize)

_PREVIOUS_DUES_RE = re.compile(
    rf"(?:OPENING|PREVIOUS)\s*(?:BALANCE|DUES?)\s*[:\-]?\s*({_AMOUNT_CAPTURE})", re.IGNORECASE
)
_TOTAL_PAYMENTS_RE = re.compile(
    rf"PAYMENTS?(?:\s*(?:/|&|AND)\s*(?:OTHER\s*)?CREDITS?)?\s*[:\-]?\s*({_AMOUNT_CAPTURE})", re.IGNORECASE
)
_TOTAL_PURCHASES_RE = re.compile(
    rf"PURCHASES?(?:\s*(?:/|&|AND)\s*(?:OTHER\s*)?DEBITS?)?\s*[:\-]?\s*({_AMOUNT_CAPTURE})", re.IGNORECASE
)
_FINANCE_CHARGES_RE = re.compile(rf"FINANCE\s*CHARGES?\s*[:\-]?\s*({_AMOUNT_CAPTURE})", re.IGNORECASE)
_TOTAL_DUE_RE = re.compile(rf"TOTAL\s*(?:AMOUNT\s*)?DUES?\s*[:\-]?\s*({_AMOUNT_CAPTURE})", re.IGNORECASE)
_STATEMENT_DATE_RE = re.compile(r"STATEMENT\s*DATE\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.IGNORECASE)
_DUE_DATE_RE = re.compile(r"(?:PAYMENT\s*)?DUE\s*DATE\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.IGNORECASE)


@dataclass
class CardDuesMeta:
    """Duck-typed stmt_meta for reconcile_statement("card_dues"/"prev_plus_purch", ...)."""

    previous_dues: Optional[Decimal] = None
    total_payments: Optional[Decimal] = None
    total_purchases: Optional[Decimal] = None
    finance_charges: Optional[Decimal] = None
    total_due: Optional[Decimal] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    statement_date: Optional[date] = None
    due_date: Optional[date] = None


def _extract_amount(full_text: str, pattern: "re.Pattern") -> Optional[Decimal]:
    match = pattern.search(full_text)
    return parse_indian_amount(match.group(1)) if match else None


def _extract_date(full_text: str, pattern: "re.Pattern") -> Optional[date]:
    match = pattern.search(full_text)
    return parse_ddmmyy(match.group(1)) if match else None


def extract_card_dues_meta(full_text: str) -> CardDuesMeta:
    """Extract the printed aggregates the "card_dues"/"prev_plus_purch" reconcile formulas need:
    previous_dues, total_payments, total_purchases, finance_charges, total_due — plus
    period/statement_date/due_date (stored, not needed for recon).
    """
    cleaned = clean_text(full_text)
    period = extract_period(cleaned)
    return CardDuesMeta(
        previous_dues=_extract_amount(cleaned, _PREVIOUS_DUES_RE),
        total_payments=_extract_amount(cleaned, _TOTAL_PAYMENTS_RE),
        total_purchases=_extract_amount(cleaned, _TOTAL_PURCHASES_RE),
        finance_charges=_extract_amount(cleaned, _FINANCE_CHARGES_RE),
        total_due=_extract_amount(cleaned, _TOTAL_DUE_RE),
        period_start=period[0] if period else None,
        period_end=period[1] if period else None,
        statement_date=_extract_date(cleaned, _STATEMENT_DATE_RE),
        due_date=_extract_date(cleaned, _DUE_DATE_RE),
    )
