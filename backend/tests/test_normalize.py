"""Unit tests for the pure normalize/ helpers — no PDF required."""
from datetime import date
from decimal import Decimal

import pytest

from models.enums import TxnDirection
from normalize import text_clean
from normalize.amounts import parse_indian_amount, signed_amount
from normalize.dates import is_date_token, parse_ddmmyy


def test_strip_watermark():
    assert text_clean.strip_watermark("STATEMENT DUPLICATE COPY") == "STATEMENT  COPY"
    assert text_clean.strip_watermark("duplicate") == ""


def test_strip_cid_glyphs():
    assert text_clean.strip_cid_glyphs("UPI(cid:1)-SAFEGOLD") == "UPI-SAFEGOLD"


def test_collapse_doubled_letters():
    assert text_clean.collapse_doubled_letters("SSTTAATTEEMMEENNTT OOFF AACCCCOOUUNNTT") == "STATEMENT OF ACCOUNT"
    # real narration text must survive untouched
    assert text_clean.collapse_doubled_letters("UPI-SAFEGOLD@YBL") == "UPI-SAFEGOLD@YBL"


def test_strip_currency_glyph():
    assert text_clean.strip_currency_glyph("₹59,828.38") == "59,828.38"
    assert text_clean.strip_currency_glyph("C1,234.50") == "1,234.50"
    assert text_clean.strip_currency_glyph("`10,079.19") == "10,079.19"
    # a real word starting with C must survive
    assert text_clean.strip_currency_glyph("Cash") == "Cash"


def test_clean_text_pipeline():
    assert text_clean.clean_text("(cid:1)SSTTAATTEEMMEENNTT DUPLICATE") == "STATEMENT"


def test_parse_indian_amount():
    assert parse_indian_amount("59,828.38") == Decimal("59828.38")
    assert parse_indian_amount("1,23,456.78") == Decimal("123456.78")
    assert parse_indian_amount("₹10,079.19") == Decimal("10079.19")
    assert parse_indian_amount("500.00 Dr") == Decimal("500.00")


def test_parse_indian_amount_rejects_garbage():
    with pytest.raises(ValueError):
        parse_indian_amount("not-a-number")


def test_signed_amount():
    assert signed_amount(Decimal("100.00"), TxnDirection.DEBIT) == Decimal("-100.00")
    assert signed_amount(Decimal("100.00"), TxnDirection.CREDIT) == Decimal("100.00")
    # magnitude is always taken as absolute, regardless of how it was passed in
    assert signed_amount(Decimal("-100.00"), TxnDirection.CREDIT) == Decimal("100.00")


def test_parse_ddmmyy():
    assert parse_ddmmyy("05/07/26") == date(2026, 7, 5)
    assert parse_ddmmyy("05/07/2026") == date(2026, 7, 5)


def test_is_date_token():
    assert is_date_token("05/07/26") is True
    assert is_date_token("UPI-SAFEGOLD@YBL") is False
