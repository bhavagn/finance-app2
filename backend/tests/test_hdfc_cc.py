"""Tests for the HDFC credit-card (Millennia) parser.

The golden section runs against every real Millennia ••9670 fixture present in tests/fixtures/
(there are three: Jun/Jul/Aug 2026 statements — none of them has a total_due matching
finance-app-spec.md §8's ₹52,368.80, so that figure is stale/from a different statement and is
NOT asserted here; see the session notes for how this was confirmed). The section is skipped
entirely when no fixture is present — they're gitignored real bank data. The direction/
normalisation unit tests below need no PDF and always run.

Txn counts and debit/credit splits are deliberately NOT locked as golden assertions yet — see
test_purchases_and_payments_cross_check_report: card_dues only reconciles the printed summary
box against itself, never against what was actually parsed, so a dropped or mis-signed row would
pass silently. That cross-check is a diagnostic report for now, not a gate, until its results
tell us the bank's real definition of the printed totals.
"""
import re
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
_EMI_MARKER_RE = re.compile(r"\bNBR?:\d")


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


# --- diagnostic cross-check: parsed transactions vs. the printed summary box ---------------------
#
# card_dues (reconcile_statement) only checks the printed summary box's internal arithmetic — it
# never compares that box against what was actually parsed off the transaction table. Bug 2 in the
# previous increment (2 of ~20 rows parsed) would have sailed through that check silently, since
# the summary box's own numbers were untouched. This is a DIAGNOSTIC REPORT, not a hard gate: we
# measure the bank's real definition of "total purchases" / "total payments" against real data
# first, the same way the ₹0.38 GST-tolerance was measured before being encoded as a tolerance.


@pytest.mark.skipif(not FIXTURES, reason="no Millennia ••9670 fixture present (gitignored real statement PDF)")
def test_purchases_and_payments_cross_check_report():
    rows = []
    for fixture in FIXTURES:
        transactions = parse(fixture)
        with pdfplumber.open(str(fixture)) as pdf:
            full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            first_page_words = pdf.pages[0].extract_words(keep_blank_chars=False, use_text_flow=False)
        stmt_meta = extract_card_dues_meta(full_text, first_page_words)

        debit_sum = sum((abs(t.amount) for t in transactions if t.direction is TxnDirection.DEBIT), Decimal("0"))
        credit_sum = sum((abs(t.amount) for t in transactions if t.direction is TxnDirection.CREDIT), Decimal("0"))

        diff_purch = debit_sum - stmt_meta.total_purchases if stmt_meta.total_purchases is not None else None
        diff_pay = credit_sum - stmt_meta.total_payments if stmt_meta.total_payments is not None else None
        matches_finance_charges = (
            diff_purch is not None
            and stmt_meta.finance_charges is not None
            and abs(diff_purch) == stmt_meta.finance_charges
        )
        credit_exceeds_payments = (
            stmt_meta.total_payments is not None and credit_sum > stmt_meta.total_payments
        )
        emi_rows = [t for t in transactions if _EMI_MARKER_RE.search(t.raw_description)]

        rows.append(
            {
                "fixture": fixture.name,
                "debit_sum": debit_sum,
                "credit_sum": credit_sum,
                "total_purchases": stmt_meta.total_purchases,
                "total_payments": stmt_meta.total_payments,
                "finance_charges": stmt_meta.finance_charges,
                "diff_purch": diff_purch,
                "diff_pay": diff_pay,
                "diff_purch==finance_charges": matches_finance_charges,
                "credit_sum>total_payments": credit_exceeds_payments,
                "emi_rows": len(emi_rows),
            }
        )

    header = (
        f"{'fixture':<45} {'debit_sum':>10} {'credit_sum':>10} {'purchases':>10} "
        f"{'payments':>10} {'finance':>8} {'diff_purch':>10} {'diff_pay':>9} "
        f"{'=finance?':>9} {'cr>pay?':>8} {'emi':>4}"
    )
    print("\n[hdfc_cc cross-check] purchases/payments vs. parsed transactions (diagnostic, not asserted)")
    print(header)
    for r in rows:
        print(
            f"{r['fixture']:<45} {r['debit_sum']!s:>10} {r['credit_sum']!s:>10} "
            f"{r['total_purchases']!s:>10} {r['total_payments']!s:>10} {r['finance_charges']!s:>8} "
            f"{r['diff_purch']!s:>10} {r['diff_pay']!s:>9} "
            f"{str(r['diff_purch==finance_charges']):>9} {str(r['credit_sum>total_payments']):>8} "
            f"{r['emi_rows']:>4}"
        )


@pytest.mark.skipif(not FIXTURES, reason="no Millennia ••9670 fixture present (gitignored real statement PDF)")
def test_emi_marker_presence_report():
    print("\n[hdfc_cc cross-check] EMI-marker (NB:/NBR:) rows per fixture")
    for fixture in FIXTURES:
        transactions = parse(fixture)
        emi_rows = [t for t in transactions if _EMI_MARKER_RE.search(t.raw_description)]
        print(f"  {fixture.name}: has_emi={'yes' if emi_rows else 'no'} count={len(emi_rows)}")


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


def test_real_petro_surcharge_waiver_row_resolves_credit():
    """Pinned from real fixture data: this is the exact word/coordinate sequence pdfplumber
    produces for the "18/06/2026 00:00 PETRO SURCHARGE WAIVER + C 38.43" row on the Jul2026
    Millennia fixture (measured directly, not approximated) — the "+" is the ONLY credit signal
    that exists anywhere in these three real statements; "Cr"/"CR" never appears.
    """
    line_words = [
        _Word(text="18/06/2026|", x0=169.5, x1=206.5, top=776.1),
        _Word(text="00:00", x0=208.1, x1=224.2, top=776.1),
        _Word(text="PETRO", x0=260.2, x1=279.1, top=776.1),
        _Word(text="SURCHARGE", x0=280.6, x1=315.9, top=776.1),
        _Word(text="WAIVER", x0=317.5, x1=340.7, top=776.1),
        _Word(text="+", x0=528.5, x1=532.0, top=776.1),
        _Word(text="C", x0=535.2, x1=538.6, top=776.1),
        _Word(text="38.43", x0=540.2, x1=556.2, top=776.1),
        _Word(text="l", x0=567.3, x1=572.5, top=776.7),  # trailing "Purchase Indicator" glyph
    ]
    cell = _find_amount_cell(line_words)
    assert cell is not None
    assert cell.is_credit
    assert cell.magnitude == Decimal("38.43")
    assert signed_amount(cell.magnitude, TxnDirection.CREDIT) == Decimal("38.43")


def test_plus_in_merchant_narration_does_not_trigger_credit():
    """The "+" detection is scoped to the single word IMMEDIATELY before the "C" glyph — a "+"
    appearing anywhere else in the narration (e.g. a merchant name rendered with stray spacing
    around a "+") must not be mistaken for the credit signal.
    """
    line_words = [
        _Word(text="10/07/2026|", x0=169.5, x1=206.5, top=700.0),
        _Word(text="AT", x0=260.2, x1=275.0, top=700.0),
        _Word(text="+", x0=276.5, x1=280.0, top=700.0),  # part of a merchant name, far from "C"
        _Word(text="T", x0=281.5, x1=286.0, top=700.0),
        _Word(text="RECHARGE", x0=287.5, x1=330.0, top=700.0),
        _Word(text="C", x0=535.2, x1=538.6, top=700.0),
        _Word(text="199.00", x0=540.2, x1=556.2, top=700.0),
    ]
    cell = _find_amount_cell(line_words)
    assert cell is not None
    assert not cell.is_credit
    assert cell.magnitude == Decimal("199.00")
    assert signed_amount(cell.magnitude, TxnDirection.DEBIT) == Decimal("-199.00")
