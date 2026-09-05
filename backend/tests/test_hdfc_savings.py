"""Golden-file test for the HDFC savings parser template.

Validated reference numbers (finance-app-spec.md §8): HDFC savings ••9069 — 549 txns, opening
₹59,828.38, closing ₹10,079.19, reconciles exact. The fixture PDF itself is gitignored (real bank
data), so this test is skipped when it isn't present on disk.
"""
from decimal import Decimal
from pathlib import Path

import pytest

from models.enums import TxnDirection
from parser.templates.hdfc_savings import extract_vpa, parse

FIXTURE = Path(__file__).parent / "fixtures" / "hdfc_savings_9069.pdf"

EXPECTED_TXN_COUNT = 549
EXPECTED_OPENING_BALANCE = Decimal("59828.38")
EXPECTED_CLOSING_BALANCE = Decimal("10079.19")

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(),
    reason=f"golden fixture not present: {FIXTURE} (gitignored real statement PDF)",
)


@pytest.fixture(scope="module")
def transactions():
    return parse(FIXTURE)


def test_transaction_count(transactions):
    assert len(transactions) == EXPECTED_TXN_COUNT, (
        f"expected {EXPECTED_TXN_COUNT} transactions, parsed {len(transactions)}"
    )


def test_opening_and_closing_balance(transactions):
    first, last = transactions[0], transactions[-1]
    opening = (first.balance_after - first.amount).quantize(Decimal("0.01"))
    closing = last.balance_after

    assert opening == EXPECTED_OPENING_BALANCE, f"expected opening {EXPECTED_OPENING_BALANCE}, derived {opening}"
    assert closing == EXPECTED_CLOSING_BALANCE, f"expected closing {EXPECTED_CLOSING_BALANCE}, got {closing}"


def test_statement_level_reconciliation(transactions):
    first = transactions[0]
    opening = (first.balance_after - first.amount).quantize(Decimal("0.01"))
    closing = transactions[-1].balance_after

    credits = sum((t.amount for t in transactions if t.direction is TxnDirection.CREDIT), Decimal("0"))
    debits = sum((-t.amount for t in transactions if t.direction is TxnDirection.DEBIT), Decimal("0"))

    computed_closing = (opening + credits - debits).quantize(Decimal("0.01"))
    assert computed_closing == closing, (
        f"opening {opening} + credits {credits} - debits {debits} = {computed_closing}, expected {closing}"
    )


def test_every_upi_row_has_a_bank_ref(transactions):
    upi_rows = [t for t in transactions if "UPI" in t.raw_description.upper()]
    missing_ref = [t for t in upi_rows if not t.bank_ref]
    assert not missing_ref, (
        f"{len(missing_ref)}/{len(upi_rows)} UPI rows are missing a bank_ref "
        f"(parse-completeness regression): {[t.raw_description for t in missing_ref][:5]}"
    )


def test_safe_gold_row_resolves_full_vpa_not_truncated(transactions):
    safe_gold_rows = [t for t in transactions if "SAFEGOLD" in t.raw_description.upper().replace(" ", "")]
    assert safe_gold_rows, "expected at least one SAFEGOLD row in the golden fixture"

    for txn in safe_gold_rows:
        vpa = extract_vpa(txn.raw_description)
        assert vpa is not None, f"no VPA recovered from: {txn.raw_description!r}"
        assert vpa.upper() == "SAFEGOLD@YBL", (
            f"VPA truncated — expected 'SAFEGOLD@YBL', got {vpa!r} from {txn.raw_description!r}"
        )
