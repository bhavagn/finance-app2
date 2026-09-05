"""HDFC credit-card statement parser (Millennia and similar card products).

Pure function: a PDF path in, a list of canonical `Transaction` models out. No DB writes, no
network calls. `statement_id`/`account_id`/`user_id`/`fingerprint` are left for the pipeline/DB to
attach — this template only knows what's on the page.

UNVERIFIED against a real fixture at the time this was written: no Millennia PDF was available.
Coordinate/label assumptions below are best-effort, mirroring how the savings parser's column x1
ranges started as guesses and were recalibrated once the real PDF arrived (see hdfc_savings.py's
git history) — expect this module to need the same treatment.

How a card differs from the savings parser:
- No per-row running balance is printed, so there's no balance_after and no balance-delta
  direction signal. reconcile_statement("card_dues", ...) uses the printed aggregates instead and
  skips the row-level walk entirely (that walk only applies when a running balance exists).
- Direction has exactly ONE source: a trailing "Cr"/"CR" credit indicator on the amount itself.
  Everything else is a debit (a purchase). There's no second signal to cross-check against, so
  detecting it is scoped strictly to the amount token's own text — never a substring check against
  the full line, which would wrongly flag a merchant name containing "cr" (e.g. "SUBSCRIPTION") as
  a credit. See _split_amount_cell.
- EMI instalment rows carry markers like "NB:06"/"NBR:01" in the narration. They parse as ordinary
  debit transactions this increment — no EMI detection/loan linking (that's Phase 2). The markers
  contain no decimal point, so they never collide with amount-token detection.
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

# Matches an amount cell that may carry BOTH traps at once: a leading "C" currency-glyph
# substitution (this statement's rendering of ₹) and/or a trailing Cr/CR credit indicator, glued
# on with no separating space (e.g. "C1,000.00Cr") since that's this bank's PDF-export norm
# (confirmed on the savings fixture; assumed here too pending the real card PDF).
_AMOUNT_CANDIDATE_RE = re.compile(r"^C?[\d,]+\.\d{2}(?:\s?(?:Cr|CR))?$")
_AMOUNT_CELL_RE = re.compile(r"^(C?[\d,]+\.\d{2})(?:\s?(Cr|CR))?$")
_STANDALONE_CR_RE = re.compile(r"^(?:Cr|CR)$")
DATE_X0_MAX = 70
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


def _is_boilerplate(line_text: str) -> bool:
    upper = line_text.upper()
    if "HDFC BANK" in upper:
        return True
    if "DATE" in upper and "TRANSACTION" in upper and ("AMOUNT" in upper or "DESCRIPTION" in upper):
        return True
    if re.fullmatch(r"PAGE\s*\d+\s*(OF\s*\d+)?", upper.strip()):
        return True
    return False


def _split_amount_cell(amount_word: _Word, next_word: Optional[_Word]) -> "tuple[Decimal, TxnDirection]":
    """Parse one amount token (+ a peek at the next word) into (magnitude, direction).

    Handles both observed shapes for the credit indicator: glued onto the same token
    ("C1,000.00Cr") or as its own following word ("C1,000.00" then "Cr"). The leading "C" currency
    glyph is stripped by normalize.amounts.parse_indian_amount regardless of which shape this is.

    Both checks are scoped to this one amount token (+ its immediate neighbour) — never a
    substring search over the full line — so a merchant name containing "cr" (e.g.
    "SUBSCRIPTION", "MICROSOFT") can never be mistaken for a credit indicator. Deliberately NOT a
    `\\bcr\\b` suffix regex on the raw token text: "1,000.00Cr" has no word-boundary between the
    digit "0" and the letter "C" (both are \\w), so that pattern would silently miss the glued
    form that's this bank's PDF-export norm — the full-string capture group below matches it
    directly instead.
    """
    match = _AMOUNT_CELL_RE.match(amount_word.text)
    numeric_part = match.group(1) if match else amount_word.text
    embedded_cr = bool(match and match.group(2))
    separate_cr = next_word is not None and bool(_STANDALONE_CR_RE.match(next_word.text.strip()))

    is_credit = embedded_cr or separate_cr
    magnitude = parse_indian_amount(numeric_part)
    direction = TxnDirection.CREDIT if is_credit else TxnDirection.DEBIT
    return magnitude, direction


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
                if not line_text or _is_boilerplate(line_text):
                    continue

                first_word = line.words[0]
                amount_words = [
                    (i, w) for i, w in enumerate(line.words) if _AMOUNT_CANDIDATE_RE.match(w.text)
                ]
                starts_with_date = first_word.x0 < DATE_X0_MAX and is_date_token(first_word.text)

                if starts_with_date and amount_words:
                    _flush()

                    amount_index, amount_word = amount_words[-1]
                    next_word = line.words[amount_index + 1] if amount_index + 1 < len(line.words) else None
                    magnitude, direction = _split_amount_cell(amount_word, next_word)

                    excluded = {id(first_word), id(amount_word)}
                    if next_word is not None and _STANDALONE_CR_RE.match(next_word.text.strip()):
                        excluded.add(id(next_word))
                    narration_words = [w for w in line.words if id(w) not in excluded]

                    pending = _PendingTxn(
                        page=page_index,
                        txn_date=parse_ddmmyy(first_word.text),
                        direction=direction,
                        magnitude=magnitude,
                        narration_parts=[" ".join(w.text for w in narration_words)],
                    )
                elif pending is not None:
                    pending.narration_parts.append(line_text)
                # else: stray boilerplate/header fragment before any anchor on this page — drop it

            _flush()

    return transactions
