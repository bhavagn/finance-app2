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
from normalize.dates import parse_day_month_year, parse_ddmmyy
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
# Verified against the real HDFC Millennia ••9670 fixtures (Jun/Jul/Aug 2026 statements). The
# summary box is a 5-column grid — PREVIOUS STATEMENT DUES | PAYMENTS/CREDITS RECEIVED |
# PURCHASES/DEBIT | FINANCE CHARGES | TOTAL AMOUNT DUE — and pdfplumber's plain-text extraction
# scrambles it: the labels and their values print in a different linear order than they're
# visually laid out (the "=" sign even lands textually BEFORE the total-due figure that follows
# it). A label-adjacency regex (the original approach here) matched nothing at all. Column
# position is reliable where reading order isn't, so this maps each value to its header by x0,
# from page 1's word list. Statement Date / Billing Period, by contrast, print as plain adjacent
# text ("Statement Date 13 Jul, 2026") and are read via regex on the flattened text as before.
#
# Column x0 ranges below (with margin) were measured directly on the Jul2026 fixture:
#   previous_dues ~39.7, total_payments ~155.7-171.3, total_purchases ~258.4-267.5,
#   finance_charges ~353.5-371.8, total_due ~445.9. due_date's own (separate) box: ~512.1.
# The value row sits 10-30pt below the header row; total_due's own figure sits ~7pt higher than
# the other four (it's rendered in its own highlighted box) - the top window covers both.

_CARD_AMOUNT_RE = re.compile(r"^C?[\d,]+\.\d{2}$")
_STATEMENT_DATE_TEXT_RE = re.compile(r"STATEMENT\s*DATE\s+(\d{1,2}\s+[A-Za-z]{3,},?\s+\d{4})", re.IGNORECASE)
_BILLING_PERIOD_RE = re.compile(
    r"BILLING\s*PERIOD\s+(\d{1,2}\s+[A-Za-z]{3,},?\s+\d{4})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,},?\s+\d{4})",
    re.IGNORECASE,
)

_DUES_BOX_COLUMNS = {
    "previous_dues": (30.0, 135.0),
    "total_payments": (150.0, 225.0),
    "total_purchases": (250.0, 325.0),
    "finance_charges": (345.0, 415.0),
    "total_due": (440.0, 515.0),
}
_DUES_BOX_TOP_RANGE = (228.0, 250.0)  # value row(s) just below the 5 column headers

_DUE_DATE_COLUMN_X0_RANGE = (505.0, 545.0)
_DUE_DATE_TOP_RANGE = (280.0, 300.0)  # separate box, below the dues equation box


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


def _words_in_band(words, top_range, x0_range=None):
    lo, hi = top_range
    band = [w for w in words if lo <= w["top"] <= hi]
    if x0_range is not None:
        x_lo, x_hi = x0_range
        band = [w for w in band if x_lo <= w["x0"] <= x_hi]
    return band


def _extract_dues_box(first_page_words) -> dict:
    """Map each of the 5 summary-box figures to its field by column (x0), not by reading order."""
    values: dict = {}
    for field, x0_range in _DUES_BOX_COLUMNS.items():
        band = _words_in_band(first_page_words, _DUES_BOX_TOP_RANGE, x0_range)
        for word in band:
            if _CARD_AMOUNT_RE.match(word["text"]):
                values[field] = parse_indian_amount(word["text"])
                break
    return values


def _extract_due_date(first_page_words) -> Optional[date]:
    band = _words_in_band(first_page_words, _DUE_DATE_TOP_RANGE, _DUE_DATE_COLUMN_X0_RANGE)
    band = sorted(band, key=lambda w: w["x0"])
    text = " ".join(w["text"] for w in band).strip()
    try:
        return parse_day_month_year(text) if text else None
    except ValueError:
        return None


def extract_card_dues_meta(full_text: str, first_page_words) -> CardDuesMeta:
    """Extract the printed aggregates the "card_dues"/"prev_plus_purch" reconcile formulas need:
    previous_dues, total_payments, total_purchases, finance_charges, total_due — plus
    period/statement_date/due_date (stored, not needed for recon).

    `first_page_words` is page 1's `page.extract_words(...)` output — the summary box needs
    coordinates, not just text (see the module note above).
    """
    cleaned = clean_text(full_text)
    dues = _extract_dues_box(first_page_words)

    statement_date_match = _STATEMENT_DATE_TEXT_RE.search(cleaned)
    period_match = _BILLING_PERIOD_RE.search(cleaned)

    return CardDuesMeta(
        previous_dues=dues.get("previous_dues"),
        total_payments=dues.get("total_payments"),
        total_purchases=dues.get("total_purchases"),
        finance_charges=dues.get("finance_charges"),
        total_due=dues.get("total_due"),
        period_start=parse_day_month_year(period_match.group(1)) if period_match else None,
        period_end=parse_day_month_year(period_match.group(2)) if period_match else None,
        statement_date=parse_day_month_year(statement_date_match.group(1)) if statement_date_match else None,
        due_date=_extract_due_date(first_page_words),
    )
