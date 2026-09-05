"""Statement date parsing: dd/mm/yy and dd/mm/yyyy → date (ISO 8601 via date.isoformat())."""
from __future__ import annotations

import re
from datetime import date

_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")


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
