"""Detect (issuer, statement_type) from a statement's raw page text.

Parsers are keyed on (issuer, statement_type) — not per card — so this decides which template
(e.g. hdfc_savings) should parse the document, before any coordinate-based extraction runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models.enums import StatementKind
from normalize.text_clean import clean_text

_HDFC_COLUMN_HEADERS = ("DATE", "NARRATION", "WITHDRAWAL", "DEPOSIT", "CLOSING BALANCE")


@dataclass(frozen=True)
class IssuerStatementType:
    issuer_id: str
    statement_type: StatementKind


def detect(page_text: str) -> Optional[IssuerStatementType]:
    """Return the detected (issuer, statement_type), or None if unrecognised.

    `page_text` should be the raw extracted text of (at least) the first page — cleaned here via
    normalize.text_clean so doubled-letter header glitches (e.g. "SSTTAATTEEMMEENNTT") don't hide
    the markers we're looking for.
    """
    upper = clean_text(page_text).upper()

    if "HDFC BANK" in upper and "STATEMENT OF ACCOUNT" in upper:
        if all(header in upper for header in _HDFC_COLUMN_HEADERS):
            return IssuerStatementType(issuer_id="hdfc", statement_type=StatementKind.SAVINGS)

    return None
