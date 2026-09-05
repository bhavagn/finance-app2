"""HDFC savings-account statement parser: coordinate-based extraction with multi-line UPI merge.

Pure function: a PDF path in, a list of canonical `Transaction` models out. No DB writes, no
network calls. `statement_id`/`account_id`/`user_id`/`fingerprint` are left for the pipeline/DB to
attach — this template only knows what's on the page.

Layout facts (validated against the HDFC savings ••9069 golden fixture, see finance-app-spec.md
§5 and §8):
- A transaction ANCHOR line starts with a dd/mm/yy date (x0 < 70) and ends with >= 2 amount tokens;
  the LAST amount is the running closing balance, the one before it is the transaction amount.
- Column right-edges (x1) are near-constant since amounts are right-aligned: withdrawal ~= 470.2,
  deposit ~= 548.2, closing balance ~= 626.7.
- Lines after an anchor that do NOT start with a date are a continuation of that SAME transaction's
  narration (critical: this is what recovers multi-line UPI merchant VPAs like "SAFEGOLD@YBL" that
  print on the row below the anchor) — UNLESS the line is footer/disclaimer boilerplate, which ends
  the pending narration instead of joining it.
- Direction is resolved primarily from the running-balance delta (b - prev == +/-magnitude, to the
  paise): column position is only a fallback/cross-check, used when the delta can't confirm a row
  (row 1 with no opening_balance, or a delta that doesn't match the parsed amount). This makes rows
  2..N immune to a miscalibrated column x-range — a shifted boundary can no longer produce a
  confidently wrong direction, only trigger the fallback.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Union

import pdfplumber

from models import Transaction
from models.enums import TxnDirection
from normalize import text_clean
from normalize.amounts import parse_indian_amount, signed_amount
from normalize.dates import is_date_token, parse_ddmmyy

_LOGGER = logging.getLogger(__name__)

_AMOUNT_TOKEN_RE = re.compile(r"^\d{1,3}(?:,\d{2,3})*\.\d{2}$")
_BANK_REF_RE = re.compile(r"(?<!\d)\d{16}(?!\d)")
# No hyphen in the prefix class: UPI narrations use "-" as a field separator (e.g.
# "UPI-SAFE GOLD-SAFEGOLD@YBL-..."), and an over-greedy class swallows the whole hyphenated
# run instead of stopping at the real local-part immediately before "@".
_VPA_RE = re.compile(r"\b[A-Za-z0-9._]{2,}@[A-Za-z]{2,}\b")
_EMBEDDED_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")

# Footer/disclaimer text that must never be merged into a transaction's narration — page footers
# aren't caught by _is_boilerplate's header/column-header checks, so without this the LAST
# transaction on each page silently absorbs junk like "*Closing balance includes funds earmarked...".
_FOOTER_MARKERS = (
    "CONTENTS OF",
    "REGISTERED OFFICE",
    "GSTIN",
    "CONSIDERED CORRECT",
    "FUNDS EARMARKED",
)

DATE_X0_MAX = 70
# Right-aligned amount columns have a near-constant x1 regardless of magnitude (measured on the
# HDFC ••9069 golden fixture: withdrawal values cluster at x1=470.2, deposit at x1=548.2, closing
# balance at x1=626.7 — a wide margin separates them, so generous tolerance bands are safe).
WITHDRAWAL_X1_RANGE = (455, 485)
DEPOSIT_X1_RANGE = (530, 565)
LINE_TOP_TOLERANCE = 3


@dataclass
class _Word:
    text: str
    x0: float
    x1: float
    top: float


@dataclass
class _Line:
    top: float
    words: List[_Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class _PendingTxn:
    page: int
    txn_date: object  # datetime.date
    direction: TxnDirection
    magnitude: Decimal
    balance_after: Decimal
    narration_parts: List[str]


def _cluster_lines(words: List[dict], tolerance: float = LINE_TOP_TOLERANCE) -> List[_Line]:
    boxes = sorted(
        (_Word(w["text"], w["x0"], w["x1"], w["top"]) for w in words),
        key=lambda w: (w.top, w.x0),
    )
    lines: List[_Line] = []
    for box in boxes:
        if lines and abs(box.top - lines[-1].top) <= tolerance:
            lines[-1].words.append(box)
        else:
            lines.append(_Line(top=box.top, words=[box]))
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    return lines


def _is_footer_line(line_text: str) -> bool:
    """Footer/disclaimer text — ends the current pending narration rather than joining it.

    Checked separately from _is_boilerplate (and given its own flush in parse()) because a footer
    block can wrap onto a second line that carries none of these markers itself; flushing at the
    first marker line stops that wrapped continuation from being appended to a stale `pending`.

    Matched against both a normally-spaced and a whitespace-collapsed form: this bank's PDF export
    frequently glues static text into a single word with no space characters at all (e.g.
    "Contentsofthisstatementwillbeconsideredcorrectif...", "RegisteredOfficeAddress:..."), so a
    marker containing a space would otherwise silently never match.
    """
    stripped = line_text.strip()
    if stripped.startswith("*"):
        return True
    upper = stripped.upper()
    compact = upper.replace(" ", "")
    return any(marker in upper or marker.replace(" ", "") in compact for marker in _FOOTER_MARKERS)


def _is_boilerplate(line_text: str) -> bool:
    upper = line_text.upper()
    if "HDFC BANK" in upper or "STATEMENT OF ACCOUNT" in upper:
        return True
    if "NARRATION" in upper and "WITHDRAWAL" in upper and "DEPOSIT" in upper:
        return True
    if re.fullmatch(r"PAGE\s*\d+\s*(OF\s*\d+)?", upper.strip()):
        return True
    if "STATEMENT SUMMARY" in upper:
        return True
    return False


def _classify_by_column(amount_word: _Word) -> Optional[TxnDirection]:
    if WITHDRAWAL_X1_RANGE[0] <= amount_word.x1 <= WITHDRAWAL_X1_RANGE[1]:
        return TxnDirection.DEBIT
    if DEPOSIT_X1_RANGE[0] <= amount_word.x1 <= DEPOSIT_X1_RANGE[1]:
        return TxnDirection.CREDIT
    return None


_BALANCE_TOLERANCE = Decimal("0.01")


def _resolve_direction(
    magnitude: Decimal,
    balance_after: Decimal,
    prev_balance: Optional[Decimal],
    txn_amount_word: _Word,
) -> TxnDirection:
    """Balance delta is the source of truth; column position is only a fallback/cross-check.

    `prev_balance` is the previous row's balance_after, or the statement's opening_balance for
    row 1. When the balance actually moved by the parsed amount (to the paise), that movement's
    sign is authoritative — a miscalibrated column x-range can no longer produce a confidently
    wrong direction for rows 2..N, only fail to confirm one.
    """
    column_direction = _classify_by_column(txn_amount_word)

    if prev_balance is not None:
        delta = balance_after - prev_balance
        if abs(abs(delta) - magnitude) <= _BALANCE_TOLERANCE:
            delta_direction = TxnDirection.CREDIT if delta > 0 else TxnDirection.DEBIT
            if column_direction is not None and column_direction is not delta_direction:
                _LOGGER.warning(
                    "direction mismatch at balance_after=%s (amount=%s): balance-delta says %s, "
                    "column position says %s — using the delta",
                    balance_after, magnitude, delta_direction.value, column_direction.value,
                )
            return delta_direction

    _LOGGER.warning(
        "could not confirm direction via balance delta at balance_after=%s (amount=%s, "
        "prev_balance=%s) — falling back to column position",
        balance_after, magnitude, prev_balance,
    )
    return column_direction or TxnDirection.DEBIT


def _extract_bank_ref(narration: str) -> Optional[str]:
    match = _BANK_REF_RE.search(narration)
    return match.group(0) if match else None


def extract_vpa(narration: str) -> Optional[str]:
    """Extract a UPI VPA (e.g. "SAFEGOLD@YBL") from a transaction's merged narration, if present.

    The VPA is the strongest merchant key (finance-app-spec.md §5); resolving it correctly depends
    on the multi-line merge above having pulled the full narration together first.
    """
    match = _VPA_RE.search(narration)
    return match.group(0) if match else None


def _clean_narration(narration: str, bank_ref: Optional[str]) -> str:
    cleaned = narration
    if bank_ref:
        cleaned = cleaned.replace(bank_ref, " ")
    cleaned = _EMBEDDED_DATE_RE.sub(" ", cleaned)
    cleaned = text_clean.normalize_whitespace(cleaned)
    return cleaned.strip(" -")


def _finalize(pending: _PendingTxn, source_row: int) -> Transaction:
    narration = text_clean.clean_text(" ".join(pending.narration_parts))
    bank_ref = _extract_bank_ref(narration)
    raw_description = _clean_narration(narration, bank_ref)
    signed = signed_amount(pending.magnitude, pending.direction)
    return Transaction(
        txn_date=pending.txn_date,
        raw_description=raw_description,
        bank_ref=bank_ref,
        direction=pending.direction,
        amount=signed,
        balance_after=pending.balance_after,
        source_page=pending.page,
        source_row=source_row,
    )


def parse(pdf_path: Union[str, Path], opening_balance: Optional[Decimal] = None) -> List[Transaction]:
    """Parse an HDFC savings-account statement PDF into canonical `Transaction` rows, in statement order.

    `opening_balance`, when given, is used as `prev_balance` for the first row's direction check
    (balance_after - opening_balance == +/-magnitude); without it, row 1 falls back to column
    position like any row whose delta doesn't confirm.
    """
    transactions: List[Transaction] = []
    prev_balance: Optional[Decimal] = opening_balance

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            lines = _cluster_lines(words)

            pending: Optional[_PendingTxn] = None
            page_row = 0

            def _flush() -> None:
                nonlocal pending, prev_balance, page_row
                if pending is not None:
                    page_row += 1
                    txn = _finalize(pending, page_row)
                    transactions.append(txn)
                    prev_balance = txn.balance_after
                    pending = None

            for line in lines:
                if not line.words:
                    continue
                line_text = text_clean.clean_text(line.text)
                if not line_text:
                    continue
                if _is_footer_line(line_text):
                    _flush()  # footer/disclaimer text ends the pending narration, never joins it
                    continue
                if _is_boilerplate(line_text):
                    continue

                first_word = line.words[0]
                amount_words = [w for w in line.words if _AMOUNT_TOKEN_RE.match(w.text)]
                starts_with_date = first_word.x0 < DATE_X0_MAX and is_date_token(first_word.text)

                if starts_with_date and len(amount_words) >= 2:
                    _flush()

                    closing_word = amount_words[-1]
                    txn_amount_word = amount_words[-2]
                    balance_after = parse_indian_amount(closing_word.text)
                    magnitude = parse_indian_amount(txn_amount_word.text)

                    direction = _resolve_direction(magnitude, balance_after, prev_balance, txn_amount_word)

                    narration_words = [
                        w for w in line.words if w is not first_word and w is not txn_amount_word and w is not closing_word
                    ]

                    pending = _PendingTxn(
                        page=page_index,
                        txn_date=parse_ddmmyy(first_word.text),
                        direction=direction,
                        magnitude=magnitude,
                        balance_after=balance_after,
                        narration_parts=[" ".join(w.text for w in narration_words)],
                    )
                elif pending is not None:
                    pending.narration_parts.append(line_text)
                # else: stray boilerplate/header fragment before any anchor on this page — drop it

            _flush()

    return transactions
