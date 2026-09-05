"""Unit tests for parser.templates.hdfc_savings._is_footer_line — no PDF needed.

Real footer/disclaimer text observed on the HDFC savings ••9069 fixture's last page comes out of
pdfplumber with NO space characters at all (a PDF-export quirk, not specific to the transaction
table): "*Closingbalanceincludesfundsearmarkedforholdandunclearedfunds",
"Contentsofthisstatementwillbeconsideredcorrectif...", "RegisteredOfficeAddress:...". A marker
containing a literal space would silently never match that, so these tests pin the fix down.
"""
from parser.templates.hdfc_savings import _is_footer_line


def test_star_prefixed_disclaimer_is_a_footer_line():
    assert _is_footer_line("*Closingbalanceincludesfundsearmarkedforholdandunclearedfunds") is True


def test_glued_contents_of_disclaimer_is_a_footer_line():
    text = (
        "Contentsofthisstatementwillbeconsideredcorrectifnoerrorisreportedwithin30days"
        "ofreceiptofstatement."
    )
    assert _is_footer_line(text) is True


def test_glued_registered_office_line_is_a_footer_line():
    assert _is_footer_line("RegisteredOfficeAddress:HDFCBankHouse,SenapatiBapatMarg,LowerParel,Mumbai400013") is True


def test_gstin_line_is_a_footer_line():
    assert _is_footer_line("HDFCBankGSTINnumberdetailsareavailableathttps://example.com") is True


def test_normal_narration_is_not_a_footer_line():
    assert _is_footer_line("UPI-SAFEGOLD@YBL-YESB0YBLUPI-606054723790-GOLDWILLBEPURCH") is False
