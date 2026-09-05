"""Statement date parsing: dd/mm/yy(yy) → date, plus the "DD Mon, YYYY" form HDFC card statements
print for Statement Date / Billing Period / Due Date (e.g. "13 Jul, 2026").
"""
from __future__ import annotations

import re
from datetime import date

_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")
_MONTH_ABBREVIATIONS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DAY_MONTH_YEAR_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,})[.,]?\s+(\d{4})$")


def parse_ddmmyy(text: str) -> date:
    """Parse a "dd/mm/yy" or "dd/mm/yyyy" token into a `date`. A 2-digit year is read as 20YY."""
    match = _DATE_RE.match(text.strip())
    if not match:
        raise ValueError(f"unrecognised date format: {text!r}")
    day, month, year = match.groups()
    year_int = 2000 + int(year) if len(year) == 2 else int(year)
    return date(year_int, int(month), int(day))


def is_date_token(text: str) -> bool:
    """True if `text` looks like a dd/mm/yy(yy) date token — used to spot anchor lines."""
    return bool(_DATE_RE.match(text.strip()))


def parse_day_month_year(text: str) -> date:
    """Parse a "13 Jul, 2026" / "13 Jul 2026" token into a `date` (HDFC card statement dates)."""
    match = _DAY_MONTH_YEAR_RE.match(text.strip())
    if not match:
        raise ValueError(f"unrecognised date format: {text!r}")
    day, month_name, year = match.groups()
    month = _MONTH_ABBREVIATIONS.get(month_name[:3].lower())
    if month is None:
        raise ValueError(f"unrecognised month name: {month_name!r}")
    return date(int(year), month, int(day))
