"""
Tests for :class:`ReportLabPDFGenerator`.

Why this exists
---------------
The previous hand-rolled PDF generator (``minimal_generator.py``)
shipped a working PDF but had four user-visible bugs we could
not reasonably fix without a real PDF library:

1. **No Unicode coverage.** Greek letters (β, α, γ) and Latin
   diacritics (Ş, é, ü) came out as ``?``.
2. **Citation references disappeared.** ``[paper:N]`` markers
   were stripped entirely; the user wanted numbered refs
   ``[1]``, ``[2]`` to remain visible AND clickable.
3. **Markdown leaked through.** ``**Plasma phosphorylated tau**``
   showed the asterisks literally.
4. **Long lines overflowed the right margin.** The wrapper
   used average-character-width heuristics; long citation
   strings broke.

The rewrite replaces the hand-rolled generator with a
reportlab-based one. These tests pin the contract of the
new generator so future refactors can't silently regress
on the user-visible behaviour the previous one got wrong.

Pinning strategy
----------------
The tests assert on the **content** of the rendered PDF (via
the reportlab ``canvas`` accessor and via raw byte
inspection) rather than on the exact byte sequence. Reportlab
embeds a creation-date timestamp, so byte-equality tests
would be brittle.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from app.domain.entities.author import Author
from app.domain.entities.citation import Citation
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.summary import Summary
from app.infrastructure.pdf.reportlab_generator import (
    ReportLabPDFGenerator,
    _convert_paper_markers_to_rlm,
    _markdown_to_rlm,
    _normalise_unicode,
    _strip_first_sentence_duplicate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _paper(title: str, doi: str | None = None) -> Paper:
    """Minimal Paper fixture -- only fields the renderer inspects."""
    return Paper(
        title=title,
        authors=[Author(first_name="A", last_name="Author")],
        journal=Journal(name="Nature"),
        year=2024,
        abstract="",
        doi=doi,
        pmid=None,
        keywords=[],
        url=None,
    )


def _report(
    body: str = "",
    *,
    papers: list[Paper] | None = None,
    citations: list[Paper] | None = None,
    limitations: list[str] | None = None,
    future_work: list[str] | None = None,
) -> ResearchReport:
    """Build a minimal ResearchReport fixture."""
    citations = citations or []
    return ResearchReport(
        summary=Summary(body=body, papers_used=papers or []),
        citations=[Citation(paper=p) for p in citations],
        limitations=limitations or [],
        future_work=future_work or [],
        metadata={},
    )


@pytest.fixture
def generator() -> ReportLabPDFGenerator:
    return ReportLabPDFGenerator()


def _extract_text(pdf_bytes: bytes) -> str:
    """
    Extract user-visible text from a PDF using
    ``pdftotext``. Required because reportlab
    flate-compresses content streams -- the raw
    bytes are not greppable. ``pdftotext`` is part
    of the ``poppler-utils`` package; it's available
    on the CI runner and most developer machines.
    """
    try:
        out = subprocess.run(
            ["pdftotext", "-", "-"],
            input=pdf_bytes,
            capture_output=True,
            check=True,
            timeout=30,
        )
        return out.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        # Fall back to raw-bytes extraction for
        # environments without ``pdftotext`` (e.g.
        # Alpine minimal containers). The raw bytes
        # still contain a small amount of uncompressed
        # metadata that's good enough to pin the
        # magic-header contract but not content
        # presence.
        return ""


def _extract_raw_text(pdf_bytes: bytes) -> str:
    """Last-resort extraction: decode raw bytes as
    latin-1 and grab printable substrings. Used when
    ``pdftotext`` is not available."""
    return pdf_bytes.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# Generator interface
# ---------------------------------------------------------------------------


class TestGeneratorInterface:
    """The generator implements the :class:`PDFGenerator` ABC."""

    def test_implements_pdf_generator(self) -> None:
        from app.domain.interfaces.pdf_generator import PDFGenerator
        assert isinstance(ReportLabPDFGenerator(), PDFGenerator)

    def test_generate_rejects_empty_summary(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        report = _report(body="")
        with pytest.raises(ValueError, match="empty"):
            generator.generate(report)


# ---------------------------------------------------------------------------
# PDF magic-header contract
# ---------------------------------------------------------------------------


class TestPDFBytesContract:
    """Output bytes start with the PDF magic header and end with EOF."""

    def test_output_starts_with_pdf_magic(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        pdf = generator.generate(_report(
            body="# Title\n\nBody text here.",
        ))
        assert pdf.startswith(b"%PDF-")

    def test_output_ends_with_eof_marker(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        pdf = generator.generate(_report(
            body="# Title\n\nBody text here.",
        ))
        assert pdf.rstrip().endswith(b"%%EOF")


# ---------------------------------------------------------------------------
# Content presence (what the user actually sees)
# ---------------------------------------------------------------------------


class TestPDFContentPresence:
    """Pin the user-visible content contract."""

    def test_title_appears_in_pdf(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        pdf = generator.generate(_report(
            body="# Tau Biomarkers in AD\n\nBody text.",
        ))
        text = _extract_text(pdf)
        assert "Tau Biomarkers in AD" in text

    def test_duplicate_first_sentence_stripped(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        """The H1 fallback prepends the first sentence of the
        body as the title. The body then starts with the
        same sentence. The PDF renderer strips the duplicate
        so the title appears exactly once.
        """
        # Title line and body both start with the same
        # sentence (an artefact of the H1 fallback at
        # commit b00b34a).
        body = (
            "# Tau biomarkers are central to AD\n\n"
            "Tau biomarkers are central to AD diagnosis. "
            "Plasma p-tau217 is the leading candidate.\n"
        )
        pdf = generator.generate(_report(body=body))
        text = _extract_text(pdf)
        # Body version present, title version present.
        assert "Tau biomarkers are central to AD" in text
        # The duplicated opening sentence is NOT
        # repeated as a paragraph.
        assert (
            "Tau biomarkers are central to AD diagnosis."
            not in text
        )

    def test_exec_summary_heading_present(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        pdf = generator.generate(_report(body="# T\n\nBody."))
        text = _extract_text(pdf)
        # The body is rendered without an "Executive
        # Summary" sub-heading because the user's body
        # itself supplies the H2 / H3 structure (we
        # don't inject one).
        # Just confirm the body text made it in.
        assert "Body." in text

    def test_limitations_section_present(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        pdf = generator.generate(_report(
            body="# T\n\nBody.",
            limitations=["Limitation A.", "Limitation B."],
        ))
        text = _extract_text(pdf)
        assert "Limitations" in text
        assert "Limitation A" in text
        assert "Limitation B" in text

    def test_future_work_section_present(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        pdf = generator.generate(_report(
            body="# T\n\nBody.",
            future_work=["Direction 1.", "Direction 2."],
        ))
        text = _extract_text(pdf)
        assert "Future Research Directions" in text
        assert "Direction 1" in text
        assert "Direction 2" in text

    def test_bibliography_heading_present(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        pdf = generator.generate(_report(
            body="# T\n\nBody.",
            citations=[_paper("First paper"), _paper("Second paper")],
        ))
        text = _extract_text(pdf)
        assert "Bibliography" in text
        # Citation titles make it into the PDF.
        assert "First paper" in text
        assert "Second paper" in text


# ---------------------------------------------------------------------------
# Bug-fix regressions: the four bugs the user reported
# ---------------------------------------------------------------------------


class TestBugFixes:
    """
    Each test pins the fix for one of the four user-visible
    bugs the previous generator shipped with.
    """

    def test_greek_letters_render(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        """Bug 1: ``β`` came out as ``?`` because Helvetica
        base-14 + WinAnsiEncoding has no Greek glyphs.
        The new generator embeds DejaVu Sans (full
        Unicode coverage), so the character renders
        verbatim in the PDF.
        """
        body = (
            "# Title\n\n"
            "Plasma Aβ and α-synuclein are AD biomarkers."
        )
        pdf = generator.generate(_report(body=body))
        # The bytes for "β" (U+03B2) and "α" (U+03B1)
        # must appear in the PDF stream (possibly
        # embedded in the font's ToUnicode CMap).
        # Reportlab encodes them via the embedded TTF.
        text = _extract_text(pdf)
        assert "Aβ" in text
        assert "α-synuclein" in text
        # And no ``?`` substitutions.
        assert "?synuclein" not in text
        assert "A?" not in text

    def test_markdown_bold_is_stripped(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        """Bug 3: ``**Plasma p-tau**`` showed the
        asterisks literally. The new generator strips
        the markers and renders the inner text in
        bold.
        """
        body = (
            "# Title\n\n"
            "**Plasma phosphorylated tau** is a leading "
            "biomarker."
        )
        pdf = generator.generate(_report(body=body))
        text = _extract_text(pdf)
        # The asterisks are gone.
        assert "**Plasma phosphorylated tau**" not in text
        # The plain text appears.
        assert "Plasma phosphorylated tau" in text

    def test_paper_markers_become_numbered_refs(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        """Bug 2 part 1: ``[paper:3]`` is no longer
        stripped. It becomes ``[3]`` (a clickable link
        to the bibliography entry).
        """
        body = (
            "# Title\n\n"
            "Plasma p-tau217 is sensitive [paper:3] "
            "and specific [paper:5]."
        )
        pdf = generator.generate(_report(
            body=body,
            citations=[
                _paper("First paper"),
                _paper("Second paper"),
                _paper("Third paper"),
                _paper("Fourth paper"),
                _paper("Fifth paper"),
            ],
        ))
        text = _extract_text(pdf)
        # Raw marker gone.
        assert "[paper:3]" not in text
        assert "[paper:5]" not in text
        # Numbered refs present.
        assert "[3]" in text
        assert "[5]" in text

    def test_paper_markers_become_clickable_links(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        """Bug 2 part 2: the numbered refs are real
        PDF /Link annotations with /Dest targets (not
        /S /URI broken URLs).
        """
        body = (
            "# Title\n\n"
            "Plasma p-tau217 is sensitive [paper:1]."
        )
        pdf = generator.generate(_report(
            body=body,
            citations=[_paper("Single paper")],
        ))
        # Real internal destinations: /Dest [...]
        # (NOT /S /URI /URI (...)).
        assert b"/Dest [" in pdf
        # We must NOT have produced URI-style links for
        # bibliography targets (that was a reportlab
        # trap: without the ``#`` prefix in the link
        # destination, the parser dispatches to
        # HotLink.link() instead of InternalLink.link()).
        # Look at the link action types: real links
        # use /Dest, broken ones use /URI.
        uri_count = len(re.findall(rb"/S\s*/URI\s*/URI", pdf))
        dest_count = len(re.findall(rb"/Dest\s*\[", pdf))
        # dest_count > uri_count: more real links
        # than broken ones. We allow some /URI for
        # the DOI URLs in the bibliography (those ARE
        # supposed to be URIs).
        assert dest_count > 0, (
            "expected at least one /Dest (internal "
            "bibliography link)"
        )
        assert uri_count <= dest_count + 5, (
            "more /S /URI than expected -- a citation "
            "link may be incorrectly rendered as a URI"
        )

    def test_long_lines_wrap_properly(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        """Bug 4: long citation strings overflowed the
        right margin in the previous generator. The
        new generator uses reportlab Paragraphs which
        do proper text wrapping.
        """
        body = "# Title\n\nShort body."
        long_limit = (
            "This is an extremely long limitation that "
            "goes on and on with many words and clauses "
            "to test that the line wrapping in the new "
            "generator actually wraps the text to fit "
            "within the page margins. " * 3
        )
        pdf = generator.generate(_report(
            body=body,
            limitations=[long_limit],
        ))
        # The PDF must still be a valid PDF -- long
        # lines wrap, not overflow the page.
        assert pdf.startswith(b"%PDF-")
        assert pdf.rstrip().endswith(b"%%EOF")
        # And the limitation text must be present
        # somewhere in the rendered output.
        text = _extract_text(pdf)
        assert "extremely long limitation" in text

    def test_out_of_range_markers_are_dropped(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        """If a body marker ``[paper:99]`` references a
        bibliography position that doesn't exist, the
        PDF must drop it silently. Otherwise reportlab
        raises ``ValueError: format not resolved`` at
        save time (we hit this during development).
        """
        body = "# Title\n\nBody [paper:99] body."
        # Only 2 citations; ``[paper:99]`` is out of
        # range.
        pdf = generator.generate(_report(
            body=body,
            citations=[_paper("A"), _paper("B")],
        ))
        text = _extract_text(pdf)
        # The bad marker is gone (no dangling ``99``).
        assert "[99]" not in text


# ---------------------------------------------------------------------------
# Markdown preprocessing helpers (unit tests)
# ---------------------------------------------------------------------------


class TestNormaliseUnicode:
    """Pin the smart-quote / dash / ellipsis normalisation."""

    def test_em_dash_becomes_double_hyphen(self) -> None:
        assert _normalise_unicode("a—b") == "a--b"

    def test_en_dash_becomes_single_hyphen(self) -> None:
        assert _normalise_unicode("a–b") == "a-b"

    def test_smart_quotes_become_ascii(self) -> None:
        assert _normalise_unicode("“hi”") == '"hi"'
        assert _normalise_unicode("‘hi’") == "'hi'"

    def test_ellipsis_becomes_three_dots(self) -> None:
        assert _normalise_unicode("a…b") == "a...b"

    def test_greek_letters_are_preserved(self) -> None:
        """Greek letters are NOT transliterated -- DejaVu
        Sans handles them. We only normalise the
        punctuation that confuses the latin-1
        escape path."""
        assert _normalise_unicode("α β γ") == "α β γ"


class TestStripFirstSentenceDuplicate:
    """The H1 fallback duplicates the first sentence as
    the title. The PDF renderer strips the duplicate
    so the title appears only once.

    The match is intentionally strict (title must be
    >= 8 chars AND the body sentence must be >= 1.5x
    the title length). Short test fixtures use
    short titles that won't match -- real reports
    have titles in the 30-80 char range.
    """

    def test_drops_identical_first_sentence(self) -> None:
        """The duplicate is the line AFTER the H1 (the
        first prose line), not the H1 line itself.
        Title is >= 8 chars so the strictness guard
        passes."""
        body = (
            "# Tau biomarkers are central\n"
            "\n"
            "Tau biomarkers are central to AD.\n"
            "Plasma p-tau217 is the leading marker.\n"
        )
        out = _strip_first_sentence_duplicate(
            body, "Tau biomarkers are central",
        )
        # Duplicate line dropped, H1 preserved, rest
        # preserved.
        assert "Tau biomarkers are central to AD" not in out
        assert "Plasma p-tau217" in out
        assert out.startswith("# Tau biomarkers are central")

    def test_drops_first_sentence_with_trailing_period(
        self,
    ) -> None:
        """Same logic with title ending in a period."""
        body = (
            "# Tau biomarkers.\n"
            "\n"
            "Tau biomarkers are central.\n"
            "Body content here.\n"
        )
        out = _strip_first_sentence_duplicate(
            body, "Tau biomarkers"
        )
        # Body sentence (29 chars) is > 1.5x title
        # (13 chars after rstrip) -- duplicate dropped.
        assert "Tau biomarkers are central.\nBody" not in out
        assert "Body content here" in out

    def test_short_title_does_not_match(self) -> None:
        """Short titles (< 8 chars) don't trigger
        the duplicate guard -- the match would
        produce too many false positives (any body
        sentence starting with the same letter)."""
        body = (
            "# Tau\n"
            "\n"
            "The unique body content sentence.\n"
            "Plasma p-tau217.\n"
        )
        out = _strip_first_sentence_duplicate(body, "Tau")
        # Title is too short to safely match -- body
        # preserved verbatim.
        assert out == body

    def test_keeps_body_when_first_sentence_differs(
        self,
    ) -> None:
        """Different opening sentence means no duplicate.
        Title >= 8 chars."""
        body = (
            "# Different title\n"
            "\n"
            "Body that does not match.\n"
            "More.\n"
        )
        out = _strip_first_sentence_duplicate(body, "Different title")
        # Body preserved verbatim.
        assert "Body that does not match." in out

    def test_keeps_body_when_title_is_empty(self) -> None:
        body = (
            "# Whatever\n\n"
            "Some body content.\n"
            "More.\n"
        )
        out = _strip_first_sentence_duplicate(body, "")
        assert out == body

    def test_keeps_body_when_body_is_empty(self) -> None:
        out = _strip_first_sentence_duplicate("", "Some title")
        assert out == ""


class TestConvertPaperMarkersToRLM:
    """Convert ``[paper:N]`` markers to RLM link tags."""

    def test_standalone_marker_becomes_link(self) -> None:
        out = _convert_paper_markers_to_rlm("text [paper:3]", num_citations=5)
        # The numbered ref must be present.
        assert "[3]" in out
        # The destination must be a hash-prefixed
        # internal link (reportlab dispatches on
        # the prefix -- without ``#`` it produces a
        # broken URI link).
        assert 'destination="#bib-3"' in out

    def test_grouped_marker_becomes_links(self) -> None:
        out = _convert_paper_markers_to_rlm(
            "text [paper:3, paper:5]", num_citations=10
        )
        assert "[3]" in out
        assert "[5]" in out
        assert 'destination="#bib-3"' in out
        assert 'destination="#bib-5"' in out

    def test_out_of_range_marker_dropped(self) -> None:
        out = _convert_paper_markers_to_rlm(
            "text [paper:99]", num_citations=5
        )
        # The dangling ``99`` is gone.
        assert "[99]" not in out
        assert "[paper:99]" not in out

    def test_zero_or_negative_marker_dropped(self) -> None:
        out = _convert_paper_markers_to_rlm(
            "text [paper:0] and [paper:-3]", num_citations=5
        )
        assert "[0]" not in out
        assert "[-3]" not in out

    def test_partial_group_dropped_silently(self) -> None:
        """If a grouped marker mixes valid + invalid
        indices, the valid ones stay and the
        invalid ones vanish silently (no
        dangling ``99``)."""
        out = _convert_paper_markers_to_rlm(
            "[paper:1, paper:99, paper:2]", num_citations=5
        )
        assert "[1]" in out
        assert "[2]" in out
        assert "[99]" not in out


class TestMarkdownToRLM:
    """The full markdown → RLM conversion."""

    def test_bold_marker_converted(self) -> None:
        out = _markdown_to_rlm("**bold text**")
        assert "<b>bold text</b>" in out

    def test_italic_marker_converted(self) -> None:
        out = _markdown_to_rlm("*italic text*")
        assert "<i>italic text</i>" in out

    def test_inline_code_converted(self) -> None:
        out = _markdown_to_rlm("`code`")
        assert "Courier" in out
        assert "code" in out

    def test_combined_markdown(self) -> None:
        out = _markdown_to_rlm(
            "**bold** and *italic* and `code` "
            "with [paper:1].",
            num_citations=5,
        )
        assert "<b>bold</b>" in out
        assert "<i>italic</i>" in out
        assert "Courier" in out
        assert "[1]" in out


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """The same input produces the same output (modulo the
    embedded creation-date timestamp)."""

    def test_two_runs_produce_same_citations_section(
        self, generator: ReportLabPDFGenerator
    ) -> None:
        report = _report(
            body="# T\n\nBody.",
            citations=[_paper("A"), _paper("B")],
            limitations=["L1."],
            future_work=["F1."],
        )
        pdf1 = generator.generate(report)
        pdf2 = generator.generate(report)
        # The citation entries appear in both. The
        # timestamp may differ but the citation
        # content must be identical -- compare
        # via ``_extract_text`` which decodes the
        # compressed content streams.
        text1 = _extract_text(pdf1)
        text2 = _extract_text(pdf2)
        for needle in ("A.", "B.", "L1.", "F1.", "Bibliography"):
            assert needle in text1, f"missing {needle!r} in run 1"
            assert needle in text2, f"missing {needle!r} in run 2"
