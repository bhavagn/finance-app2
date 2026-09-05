"""Amount parsing: Indian digit grouping (1,23,456.78) → Decimal, plus the signed-amount convention.

Money is always Decimal, never float. Sign convention: amount < 0 = money out, > 0 = money in.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from models.enums import TxnDirection

from . import text_clean

_TRAILING_DRCR_RE = re.compile(r"\s*(dr|cr)\.?$", re.IGNORECASE)
_TWO_DP = Decimal("0.01")


def parse_indian_amount(text: str) -> Decimal:
    """Parse an Indian-grouped amount string (e.g. "1,23,456.78" or "₹59,828.38") into a Decimal.

    Grouping commas are simply stripped — Decimal doesn't need to understand the 2-3-3 grouping,
    just that they aren't part of the number.
    """
    if text is None:
        raise ValueError("amount text is None")
    cleaned = text_clean.strip_currency_glyph(text)
    cleaned = _TRAILING_DRCR_RE.sub("", cleaned)
    cleaned = cleaned.replace(",", "").strip()
    if not cleaned or cleaned in ("-", "."):
        raise ValueError(f"unparsable amount: {text!r}")
    try:
        return Decimal(cleaned).quantize(_TWO_DP)
    except InvalidOperation as exc:
        raise ValueError(f"unparsable amount: {text!r}") from exc


def signed_amount(magnitude: Decimal, direction: TxnDirection) -> Decimal:
    """Apply the sign convention: DEBIT (money out) < 0, CREDIT (money in) > 0."""
    magnitude = magnitude.copy_abs()
    return -magnitude if direction is TxnDirection.DEBIT else magnitude
