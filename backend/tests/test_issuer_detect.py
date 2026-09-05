"""Unit tests for parser.issuer_detect — synthetic header text, no PDF required."""
from models.enums import StatementKind
from parser.issuer_detect import IssuerStatementType, detect

_HDFC_SAVINGS_HEADER = """
HDFC BANK LIMITED
Statement of account
From : 01/07/26  To : 31/07/26
Date Narration Chq/Ref No Value Dt Withdrawal Deposit Closing Balance
"""

_HDFC_SAVINGS_HEADER_WITH_GLYPH_DOUBLING = """
HHDDFFCC BBAANNKK LLIIMMIITTEEDD
SSTTAATTEEMMEENNTT OOFF AACCCCOOUUNNTT
Date Narration Chq/Ref No Value Dt Withdrawal Deposit Closing Balance
"""


def test_detects_hdfc_savings():
    assert detect(_HDFC_SAVINGS_HEADER) == IssuerStatementType(issuer_id="hdfc", statement_type=StatementKind.SAVINGS)


def test_detects_hdfc_savings_despite_doubled_letters():
    result = detect(_HDFC_SAVINGS_HEADER_WITH_GLYPH_DOUBLING)
    assert result is not None
    assert result.statement_type is StatementKind.SAVINGS


def test_returns_none_for_unrecognised_text():
    assert detect("ICICI Bank Credit Card Statement") is None
