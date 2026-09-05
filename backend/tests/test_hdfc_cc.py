"""Tests for the HDFC credit-card (Millennia) parser.

The golden section (against the real fixture) is skipped when the fixture PDF isn't present on
disk — it's gitignored real bank data, same as the savings fixture. The direction/normalisation
unit tests below it need no PDF and always run.

Validated reference numbers (finance-app-spec.md §8): HDFC Millennia ••9670 — total due ₹52,368.80,
recon diff ₹0.38 (within tolerance — GST billed next cycle), 2 EMI loans.
"""
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest

from models.enums import ReconState, TxnDirection
from normalize.amounts import signed_amount
from parser.statement_meta import extract_card_dues_meta
from parser.templates.hdfc_cc import _AMOUNT_CANDIDATE_RE, _Word, _split_amount_cell, parse
from reconcile import reconcile_statement

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_MATCHES = sorted(_FIXTURES_DIR.glob("*9670*.pdf")) or sorted(_FIXTURES_DIR.glob("*[Mm]illennia*.pdf"))
FIXTURE = _MATCHES[0] if _MATCHES else _FIXTURES_DIR / "hdfc_cc_millennia_9670.pdf"

EXPECTED_TOTAL_DUE = Decimal("52368.80")
EXPECTED_RECON_DIFF_MAGNITUDE = Decimal("0.38")


# --- golden fixture (skipped without the real PDF) -----------------------------------------------


@pytest.mark.skipif(
    not FIXTURE.exists(),
    reason=f"golden fixture not present: {FIXTURE} (gitignored real statement PDF)",
)
class TestMillenniaGolden:
    @pytest.fixture(scope="class")
    def transactions(self):
        return parse(FIXTURE)

    @pytest.fixture(scope="class")
    def stmt_meta(self):
        with pdfplumber.open(str(FIXTURE)) as pdf:
            full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        return extract_card_dues_meta(full_text)

    def test_total_due_parsed(self, stmt_meta):
        assert stmt_meta.total_due == EXPECTED_TOTAL_DUE, (
            f"expected total_due {EXPECTED_TOTAL_DUE}, got {stmt_meta.total_due}"
        )

    def test_reconciles_with_warning_at_038(self, transactions, stmt_meta):
        result = reconcile_statement("card_dues", stmt_meta, transactions, tolerance=Decimal("1.00"))
        assert result.recon_status == ReconState.RECONCILED_WITH_WARNING, (
            f"expected reconciled_with_warning, got {result.recon_status} (diff {result.recon_diff})"
        )
        assert abs(result.recon_diff).quantize(Decimal("0.01")) == EXPECTED_RECON_DIFF_MAGNITUDE, (
            f"expected |diff| {EXPECTED_RECON_DIFF_MAGNITUDE}, got {abs(result.recon_diff)}"
        )

    def test_report_counts(self, transactions):
        # Deliberately not hard-asserted: unverified until confirmed against the real PDF.
        debit_count = sum(1 for t in transactions if t.direction is TxnDirection.DEBIT)
        credit_count = sum(1 for t in transactions if t.direction is TxnDirection.CREDIT)
        print(
            f"\n[hdfc_cc golden] total txns={len(transactions)} "
            f"debit={debit_count} credit={credit_count}"
        )


# --- direction / normalisation unit tests (no PDF needed) -----------------------------------------


def test_merchant_name_containing_cr_letters_resolves_debit():
    """The exact bug class named in the task: "SUBSCRIPTION" contains the letters "cr" as a
    substring. A naive `"cr" in full_line` check would wrongly flag this as a credit; scoping
    detection to the amount token alone must not.
    """
    line_words = [
        _Word(text="15/07/2026", x0=30.0, x1=90.0, top=100.0),
        _Word(text="SUBSCRIPTION", x0=100.0, x1=200.0, top=100.0),
        _Word(text="500.00", x0=450.0, x1=480.0, top=100.0),
    ]
    amount_candidates = [(i, w) for i, w in enumerate(line_words) if _AMOUNT_CANDIDATE_RE.match(w.text)]
    assert len(amount_candidates) == 1
    amount_index, amount_word = amount_candidates[0]
    next_word = line_words[amount_index + 1] if amount_index + 1 < len(line_words) else None

    magnitude, direction = _split_amount_cell(amount_word, next_word)

    assert direction is TxnDirection.DEBIT
    assert magnitude == Decimal("500.00")
    assert signed_amount(magnitude, direction) == Decimal("-500.00")


def test_leading_c_currency_glyph_is_stripped():
    amount_word = _Word(text="C12,345.00", x0=450.0, x1=480.0, top=100.0)
    magnitude, direction = _split_amount_cell(amount_word, None)
    assert magnitude == Decimal("12345.00")
    assert direction is TxnDirection.DEBIT


def test_leading_c_and_separate_trailing_cr_resolve_to_positive_credit():
    # The task's own example shape: "C1,000.00 Cr" as two separate words on the line.
    amount_word = _Word(text="C1,000.00", x0=450.0, x1=480.0, top=100.0)
    next_word = _Word(text="Cr", x0=485.0, x1=495.0, top=100.0)

    magnitude, direction = _split_amount_cell(amount_word, next_word)

    assert direction is TxnDirection.CREDIT
    assert magnitude == Decimal("1000.00")
    assert signed_amount(magnitude, direction) == Decimal("1000.00")


def test_leading_c_and_glued_trailing_cr_resolve_to_positive_credit():
    # The same collision, but glued into one token ("C1,000.00Cr") — this bank's PDF-export norm.
    amount_word = _Word(text="C1,000.00Cr", x0=450.0, x1=480.0, top=100.0)

    magnitude, direction = _split_amount_cell(amount_word, None)

    assert direction is TxnDirection.CREDIT
    assert magnitude == Decimal("1000.00")
    assert signed_amount(magnitude, direction) == Decimal("1000.00")
