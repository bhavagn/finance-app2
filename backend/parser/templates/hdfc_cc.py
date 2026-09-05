"""HDFC credit-card statement parser (Millennia and similar card products).

Pure function: a PDF path in, a list of canonical `Transaction` models out. No DB writes, no
network calls. `statement_id`/`account_id`/`user_id`/`fingerprint` are left for the pipeline/DB to
attach — this template only knows what's on the page.

Verified against the real HDFC Millennia ••9670 fixtures (Jun/Jul/Aug 2026 statements). Two
assumptions this module started with turned out wrong on real data and were corrected here:
- The credit indicator is NOT a trailing "Cr"/"CR" suffix — real rows use a standalone "+" word
  immediately before the "C" currency glyph (e.g. "PETRO SURCHARGE WAIVER + C 38.43"). Zero "Cr"/
  "CR" occurrences exist anywhere across all three fixtures. The old Cr-suffix detection is kept
  as a secondary check (harmless, and future-proofs against a card template that does use it) but
  is no longer the primary signal.
- The transaction date is usually glued directly to a trailing "|" with no space (e.g.
  "13/06/2026|"), which the original exact-match date check rejected outright — silently dropping
  the row. Fixed by stripping a trailing "|" before checking.

How a card differs from the savings parser:
- No per-row running balance is printed, so there's no balance_after and no balance-delta
  direction signal. reconcile_statement("card_dues", ...) uses the printed aggregates instead and
  skips the row-level walk entirely (that walk only applies when a running balance exists).
- Direction detection is scoped strictly to the amount cell itself (the "+"/"C"/amount token
  cluster) — never a substring check against the full line, which would wrongly flag a merchant
  name containing "cr" (e.g. "SUBSCRIPTION") as a credit. See _find_amount_cell.
- EMI instalment rows carry markers like "NB:04"/"NBR:04" in the narration (confirmed real,
  format "OFFUS EMI,PRIN NB:04,00000138588544" / "OFFUS EMI,INT NBR:04,..."). They parse as
  ordinary debit transactions this increment — no EMI detection/loan linking (Phase 2). The
  markers contain no decimal point, so they never collide with amount-cell detection.
- Real transactions are single-line (no multi-line narration wrap was observed) — but the
  transaction table is directly followed, on the SAME page, by summary sections (transactions
  total, rewards points, EMI loan summary, GST summary) that print no date and would otherwise be
  silently appended to the last transaction's narration as a "continuation". _is_section_break
  flushes the pending transaction there instead of merging it in — this is real, observed
  pollution, not a hypothetical.
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

_BARE_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}$")
# Fallback shape (not observed on the real fixtures, kept for robustness): a currency glyph glued
# directly onto the digits, optionally with a glued Cr/CR suffix, e.g. "C1,000.00" or "C1,000.00Cr".
_GLUED_AMOUNT_RE = re.compile(r"^C([\d,]+\.\d{2})(Cr|CR)?$")
_STANDALONE_CR_RE = re.compile(r"^(?:Cr|CR)$")
_TIME_OF_DAY_RE = re.compile(r"^\d{1,2}:\d{2}$")

# Real dates print glued to a trailing "|" with no space ("13/06/2026|"); occasionally (seen on
# "International Transactions" rows) there's a real space instead ("21/07/2026 |"), which
# tokenizes as two separate words and needs no stripping. rstrip handles both uniformly.
DATE_X0_MAX = 220  # measured: real date tokens sit at x0=169.5; wide margin either side
LINE_TOP_TOLERANCE = 3

# Section headers that appear on the SAME page directly after the transaction table, before the
# next page break — confirmed by inspecting all three real fixtures. None of them print a leading
# date, so without this they'd silently be treated as a continuation of the last transaction's
# narration (real, observed pollution — this isn't a hypothetical like the savings footer guard).
_SECTION_BREAK_MARKERS = (
    "TRANSACTIONS TOTAL AMOUNT",
    "REWARDS PROGRAM",
    "SMART EMI LOAN SUMMARY",
    "GST SUMMARY",
    "IMPORTANT INFORMATION",
    "USEFUL LINKS",
    "DOMESTIC TRANSACTIONS",
    "INTERNATIONAL TRANSACTIONS",
)


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
    narration_parts: List[str]


@dataclass
class _AmountCell:
    start: int  # first word index belonging to the cell (narration = words[1:start])
    end: int  # last word index belonging to the cell (inclusive)
    magnitude: Decimal
    is_credit: bool


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


def _is_boilerplate(line_text: str) -> bool:
    upper = line_text.upper()
    if "HDFC BANK" in upper or "CREDIT CARD STATEMENT" in upper:
        return True
    if "DATE" in upper and "TRANSACTION" in upper and ("AMOUNT" in upper or "DESCRIPTION" in upper):
        return True
    if re.fullmatch(r"PAGE\s*\d+\s*(OF\s*\d+)?", upper.strip()):
        return True
    return False


def _is_section_break(line_text: str) -> bool:
    upper = line_text.upper()
    return any(marker in upper for marker in _SECTION_BREAK_MARKERS)


def _find_amount_cell(words: List[_Word]) -> Optional[_AmountCell]:
    """Find the transaction amount on an anchor line, scanning left to right and taking the LAST
    complete match (the amount is the rightmost value on the line).

    Primary shape (verified on all three real fixtures): a standalone "+" word (credit only),
    then a standalone "C" word, then a bare numeric word — "+ C 38.43" or plain "C 23.76".
    Fallback shape (not observed, kept for robustness): a glued single token "C1,000.00" or
    "C1,000.00Cr", still honouring a preceding "+" and/or a trailing Cr/CR suffix either way.
    """
    best: Optional[_AmountCell] = None
    n = len(words)
    i = 0
    while i < n:
        has_plus = words[i].text == "+"
        j = i + 1 if has_plus else i
        if j >= n:
            break

        if words[j].text == "C" and j + 1 < n and _BARE_AMOUNT_RE.match(words[j + 1].text):
            end = j + 1
            magnitude = parse_indian_amount(words[end].text)
            is_credit = has_plus
            if end + 1 < n and _STANDALONE_CR_RE.match(words[end + 1].text):
                is_credit = True
                end += 1
            best = _AmountCell(start=i, end=end, magnitude=magnitude, is_credit=is_credit)
            i = end + 1
            continue

        match = _GLUED_AMOUNT_RE.match(words[j].text)
        if match:
            end = j
            magnitude = parse_indian_amount(match.group(1))
            is_credit = has_plus or bool(match.group(2))
            if end + 1 < n and _STANDALONE_CR_RE.match(words[end + 1].text):
                is_credit = True
                end += 1
            best = _AmountCell(start=i, end=end, magnitude=magnitude, is_credit=is_credit)
            i = end + 1
            continue

        i += 1

    return best


def _clean_narration(words: List[_Word]) -> str:
    kept = [w.text for w in words if not (w.text == "|" or _TIME_OF_DAY_RE.match(w.text))]
    return text_clean.clean_text(" ".join(kept))


def _finalize(pending: _PendingTxn, source_row: int) -> Transaction:
    narration = text_clean.clean_text(" ".join(pending.narration_parts))
    signed = signed_amount(pending.magnitude, pending.direction)
    return Transaction(
        txn_date=pending.txn_date,
        raw_description=narration,
        direction=pending.direction,
        amount=signed,
        source_page=pending.page,
        source_row=source_row,
    )


def parse(pdf_path: Union[str, Path]) -> List[Transaction]:
    """Parse an HDFC credit-card statement PDF into canonical `Transaction` rows, in statement order.

    Unlike hdfc_savings.parse(), there's no opening_balance parameter: a card prints no running
    balance, so there's nothing for row 1 (or any row) to be confirmed against — direction comes
    solely from the credit indicator.
    """
    transactions: List[Transaction] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            lines = _cluster_lines(words)

            pending: Optional[_PendingTxn] = None
            page_row = 0

            def _flush() -> None:
                nonlocal pending, page_row
                if pending is not None:
                    page_row += 1
                    transactions.append(_finalize(pending, page_row))
                    pending = None

            for line in lines:
                if not line.words:
                    continue
                line_text = text_clean.clean_text(line.text)
                if not line_text:
                    continue
                if _is_section_break(line_text):
                    _flush()  # summary/rewards/EMI-loan/GST sections end the pending narration
                    continue
                if _is_boilerplate(line_text):
                    continue

                first_word = line.words[0]
                date_text = first_word.text.rstrip("|")
                starts_with_date = first_word.x0 < DATE_X0_MAX and is_date_token(date_text)
                cell = _find_amount_cell(line.words) if starts_with_date else None

                if starts_with_date and cell is not None:
                    _flush()

                    narration_words = line.words[1:cell.start]
                    pending = _PendingTxn(
                        page=page_index,
                        txn_date=parse_ddmmyy(date_text),
                        direction=TxnDirection.CREDIT if cell.is_credit else TxnDirection.DEBIT,
                        magnitude=cell.magnitude,
                        narration_parts=[_clean_narration(narration_words)],
                    )
                elif pending is not None:
                    pending.narration_parts.append(line_text)
                # else: stray boilerplate/header fragment before any anchor on this page — drop it

            _flush()

    return transactions
