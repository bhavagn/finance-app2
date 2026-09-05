"""Unit tests for parser.statement_meta.extract_card_dues_meta — synthetic, no PDF.

The summary box's plain-text reading order is scrambled relative to its visual layout (confirmed
on the real Millennia fixtures — see the module docstring in parser/statement_meta.py), so
extraction is coordinate-based. These synthetic word positions mirror the ones measured directly
on the Jul2026 fixture's page 1.
"""
from datetime import date
from decimal import Decimal

from parser.statement_meta import extract_card_dues_meta

_STATEMENT_TEXT = """
Statement Date 13 Jul, 2026
Billing Period 14 Jun, 2026 - 13 Jul, 2026
"""


def _word(text: str, x0: float, top: float, width: float = 30.0) -> dict:
    return {"text": text, "x0": x0, "x1": x0 + width, "top": top}


_DUES_BOX_WORDS = [
    _word("C10,050.66", 63.5, 242.2),   # previous_dues column
    _word("C10,170.09", 167.2, 242.2),  # total_payments column
    _word("C16,839.79", 267.5, 242.2),  # total_purchases column
    _word("C0.00", 371.8, 242.2),       # finance_charges column
    _word("C16,720.00", 445.9, 235.2),  # total_due — its own box, ~7pt higher
]
_DUE_DATE_WORDS = [
    _word("02", 512.1, 289.7, width=8.0),
    _word("Aug,", 522.0, 289.7, width=15.0),
    _word("2026", 538.8, 289.7, width=17.0),
]


def test_extracts_all_five_dues_fields_by_column_position():
    meta = extract_card_dues_meta(_STATEMENT_TEXT, _DUES_BOX_WORDS + _DUE_DATE_WORDS)
    assert meta.previous_dues == Decimal("10050.66")
    assert meta.total_payments == Decimal("10170.09")
    assert meta.total_purchases == Decimal("16839.79")
    assert meta.finance_charges == Decimal("0.00")
    assert meta.total_due == Decimal("16720.00")


def test_extracts_statement_date_and_period_from_text():
    meta = extract_card_dues_meta(_STATEMENT_TEXT, [])
    assert meta.statement_date == date(2026, 7, 13)
    assert meta.period_start == date(2026, 6, 14)
    assert meta.period_end == date(2026, 7, 13)


def test_extracts_due_date_by_column_position():
    meta = extract_card_dues_meta(_STATEMENT_TEXT, _DUE_DATE_WORDS)
    assert meta.due_date == date(2026, 8, 2)


def test_missing_fields_are_none_not_an_error():
    meta = extract_card_dues_meta("nothing relevant in this text", [])
    assert meta.previous_dues is None
    assert meta.total_due is None
    assert meta.statement_date is None
    assert meta.due_date is None


def test_a_value_outside_every_column_range_is_not_assigned():
    stray = [_word("C999.99", 999.0, 242.2)]  # far outside any known column
    meta = extract_card_dues_meta(_STATEMENT_TEXT, stray)
    assert meta.previous_dues is None
    assert meta.total_due is None
