"""Tests for the HDFC credit-card (Millennia) parser.

The golden section runs against every real Millennia ••9670 fixture present in tests/fixtures/
(there are three: Jun/Jul/Aug 2026 statements — none of them has a total_due matching
finance-app-spec.md §8's ₹52,368.80, so that figure is stale/from a different statement and is
NOT asserted here; see the session notes for how this was confirmed). The section is skipped
entirely when no fixture is present — they're gitignored real bank data. The direction/
normalisation unit tests below need no PDF and always run.
"""
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest

from models.enums import ReconState, TxnDirection
from normalize.amounts import signed_amount
from parser.statement_meta import extract_card_dues_meta
from parser.templates.hdfc_cc import _find_amount_cell, _Word, parse
from reconcile import reconcile_statement

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES = sorted(_FIXTURES_DIR.glob("*9670*.pdf")) or sorted(_FIXTURES_DIR.glob("*[Mm]illennia*.pdf"))


# --- golden fixtures (skipped without a real PDF) -------------------------------------------------


@pytest.mark.skipif(not FIXTURES, reason="no Millennia ••9670 fixture present (gitignored real statement PDF)")
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
class TestMillenniaGolden:
    @pytest.fixture
    def transactions(self, fixture):
        return parse(fixture)

    @pytest.fixture
    def stmt_meta(self, fixture):
        with pdfplumber.open(str(fixture)) as pdf:
            full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            first_page_words = pdf.pages[0].extract_words(keep_blank_chars=False, use_text_flow=False)
        return extract_card_dues_meta(full_text, first_page_words)

    def test_total_due_was_parsed(self, stmt_meta):
        assert stmt_meta.total_due is not None

    def test_all_five_dues_fields_were_parsed(self, stmt_meta):
        assert stmt_meta.previous_dues is not None
        assert stmt_meta.total_payments is not None
        assert stmt_meta.total_purchases is not None
        assert stmt_meta.finance_charges is not None
        assert stmt_meta.total_due is not None

    def test_reconciles_within_warning_tolerance(self, transactions, stmt_meta):
        result = reconcile_statement("card_dues", stmt_meta, transactions, tolerance=Decimal("1.00"))
        assert result.recon_status in (ReconState.RECONCILED, ReconState.RECONCILED_WITH_WARNING), (
            f"expected reconciled or reconciled_with_warning, got {result.recon_status} "
            f"(diff {result.recon_diff})"
        )

    def test_report(self, fixture, transactions, stmt_meta):
        # Deliberately not hard-asserted beyond the tolerance check above: these are the real
        # numbers, reported for confirmation rather than locked in as golden.
        debit_count = sum(1 for t in transactions if t.direction is TxnDirection.DEBIT)
        credit_count = sum(1 for t in transactions if t.direction is TxnDirection.CREDIT)
        result = reconcile_statement("card_dues", stmt_meta, transactions, tolerance=Decimal("1.00"))
        print(
            f"\n[hdfc_cc golden] {fixture.name}: "
            f"total txns={len(transactions)} debit={debit_count} credit={credit_count} "
            f"previous_dues={stmt_meta.previous_dues} total_payments={stmt_meta.total_payments} "
            f"total_purchases={stmt_meta.total_purchases} finance_charges={stmt_meta.finance_charges} "
            f"total_due={stmt_meta.total_due} recon_status={result.recon_status} "
            f"recon_diff={result.recon_diff}"
        )

    def test_no_section_break_text_in_narration(self, transactions):
        polluted = [
            t for t in transactions
            if any(
                marker in t.raw_description.upper()
                for marker in ("REWARDS PROGRAM", "GST SUMMARY", "TRANSACTIONS TOTAL AMOUNT", "LOAN SUMMARY")
            )
        ]
        assert not polluted, (
            f"{len(polluted)} row(s) absorbed section-break text into raw_description: "
            f"{[t.raw_description for t in polluted]}"
        )


# --- direction / normalisation unit tests (no PDF needed) -----------------------------------------


def test_merchant_name_containing_cr_letters_resolves_debit():
    """The exact bug class named in the task: "SUBSCRIPTION" contains the letters "cr" as a
    substring. A naive `"cr" in full_line` check would wrongly flag this as a credit; scoping
    detection to the amount cell alone must not.
    """
    line_words = [
        _Word(text="15/07/2026|", x0=30.0, x1=90.0, top=100.0),
        _Word(text="SUBSCRIPTION", x0=100.0, x1=200.0, top=100.0),
        _Word(text="C", x0=445.0, x1=449.0, top=100.0),
        _Word(text="500.00", x0=452.0, x1=480.0, top=100.0),
    ]
    cell = _find_amount_cell(line_words)
    assert cell is not None
    assert not cell.is_credit
    assert cell.magnitude == Decimal("500.00")
    assert signed_amount(cell.magnitude, TxnDirection.DEBIT) == Decimal("-500.00")


def test_leading_c_currency_glyph_is_stripped():
    line_words = [
        _Word(text="15/07/2026|", x0=30.0, x1=90.0, top=100.0),
        _Word(text="C", x0=445.0, x1=449.0, top=100.0),
        _Word(text="12,345.00", x0=452.0, x1=490.0, top=100.0),
    ]
    cell = _find_amount_cell(line_words)
    assert cell is not None
    assert cell.magnitude == Decimal("12345.00")
    assert not cell.is_credit


def test_leading_plus_before_c_resolves_to_positive_credit():
    # The real, verified shape: a standalone "+" immediately before the "C" currency glyph.
    line_words = [
        _Word(text="18/06/2026|", x0=30.0, x1=90.0, top=100.0),
        _Word(text="PETRO", x0=100.0, x1=150.0, top=100.0),
        _Word(text="SURCHARGE", x0=152.0, x1=210.0, top=100.0),
        _Word(text="WAIVER", x0=212.0, x1=260.0, top=100.0),
        _Word(text="+", x0=440.0, x1=444.0, top=100.0),
        _Word(text="C", x0=447.0, x1=451.0, top=100.0),
        _Word(text="1,000.00", x0=454.0, x1=490.0, top=100.0),
    ]
    cell = _find_amount_cell(line_words)
    assert cell is not None
    assert cell.is_credit
    assert cell.magnitude == Decimal("1000.00")
    assert signed_amount(cell.magnitude, TxnDirection.CREDIT) == Decimal("1000.00")


def test_glued_leading_c_and_trailing_cr_resolve_to_positive_credit():
    # Fallback shape (not observed on the real fixtures, kept for robustness): a single glued
    # token "C1,000.00Cr" — the collision the task specifically named.
    line_words = [
        _Word(text="15/07/2026|", x0=30.0, x1=90.0, top=100.0),
        _Word(text="C1,000.00Cr", x0=445.0, x1=490.0, top=100.0),
    ]
    cell = _find_amount_cell(line_words)
    assert cell is not None
    assert cell.is_credit
    assert cell.magnitude == Decimal("1000.00")
    assert signed_amount(cell.magnitude, TxnDirection.CREDIT) == Decimal("1000.00")
