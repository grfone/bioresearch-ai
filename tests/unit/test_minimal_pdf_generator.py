"""
tests/unit/test_minimal_pdf_generator.py

Unit tests for the hand-rolled ``MinimalPDFGenerator``.

The generator is intentionally minimal: ASCII-only text in
Helvetica on a single page. These tests pin the behaviour
that LLMs rely on:

  - The PDF magic header (``%PDF-1.4``) is always present.
  - Common Unicode punctuation (em dashes, smart quotes,
    ellipses, etc.) is normalized to ASCII so the latin-1
    encode doesn't crash.
  - Any non-ASCII codepoint that survives the normalizer
    is replaced with ``?`` -- a visible fallback, not a
    500.
  - PDF text-object escapes (``, ``(`` ``)`` ``\``) are
    applied correctly.
  - Control characters (newlines, tabs) are replaced with
    spaces inside text objects.

Why this file exists
--------------------
The minimal generator is a hand-rolled 400-line implementation
of a well-specified format (PDF 1.4). Without these tests a
future contributor could change the encoding pipeline and
silently regress on Unicode handling -- the kind of bug that
only surfaces in production when an LLM emits a single em
dash. See the live-verify incident in the pick-up 3 session
where a 20-paper report crashed the publish endpoint because
the LLM summary contained ``—``.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import io

import pytest

from app.domain.entities.author import Author
from app.domain.entities.citation import Citation
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.summary import Summary
from app.domain.interfaces.pdf_generator import PDFGenerator
from app.infrastructure.pdf.minimal_generator import MinimalPDFGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report(text: str) -> ResearchReport:
    """Build a minimal ResearchReport whose summary is ``text``.

    The generator only reads ``summary.text``; citations,
    limitations, and future_work can be empty for these tests.
    """
    paper = Paper(
        title="Tau phosphorylation in Alzheimer's disease",
        authors=[Author(first_name="Jane", last_name="Doe")],
        journal=Journal(name="Nature"),
        year=2024,
        abstract="",
        doi="10.1038/nature14539",
    )
    return ResearchReport(
        summary=Summary(text=text, papers_used=[paper]),
        citations=[
            Citation(
                paper=paper,
                style=__import__(
                    "app.core.enums.citation_style",
                    fromlist=["CitationStyleEnum"],
                ).CitationStyleEnum.APA,
            )
        ],
        limitations=["Sample size is small"],
        future_work=["Replicate in larger cohort"],
        metadata={"model": "stub"},
    )


@pytest.fixture
def generator() -> MinimalPDFGenerator:
    return MinimalPDFGenerator()


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_generator_implements_pdf_generator_interface() -> None:
    """``MinimalPDFGenerator`` satisfies the interface so the
    orchestrator can inject it via ``PDFGenerator``.
    """
    assert isinstance(MinimalPDFGenerator(), PDFGenerator)


def test_generate_returns_valid_pdf_bytes(generator) -> None:
    """The generator returns bytes that start with the PDF
    magic header and end with the ``%%EOF`` terminator.
    """
    pdf = generator.generate(_make_report("A plain ASCII summary."))
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.endswith(b"%%EOF\n")
    # ``file`` would call it PDF v1.4 -- the magic header is
    # the only programmatic pin we can assert on here.
    assert b"%PDF-1.4" in pdf
    # The body should reference the catalog object we emit.
    assert b"/Type /Catalog" in pdf
    assert b"/Type /Page" in pdf


def test_generate_rejects_empty_summary(generator) -> None:
    """A report with no summary text is malformed -- the
    generator raises ``ValueError`` rather than producing
    a blank PDF.
    """
    with pytest.raises(ValueError, match="empty report"):
        generator.generate(_make_report(""))


# ---------------------------------------------------------------------------
# Unicode normalization (regression: pick-up 3 live-verify crash)
# ---------------------------------------------------------------------------


def test_em_dash_in_summary_does_not_crash(generator) -> None:
    """REGRESSION: the LLM in the pick-up 3 live-verify
    produced a summary containing an em dash (``—``).
    The minimal generator used to call ``.encode("latin-1")``
    on the text and crash with ``UnicodeEncodeError``.

    After the fix, em dashes are normalized to ``--`` (a
    visible ASCII equivalent) and the PDF renders. This
    test pins the behavior so a future contributor can't
    silently regress it.
    """
    # The character ``—`` is U+2014, outside latin-1.
    summary = "This is a test summary — with an em dash."
    pdf = generator.generate(_make_report(summary))
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.endswith(b"%%EOF\n")
    # The PDF body should contain ``--`` (the em-dash
    # replacement) rather than the original glyph.
    # We can't grep the PDF body for the em-dash directly
    # because the generator escapes it, but the absence of
    # a crash is the regression pin.
    assert b"--" in pdf


@pytest.mark.parametrize(
    "glyph, replacement",
    [
        ("\u2014", "--"),     # em dash
        ("\u2013", "-"),      # en dash
        ("\u2212", "-"),      # minus sign
        ("\u2018", "'"),      # left single quote
        ("\u2019", "'"),      # right single quote
        ("\u201c", '"'),      # left double quote
        ("\u201d", '"'),      # right double quote
        ("\u2026", "..."),    # ellipsis
        ("\u00a0", " "),      # non-breaking space
        ("\u2022", "*"),      # bullet
    ],
)
def test_unicode_punctuation_normalized(
    generator,
    glyph: str,
    replacement: str,
) -> None:
    """Common Unicode punctuation is mapped to ASCII
    equivalents via the normalizer in ``_pdf_escape``.
    """
    escaped = generator._pdf_escape(f"a {glyph} b")
    # The replacement should appear in the escaped text.
    assert replacement in escaped, (
        f"Expected {repr(replacement)} in escaped output for "
        f"glyph {repr(glyph)}; got {escaped!r}"
    )
    # The original glyph should NOT appear.
    assert glyph not in escaped


def test_unknown_unicode_falls_back_to_question_mark(
    generator,
) -> None:
    """Characters outside the WinAnsiEncoding range that
    don't have a mapping (e.g. CJK, emoji) are replaced
    with ``?`` rather than crashing.

    This is the second line of defence: even if a future
    LLM emits a glyph we didn't map, the generator
    produces a valid (if visually degraded) PDF instead
    of 500-ing.
    """
    # ``\u4e2d\u6587`` is Chinese for "Chinese language".
    # No reasonable biomedical summary would contain this,
    # but we want graceful degradation just in case.
    escaped = generator._pdf_escape("text \u4e2d\u6587 more text")
    assert "?" in escaped
    # The ASCII parts still come through.
    assert "text" in escaped
    assert "more text" in escaped


# ---------------------------------------------------------------------------
# PDF text-object escapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("(", "\\("),
        (")", "\\)"),
        ("\\", "\\\\"),
        ("(", "\\("),
        ("a)b(c\\d", "a\\)b\\(c\\\\d"),
    ],
)
def test_pdf_text_object_escapes(
    generator,
    raw: str,
    expected: str,
) -> None:
    """PDF text-object strings are parenthesised; the three
    characters that must be escaped (``\\``, ``(``, ``)``)
    get a backslash prefix.
    """
    assert generator._pdf_escape(raw) == expected


def test_control_chars_replaced_with_space(generator) -> None:
    """Newlines / tabs / carriage returns would terminate
    the PDF text-object string prematurely. Replace them
    with spaces before encoding.
    """
    assert generator._pdf_escape("a\nb\tc\rd") == "a b c d"


# ---------------------------------------------------------------------------
# Multi-section layout
# ---------------------------------------------------------------------------


def test_summary_appears_in_pdf(generator) -> None:
    """The summary text shows up in the rendered PDF body.

    We can't easily assert exact byte positions (the layout
    is computed), but we can verify the ASCII-normalized
    summary string appears verbatim in the bytes -- this
    pins the contract that the generator actually writes
    the user's text, not just metadata.
    """
    text = "Tau phosphorylation drives neurofibrillary tangle pathology."
    pdf = generator.generate(_make_report(text))
    # The escaped summary (no special chars in this string)
    # should appear as a substring of the content stream.
    # The generator writes ``(text) Tj`` in the content stream.
    assert b"Tau phosphorylation drives neurofibrillary" in pdf


def test_citation_appears_in_pdf(generator) -> None:
    """The citation list shows up in the rendered PDF body
    (numbered 1..N). Pin this so a future contributor
    can't silently drop the citations section.
    """
    pdf = generator.generate(
        _make_report("Short summary."),
    )
    # The title (APA citation uses it) appears in the PDF
    # body. We use a unique substring to avoid false matches.
    assert b"Alzheimer" in pdf


def test_limitations_and_future_work_appear_in_pdf(generator) -> None:
    """Both ancillary sections (limitations + future work)
    show up in the PDF body, prefixed with their section
    headings.
    """
    pdf = generator.generate(
        _make_report("Short summary."),
    )
    assert b"Limitations" in pdf
    assert b"Future Work" in pdf
    # The fixture strings we used in ``_make_report``.
    assert b"Sample size" in pdf
    assert b"larger cohort" in pdf


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_generate_is_deterministic(generator) -> None:
    """Same input -> same bytes. The generator is hand-rolled
    with no time, no randomness, no LLM. Two consecutive
    ``generate()`` calls on the same report produce
    byte-identical PDFs (modulo the layout, which is itself
    deterministic given the page width).
    """
    report = _make_report("Deterministic test.")
    pdf1 = generator.generate(report)
    pdf2 = generator.generate(report)
    assert pdf1 == pdf2


def test_generate_handles_long_summary_without_crashing(
    generator,
) -> None:
    """A 100x-repeated summary renders without crashing.
    The content stream can get large but the generator
    is a sequential writer with no fixed-size buffers.
    """
    text = "This is a sentence. " * 100
    pdf = generator.generate(_make_report(text))
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.endswith(b"%%EOF\n")