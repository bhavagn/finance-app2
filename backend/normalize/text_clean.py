"""PDF-text normalisation: watermarks, unmapped glyphs, doubled letters, stray currency glyphs.

Required even for "digital" statement PDFs — see finance-app-spec.md §5.
"""
from __future__ import annotations

import re

_CID_GLYPH_RE = re.compile(r"\(cid:\d+\)")
_WATERMARK_RE = re.compile(r"(?i)\bDUPLICATE\b")
_WHITESPACE_RE = re.compile(r"\s+")
_CURRENCY_PREFIX_RE = re.compile(r"^(?:₹|Rs\.?|INR)\s*", re.IGNORECASE)
# Some statements mis-render the ₹ glyph as a stray backtick or a bare "C" glued to the digits.
# Only strip when immediately followed by a digit/comma, so real words starting with "C" survive.
_CURRENCY_GLYPH_ARTIFACT_RE = re.compile(r"^[`C](?=[\d,])")


def strip_cid_glyphs(text: str) -> str:
    """Remove literal "(cid:NN)" tokens left by fonts pdfplumber can't map to unicode."""
    return _CID_GLYPH_RE.sub("", text)


def strip_watermark(text: str) -> str:
    """Remove the "DUPLICATE" watermark token (case-insensitive, whole word)."""
    return _WATERMARK_RE.sub("", text)


def collapse_doubled_letters(text: str) -> str:
    """Collapse header tokens whose letters were each rendered twice, e.g. "SSTTAATTEEMMEENNTT".

    Only collapses a token when EVERY letter is doubled (even length, and the even- and odd-indexed
    characters match exactly) — real words essentially never satisfy this by chance, so narration
    text is left untouched.
    """

    def _collapse_token(token: str) -> str:
        if len(token) >= 4 and len(token) % 2 == 0 and token.isalpha():
            evens, odds = token[0::2], token[1::2]
            if evens == odds:
                return evens
        return token

    return " ".join(_collapse_token(tok) for tok in text.split())


def strip_currency_glyph(amount_text: str) -> str:
    """Strip a leading currency symbol/artifact (₹, Rs., INR, or a mis-rendered `/C) off an amount string."""
    s = amount_text.strip()
    s = _CURRENCY_PREFIX_RE.sub("", s)
    s = _CURRENCY_GLYPH_ARTIFACT_RE.sub("", s)
    return s


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def clean_text(text: str) -> str:
    """Full pipeline: strip cid glyphs, strip the watermark, collapse doubled letters, tidy whitespace."""
    text = strip_cid_glyphs(text)
    text = strip_watermark(text)
    text = collapse_doubled_letters(text)
    return normalize_whitespace(text)
