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

    The generator only reads ``summary.body``; citations,
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
        summary=Summary(body=text, papers_used=[paper]),
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


"""
Tests for the new PDF format additions.

Background
----------
The ``MinimalPDFGenerator`` historically embedded
``[paper:N]`` markers from the LLM output verbatim in the
PDF. That made the rendered document look like raw
markdown -- citations like ``...research cohorts [paper:3,
paper:13].`` appeared as bracketed markers in the prose,
with the actual citation list at the bottom of the page.

The fix: strip ``[paper:N]`` markers from the prose before
rendering. The citations list still provides the reader-to-
paper mapping -- the markers in the prose were redundant.

Tests pin:
1. Standalone ``[paper:N]`` markers are stripped.
2. Grouped ``[paper:N, paper:M, ...]`` markers are stripped.
3. Malformed ``[paper:abc]`` markers are NOT stripped
   (they pass through unchanged; this is intentional).
4. Trailing whitespace and punctuation are preserved
   cleanly (no double spaces or dangling brackets).
5. The H1 title line is extracted as the page heading
   instead of appearing inline in the body.
6. The citations list still shows up at the bottom of
   the page (so the reader can find the references).
"""


class TestPDFPaperMarkerStrip:
    """Pin the ``_strip_paper_markers`` helper."""

    def test_strips_standalone_marker(self, generator):
        """A single ``[paper:N]`` is removed cleanly.

        ``"cohorts [paper:3]."`` becomes ``"cohorts."`` --
        the surrounding text and the trailing period are
        preserved.
        """
        assert generator._strip_paper_markers(
            "cohorts [paper:3]."
        ) == "cohorts."

    def test_strips_grouped_marker(self, generator):
        """``[paper:N, paper:M]`` is removed cleanly."""
        assert generator._strip_paper_markers(
            "cohorts [paper:3, paper:13]."
        ) == "cohorts."

    def test_strips_three_way_group(self, generator):
        """``[paper:N, paper:M, paper:K]`` is removed cleanly.

        A real-world example: the LLM often emits three or
        four references in a single group when multiple
        papers support one claim.
        """
        assert generator._strip_paper_markers(
            "cohorts [paper:3, paper:13, paper:19]."
        ) == "cohorts."

    def test_does_not_strip_malformed_marker(self, generator):
        """``[paper:abc]`` (non-numeric) passes through unchanged.

        The regex requires ``\d+``, so non-numeric content
        is never matched. ``[paper:abc]`` is preserved
        exactly as the LLM wrote it. This is intentional --
        we shouldn't silently rewrite malformed output.
        """
        assert generator._strip_paper_markers(
            "cohorts [paper:abc]."
        ) == "cohorts [paper:abc]."

    def test_preserves_punctuation_around_stripped_marker(self, generator):
        """Trailing punctuation (``.,``, ``;``, ``:``) stays
        in place after the marker is stripped.

        Before stripping: ``"cohorts [paper:3]; see ref [4]."``
        After stripping:  ``"cohorts; see ref [4]."``
        """
        assert generator._strip_paper_markers(
            "cohorts [paper:3]; see ref [4]."
        ) == "cohorts; see ref [4]."

    def test_collapses_double_spaces_left_by_strip(self, generator):
        """When a marker was surrounded by spaces (``"a [paper:3] b"``)
        the strip would leave ``"a  b"`` -- collapse to ``"a b"``.
        """
        assert generator._strip_paper_markers(
            "a [paper:3] b"
        ) == "a b"

    def test_preserves_newlines(self, generator):
        """The strip operates within lines and doesn't merge
        paragraphs. Newlines between paragraphs are kept.
        """
        assert generator._strip_paper_markers(
            "first [paper:3]\nsecond [paper:4]"
        ) == "first\nsecond"

    def test_no_markers_is_noop(self, generator):
        """A string with no ``[paper:N]`` markers is returned
        unchanged (modulo whitespace collapsing, which
        shouldn't trigger here because there's no marker
        for it to leave dangling spaces around).
        """
        assert generator._strip_paper_markers(
            "Plain text with no markers."
        ) == "Plain text with no markers."


class TestPDFReportTitle:
    """Pin the title-extraction logic in ``generate``."""

    def test_h1_heading_appears_as_page_title(self, generator):
        """A body starting with ``# Some Title`` puts that
        title in the page heading, NOT inline in the body.
        """
        from tests.unit.test_minimal_pdf_generator import (
            _make_report,
        )

        body = "# Tau Biomarkers in AD: A Synthesis\n\nFull body here."
        pdf = generator.generate(_make_report(body))
        # The title appears in the content stream (PDF
        # escapes special chars but plain ASCII passes
        # through unchanged).
        assert b"Tau Biomarkers in AD: A Synthesis" in pdf

    def test_title_line_not_repeated_in_body(self, generator):
        """The title is shown ONCE at the top, not twice
        (once as the heading and once inline in the body).
        """
        from tests.unit.test_minimal_pdf_generator import (
            _make_report,
        )

        body = "# My Title\n\nFirst paragraph."
        pdf = generator.generate(_make_report(body))
        # Count occurrences of "My Title" in the PDF -- should
        # be exactly 1.
        assert pdf.count(b"My Title") == 1

    def test_falls_back_to_generic_label_when_no_h1(self, generator):
        """If the body has no leading ``# `` heading, the
        page heading is the generic ``Biomedical Research
        Report`` label (same behaviour as before the change).
        """
        from tests.unit.test_minimal_pdf_generator import (
            _make_report,
        )

        body = "Just a body with no title heading."
        pdf = generator.generate(_make_report(body))
        # The generic title appears; the body content also
        # appears.
        assert b"Biomedical Research Report" in pdf
        assert b"Just a body with no title heading." in pdf


class TestPDFCitationSectionStillWorks:
    """Pin that the citations list survives the strip.

    The whole point of stripping markers from the prose is
    that the citations list is the canonical reader-to-
    paper mapping. If the strip accidentally nuked the
    citations section too, the reader would have no way to
    look up the references -- so this test guards against
    that regression.
    """

    def test_citations_list_present_in_pdf(self, generator):
        """The numbered citations list at the bottom of the
        page is still rendered.
        """
        from tests.unit.test_minimal_pdf_generator import (
            _make_report,
        )

        body = "Cohort study with citation [paper:1]."
        pdf = generator.generate(_make_report(body))
        # The fixture's citation uses paper.title="Tau
        # phosphorylation in Alzheimer's disease" which
        # appears in the APA-formatted citation list. The
        # number "1." prefixes the entry.
        assert b"1." in pdf
        assert b"Tau phosphorylation" in pdf


class TestPDFLimitationsAndFutureWorkStripped:
    """Pin that the Limitations / Future Work lists also
    have their markers stripped."""

    def test_limitations_marker_stripped(self, generator):
        """A limitation with ``[paper:N]`` renders without
        the marker.
        """
        from app.domain.entities.author import Author
        from app.domain.entities.journal import Journal
        from app.domain.entities.paper import Paper
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_report import (
            ResearchReport,
        )

        paper = Paper(
            title="P",
            authors=[Author(first_name="A", last_name="B")],
            journal=Journal(name="J"),
            year=2024,
            abstract="",
            doi="10.1/x",
        )
        report = ResearchReport(
            summary=Summary(body="body", papers_used=[paper]),
            citations=[],
            limitations=[
                "Sample size is small [paper:3]."
            ],
            future_work=[],
            metadata={},
        )
        pdf = generator.generate(report)
        # The marker is gone; the surrounding prose is kept.
        assert b"Sample size is small." in pdf
        assert b"[paper:3]" not in pdf

    def test_future_work_marker_stripped(self, generator):
        """A future-work bullet with ``[paper:N]`` renders
        without the marker.
        """
        from app.domain.entities.author import Author
        from app.domain.entities.journal import Journal
        from app.domain.entities.paper import Paper
        from app.domain.entities.summary import Summary
        from app.domain.entities.research_report import (
            ResearchReport,
        )

        paper = Paper(
            title="P",
            authors=[Author(first_name="A", last_name="B")],
            journal=Journal(name="J"),
            year=2024,
            abstract="",
            doi="10.1/x",
        )
        report = ResearchReport(
            summary=Summary(body="body", papers_used=[paper]),
            citations=[],
            limitations=[],
            future_work=[
                "Replicate in larger cohort [paper:5]."
            ],
            metadata={},
        )
        pdf = generator.generate(report)
        assert b"Replicate in larger cohort." in pdf
        assert b"[paper:5]" not in pdf
"""
Tests for multi-page PDF output.

Background
----------
The minimal generator historically produced single-page PDFs
with content silently truncated when the body exceeded the
available vertical space (the no-pagination limitation).
This was acceptable when reports were short (1-2 paragraphs)
but breaks for long reports: Limitations and Future Work
sections would simply be missing from the rendered PDF.

The new layout: when the y-coordinate crosses the bottom
margin, the current page is closed and a fresh page starts.
This produces a multi-page PDF where every ``page_lines``
entry from the layout phase renders somewhere in the
output.

Tests pin:
  1. Short reports stay on a single page (no regression
     for the common case).
  2. Long reports produce multiple pages with ``/Count``
     matching the number of pages emitted.
  3. Every page has a content stream that renders the
     expected body content (no silent loss).
  4. Limitations and Future Work sections are present in
     multi-page output (the original motivation for the
     fix).
  5. The xref offsets match the actual byte positions of
     each object -- a regression here would crash PDF
     readers.
"""

import re

from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.summary import Summary


def _paper(title="P", doi="10.1/x") -> Paper:
    return Paper(
        title=title,
        authors=[Author(first_name="A", last_name="B")],
        journal=Journal(name="J"),
        year=2024,
        abstract="",
        doi=doi,
    )


def _make_custom_report(
    body: str,
    citations: list | None = None,
    limitations: list | None = None,
    future_work: list | None = None,
) -> ResearchReport:
    """Build a report with explicit sections, for multi-page
    tests. The default ``_make_report`` in the test file
    only takes a body string; this lets the multi-page
    tests assert about Limitations/Future Work sections
    without re-creating the fixture for every case.
    """
    paper = _paper()
    return ResearchReport(
        summary=Summary(body=body, papers_used=[paper]),
        citations=citations if citations is not None else [],
        limitations=limitations if limitations is not None else [],
        future_work=future_work if future_work is not None else [],
        metadata={"model": "stub"},
    )


def _count_pages(pdf: bytes) -> int:
    """Count the number of page dicts in the PDF.

    Walks the ``/Type /Page`` declarations (excluding
    ``/Type /Pages``). Each page produces exactly one such
    dict.
    """
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def _count_kids(pdf: bytes) -> int:
    """Parse the /Count field from the Pages collection
    object. Should equal the number of page dicts.
    """
    m = re.search(rb"/Count\s+(\d+)", pdf)
    if not m:
        return 0
    return int(m.group(1))


class TestPDFSinglePageShortReport:
    """A short report fits on one page -- no regression
    vs. the pre-pagination behaviour.
    """

    def test_short_body_is_single_page(self, generator):
        pdf = generator.generate(
            _make_custom_report("Short body.")
        )
        assert _count_pages(pdf) == 1
        assert _count_kids(pdf) == 1

    def test_short_body_keeps_sections_together(self, generator):
        """Title, exec summary, citations, limitations, and
        future work all stay on page 1 if everything fits.
        """
        body = "Short body."
        citations = [_paper(title=f"Citation {i}") for i in range(5)]
        limitations = ["Lim A", "Lim B"]
        future_work = ["FW A", "FW B"]
        pdf = generator.generate(
            _make_custom_report(
                body,
                citations=citations,
                limitations=limitations,
                future_work=future_work,
            )
        )
        assert _count_pages(pdf) == 1
        # Each section's content is present somewhere in the PDF.
        assert b"Biomedical Research Report" in pdf
        assert b"Executive Summary" in pdf
        assert b"Citations" in pdf
        assert b"Limitations" in pdf
        assert b"Future Work" in pdf


class TestPDFMultiPageLongReport:
    """A long report spans multiple pages."""

    def test_long_body_produces_multiple_pages(self, generator):
        """A body of ~200 sentences wraps to multiple pages.

        The exact number depends on the wrap width, but for
        Helvetica 11pt with 1-inch margins on letter paper,
        the body comfortably exceeds one page.
        """
        long_body = "This is a sentence in a long report. " * 200
        pdf = generator.generate(
            _make_custom_report(long_body)
        )
        page_count = _count_pages(pdf)
        assert page_count >= 2, (
            f"long body should produce >= 2 pages; got {page_count}"
        )
        assert _count_kids(pdf) == page_count

    def test_every_page_has_a_content_stream(self, generator):
        """Every page dict must have a ``/Contents`` pointer
        to a content-stream object. A missed page would
        leave the reader with a blank page at the end.
        """
        long_body = "This is a sentence in a long report. " * 200
        pdf = generator.generate(
            _make_custom_report(long_body)
        )
        contents_count = len(re.findall(rb"/Contents\s+\d+\s+0\s+R", pdf))
        page_count = _count_pages(pdf)
        assert contents_count == page_count, (
            f"expected {page_count} /Contents pointers; got {contents_count}"
        )

    def test_limitations_appear_in_long_report(self, generator):
        """The original motivation for pagination: with a
        long body, the Limitations section MUST appear in
        the PDF (previously truncated silently).
        """
        long_body = "This is a sentence in a long report. " * 200
        pdf = generator.generate(
            _make_custom_report(
                long_body,
                limitations=["Real Limitation"],
            )
        )
        assert b"Limitations" in pdf
        assert b"Real Limitation" in pdf

    def test_future_work_appears_in_long_report(self, generator):
        """Future Work section MUST appear even when the
        body is long.
        """
        long_body = "This is a sentence in a long report. " * 200
        pdf = generator.generate(
            _make_custom_report(
                long_body,
                future_work=["Real Future Work"],
            )
        )
        assert b"Future Work" in pdf
        assert b"Real Future Work" in pdf

    def test_xref_offsets_match_actual_object_positions(self, generator):
        """The xref entries must point to the actual byte
        positions of each object in the PDF. A regression
        here would crash strict readers (the ``xref num N
        not found`` error from ``pdftotext``).
        """
        long_body = "This is a sentence in a long report. " * 200
        pdf = generator.generate(
            _make_custom_report(long_body)
        )
        # Walk every "N 0 obj" declaration and capture its
        # byte offset.
        declared: dict[int, int] = {}
        for m in re.finditer(rb"(\d+) 0 obj\n", pdf):
            declared[int(m.group(1))] = m.start()
        # Parse xref entries and check each one resolves.
        xref_match = re.search(
            rb"xref\n0 \d+\n"
            + b"0000000000 65535 f \n"
            + rb"(.*?)\ntrailer",
            pdf,
            re.DOTALL,
        )
        assert xref_match, "no xref table found"
        xref_lines = xref_match.group(1).strip().split(b"\n")
        checked = 0
        for line in xref_lines:
            parts = line.split()
            if len(parts) < 3 or parts[2] != b"n":
                continue
            offset = int(parts[0])
            matched = [
                oid for oid, off in declared.items() if off == offset
            ]
            assert matched, (
                f"xref points to offset {offset} but no object "
                f"starts there. Declared offsets: "
                f"{sorted(declared.items())}"
            )
            checked += 1
        assert checked == len(declared), (
            f"only checked {checked} of {len(declared)} objects"
        )
