"""Unit tests for parser.statement_meta.extract_card_dues_meta — synthetic label text, no PDF.

The label wording matched here (e.g. "Previous Balance", "Payment/Credits") is a best-effort
guess, unverified against a real HDFC card statement — see the UNVERIFIED note in
parser/templates/hdfc_cc.py. These tests confirm the regex mechanics work correctly against
representative text; the actual label wording may need adjustment once a real fixture is checked.
"""
from datetime import date
from decimal import Decimal

from parser.statement_meta import extract_card_dues_meta

_SYNTHETIC_SUMMARY = """
HDFC Bank Millennia Credit Card Statement
Statement Date : 05/08/2026
Payment Due Date : 25/08/2026
From : 01/07/2026 To : 31/07/2026

Previous Balance         C0.00
Payment/Credits          C0.00
Purchase/Debits          C52,368.42
Finance Charges          C0.76
Total Amount Due         C52,368.80
"""


def test_extracts_all_five_dues_fields():
    meta = extract_card_dues_meta(_SYNTHETIC_SUMMARY)
    assert meta.previous_dues == Decimal("0.00")
    assert meta.total_payments == Decimal("0.00")
    assert meta.total_purchases == Decimal("52368.42")
    assert meta.finance_charges == Decimal("0.76")
    assert meta.total_due == Decimal("52368.80")


def test_extracts_dates():
    meta = extract_card_dues_meta(_SYNTHETIC_SUMMARY)
    assert meta.statement_date == date(2026, 8, 5)
    assert meta.due_date == date(2026, 8, 25)
    assert meta.period_start == date(2026, 7, 1)
    assert meta.period_end == date(2026, 7, 31)


def test_missing_fields_are_none_not_an_error():
    meta = extract_card_dues_meta("nothing relevant in this text")
    assert meta.previous_dues is None
    assert meta.total_due is None
    assert meta.statement_date is None
