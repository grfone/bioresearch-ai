"""
Tests for ``app/infrastructure/llm/title_fallback.py``.

The H1 fallback runs at synthesis-ingest time when the LLM
omits the ``# <title>`` heading. Without this fallback,
both the PDF generator and the React UI display the generic
``"Biomedical Research Report"`` label on every report.

Tests pin:
  1. ``has_h1_title`` correctly detects the presence of a
     leading H1 line.
  2. ``derive_title_from_first_sentence`` derives a useful
     title from the first sentence (handles citation markers,
     trailing punctuation, very long sentences, multi-paragraph
     bodies).
  3. ``inject_h1_fallback`` is idempotent (no-op when an H1
     is already present), prepends a derived title when
     missing, and handles empty bodies gracefully.

These tests are the contract for the fallback; if a future
refactor changes the derivation logic, the tests catch any
behaviour that breaks downstream consumers.
"""
from __future__ import annotations

from app.infrastructure.llm.title_fallback import (
    derive_title_from_first_sentence,
    has_h1_title,
    inject_h1_fallback,
)


class TestHasH1Title:
    """``has_h1_title`` detects the leading H1 line."""

    def test_empty_body_has_no_h1(self):
        assert has_h1_title("") is False

    def test_plain_prose_has_no_h1(self):
        """The live failure mode: LLM emits synthesis prose
        without any ``# `` heading.
        """
        assert (
            has_h1_title(
                "Plasma p-tau217 is a sensitive marker. "
                "The body has more text."
            )
            is False
        )

    def test_body_starting_with_h1_has_h1(self):
        """Body starting with ``# <title>`` is detected."""
        assert has_h1_title("# My Title\n\nBody text") is True

    def test_h1_after_blank_line_has_h1(self):
        """An H1 anywhere in the body counts -- the
        consumer (PDF/UI) takes the FIRST ``# `` line,
        not just the line at index 0.
        """
        body = "preamble text\n\n# Real Title\n\nBody"
        assert has_h1_title(body) is True

    def test_h2_is_not_h1(self):
        """``## `` is a subheading, not an H1. The fallback
        should still inject a title in this case (the LLM
        emitted a subheading instead of a top-level one).
        """
        body = "## Limitations\n\n- too small"
        assert has_h1_title(body) is False

    def test_hash_in_prose_is_not_h1(self):
        """A bare ``#`` in body prose isn't a heading. The
        regex requires ``# `` followed by a non-space
        character.
        """
        assert has_h1_title("counting #1 #2 #3") is False


class TestDeriveTitleFromFirstSentence:
    """``derive_title_from_first_sentence`` produces a
    useful title from the first sentence of the body."""

    def test_basic_first_sentence(self):
        out = derive_title_from_first_sentence(
            "Plasma p-tau217 is a sensitive marker. Rest."
        )
        assert out == "Plasma p-tau217 is a sensitive marker"

    def test_first_sentence_with_trailing_period(self):
        """A trailing period is consumed (the punctuation
        marks the sentence end; the title doesn't need to
        repeat it).
        """
        out = derive_title_from_first_sentence(
            "Tau biomarkers have emerged as central tools."
        )
        assert out == "Tau biomarkers have emerged as central tools"
        # No trailing period.
        assert not out.endswith(".")

    def test_first_sentence_with_exclamation(self):
        """``!`` and ``?`` also terminate the sentence."""
        out = derive_title_from_first_sentence(
            "What a finding! More text."
        )
        assert out == "What a finding"

    def test_first_sentence_with_question_mark(self):
        out = derive_title_from_first_sentence(
            "What is the best marker? Body continues."
        )
        assert out == "What is the best marker"

    def test_citation_markers_stripped_from_title(self):
        """``[paper:N]`` markers are visual noise in a title.
        The derived title must NOT include them.
        """
        out = derive_title_from_first_sentence(
            "Plasma p-tau217 is a sensitive marker [paper:1]. "
            "More text."
        )
        assert "[paper:" not in out
        assert out == "Plasma p-tau217 is a sensitive marker"

    def test_grouped_citation_markers_stripped_from_title(self):
        """Grouped ``[paper:N, paper:M]`` markers are stripped.
        """
        out = derive_title_from_first_sentence(
            "Tau biomarkers [paper:3, paper:13, paper:19] are "
            "central. More text."
        )
        assert "[paper:" not in out
        assert out == "Tau biomarkers are central"

    def test_long_sentence_truncated_to_12_words(self):
        """Sentences longer than the word cap are truncated
        cleanly. ``_MAX_TITLE_WORDS = 12``.
        """
        text = (
            "one two three four five six seven eight nine ten "
            "eleven twelve thirteen fourteen fifteen sixteen"
        )
        out = derive_title_from_first_sentence(text)
        assert len(out.split()) == 12
        assert out == (
            "one two three four five six seven eight nine ten "
            "eleven twelve"
        )

    def test_newline_breaks_sentence(self):
        """A newline ends the first sentence (common in
        multi-paragraph bodies where the LLM breaks after
        the first sentence).
        """
        out = derive_title_from_first_sentence(
            "First sentence here.\nSecond paragraph starts."
        )
        assert out == "First sentence here"

    def test_internal_whitespace_collapsed(self):
        """Runs of whitespace inside the candidate are
        collapsed to a single space.
        """
        out = derive_title_from_first_sentence(
            "First   sentence\n\n   with    spacing."
        )
        assert out == "First sentence with spacing"

    def test_no_sentence_end_uses_full_body(self):
        """A body without ``.``, ``!``, ``?``, or ``\n``
        uses the whole body as the candidate (after
        truncation).
        """
        out = derive_title_from_first_sentence(
            "A body without sentence terminators"
        )
        assert out == "A body without sentence terminators"

    def test_empty_body_returns_empty_string(self):
        """Empty input returns empty -- caller falls back
        to its default label.
        """
        assert derive_title_from_first_sentence("") == ""

    def test_body_of_only_punctuation_returns_empty(self):
        """If the first sentence is purely punctuation (no
        usable words), return empty.
        """
        out = derive_title_from_first_sentence("...")
        assert out == ""


class TestInjectH1Fallback:
    """``inject_h1_fallback`` is idempotent + prepends an H1
    derived from the first sentence when missing."""

    def test_empty_body_passes_through(self):
        """Empty body stays empty -- no synthetic H1."""
        assert inject_h1_fallback("") == ""

    def test_body_without_h1_gets_one(self):
        body = "Plasma p-tau217 is a sensitive marker. Body text."
        out = inject_h1_fallback(body)
        # H1 is the first line.
        assert out.startswith("# Plasma p-tau217 is a sensitive marker")
        # Original body is preserved below.
        assert "Plasma p-tau217 is a sensitive marker. Body text." in out

    def test_body_with_h1_is_unchanged(self):
        """When the body already starts with ``# ``, the
        fallback is a no-op -- the LLM's choice wins.
        """
        body = "# LLM's Title\n\nBody text here."
        assert inject_h1_fallback(body) == body

    def test_injected_h1_is_on_first_line(self):
        """The injected H1 is the FIRST line of the output,
        not the second or after a preamble. The PDF
        generator's H1 extractor looks at ``body_lines[0]``.
        """
        body = "First sentence ends here. Rest of body."
        out = inject_h1_fallback(body)
        first_line = out.split("\n", 1)[0]
        assert first_line.startswith("# ")

    def test_h2_is_not_treated_as_h1(self):
        """A body that starts with ``## Limitations`` (a
        subheading, not a real title) still gets the
        fallback H1 prepended. The PDF/UI extractors look
        for ``# `` (single hash) specifically, so a body
        with ``## `` as the first heading still appears
        title-less without the fallback.
        """
        body = "## Limitations\n\n- too small"
        out = inject_h1_fallback(body)
        # The injected H1 is BEFORE the H2 in the output.
        assert out.startswith("# Limitations" if False else "#")
        # Specifically: the first line is a real H1, not H2.
        assert out.split("\n", 1)[0].startswith("# ")
        # The H2 still appears in the body.
        assert "## Limitations" in out

    def test_injected_title_is_truncated(self):
        """The injected H1 stays within the word cap."""
        text = (
            "one two three four five six seven eight nine ten "
            "eleven twelve thirteen fourteen fifteen."
        )
        out = inject_h1_fallback(text)
        first_line = out.split("\n", 1)[0]
        # Strip the ``# `` prefix.
        title = first_line[2:]
        assert len(title.split()) == 12

    def test_idempotent(self):
        """Calling twice produces the same output as calling
        once (no recursion / no incremental growth).
        """
        body = "Plasma p-tau217 is a sensitive marker. Body text."
        once = inject_h1_fallback(body)
        twice = inject_h1_fallback(once)
        assert once == twice

    def test_injection_preserves_citation_markers_in_body(self):
        """The fallback doesn't touch the body -- it only
        PREPENDS the H1. Citation markers in the body
        remain intact (they're handled by the
        citation_sanitizer and the PDF's
        ``_strip_paper_markers``).
        """
        body = "Tau biomarkers [paper:1] are central. Rest."
        out = inject_h1_fallback(body)
        assert "[paper:1]" in out
        # The H1 itself doesn't contain the marker.
        first_line = out.split("\n", 1)[0]
        assert "[paper:" not in first_line

    def test_idempotent_on_h1_only_body(self):
        """A body that's ONLY the H1 (no prose below) is
        returned unchanged -- the LLM already emitted a
        title.
        """
        body = "# My Title"
        assert inject_h1_fallback(body) == body

class TestLeadingHeadingIsNotProse:
    """A leading markdown heading must not leak into the title.

    The synthesis LLM sometimes opens with a section label written
    at the wrong level -- ``### Bottom line`` where a ``# `` title
    was asked for. The heading is not the opening of a sentence, so
    including it produced titles like::

        ### Bottom line Among the supplied studies, **plasma N-terminal tau fragment 1**

    which both the PDF generator and the React UI displayed
    verbatim, raw markdown and all.
    """

    BODY = (
        "### Bottom line\n"
        "\n"
        "Among the supplied studies, **plasma N-terminal tau fragment 1** "
        "(p-tau217) emerged as the most consistently elevated marker, "
        "outperforming CSF assays in several cohorts."
    )

    def test_heading_marker_is_not_in_the_title(self):
        title = derive_title_from_first_sentence(self.BODY)
        assert "#" not in title, (
            f"the heading marker leaked into the title: {title!r}"
        )

    def test_bold_markers_are_not_in_the_title(self):
        title = derive_title_from_first_sentence(self.BODY)
        assert "**" not in title, (
            f"the bold marker leaked into the title: {title!r}"
        )

    def test_the_heading_text_is_not_in_the_title(self):
        title = derive_title_from_first_sentence(self.BODY)
        assert "Bottom line" not in title, (
            f"the section label leaked into the title: {title!r}"
        )

    def test_the_title_carries_the_actual_content(self):
        title = derive_title_from_first_sentence(self.BODY)
        assert "plasma N-terminal tau fragment 1" in title, (
            f"the title lost the report's subject: {title!r}"
        )

    def test_injected_h1_is_plain_text(self):
        injected = inject_h1_fallback(self.BODY)
        first_line = injected.split("\n", 1)[0]
        assert first_line.startswith("# ")
        assert first_line.count("#") == 1, (
            f"the injected H1 carries extra '#' characters: {first_line!r}"
        )
        assert "**" not in first_line, (
            f"the injected H1 carries bold markers: {first_line!r}"
        )

    def test_an_h2_heading_is_also_skipped(self):
        body = (
            "## Overview of the Biomarker Landscape\n"
            "\n"
            "The diagnostic framework for Alzheimer's disease has evolved "
            "rapidly in recent years."
        )
        title = derive_title_from_first_sentence(body)
        assert "#" not in title
        assert "Overview" not in title
        assert "diagnostic framework" in title

    def test_several_leading_headings_are_skipped(self):
        body = (
            "### Bottom line\n"
            "\n"
            "### Key findings\n"
            "\n"
            "Plasma p-tau217 outperformed CSF assays across the cohorts."
        )
        title = derive_title_from_first_sentence(body)
        assert "Bottom line" not in title
        assert "Key findings" not in title
        assert "Plasma p-tau217" in title

    def test_a_body_of_only_headings_uses_the_first_one(self):
        """No prose to derive from -- the heading is the best title."""
        body = "### Tau Biomarkers in Alzheimer's Disease"
        title = derive_title_from_first_sentence(body)
        assert title == "Tau Biomarkers in Alzheimer's Disease"


class TestTitleTextIsPlainText:
    """Inline markdown must not reach a title.

    A title is rendered as plain text in the React UI and as a
    ReportLab paragraph in the PDF; neither renders markdown.
    """

    def test_bold_markers_are_stripped(self):
        body = "**Plasma p-tau217** is a sensitive marker of AD."
        title = derive_title_from_first_sentence(body)
        assert title == "Plasma p-tau217 is a sensitive marker of AD"

    def test_code_markers_are_stripped(self):
        body = "`p-tau217` is a sensitive marker of AD."
        title = derive_title_from_first_sentence(body)
        assert title == "p-tau217 is a sensitive marker of AD"

    def test_underscores_in_identifiers_are_preserved(self):
        """A single ``_`` is ordinary text, not emphasis.

        Stripping it would mangle identifiers like ``p_tau217``.
        """
        body = "The p_tau217 assay is a sensitive marker of AD."
        title = derive_title_from_first_sentence(body)
        assert "p_tau217" in title, (
            f"the underscore in the identifier was stripped: {title!r}"
        )

    def test_a_hyphenated_identifier_survives(self):
        body = "**Plasma N-terminal tau fragment 1** (p-tau217) is a marker."
        title = derive_title_from_first_sentence(body)
        assert "p-tau217" in title


class TestConsumersSeeTheCleanTitle:
    r"""Both consumers take the first ``# `` line -- it must be clean.

    The PDF generator matches ``^#\s+(.+?)\s*$`` and the React UI
    matches ``line.startsWith("# ")``. Whatever they find becomes
    the visible title, so a title with markdown in it is a title
    the reader sees with raw markdown in it.
    """

    BODY = (
        "### Bottom line\n"
        "\n"
        "Among the supplied studies, **plasma N-terminal tau fragment 1** "
        "(p-tau217) emerged as the most consistently elevated marker."
    )

    def test_the_pdf_generator_finds_a_clean_title(self):
        """The PDF generator's extraction, ported to Python.

        ``app/infrastructure/pdf/reportlab_generator.py`` splits the
        body into lines and matches the first line that looks like
        an H1::

            for line in body_lines:
                m = _H1_LINE_RE.match(line)
                if m:
                    title = m.group(1).strip()
                    break
        """
        from app.infrastructure.pdf.reportlab_generator import (
            _H1_LINE_RE,
        )

        injected = inject_h1_fallback(self.BODY)
        title = ""
        for line in injected.split("\n"):
            match = _H1_LINE_RE.match(line)
            if match:
                title = match.group(1).strip()
                break
        assert title, "the PDF generator found no title at all"
        assert "#" not in title
        assert "**" not in title
        assert "Bottom line" not in title

    def test_the_frontend_finds_a_clean_title(self):
        r"""The React UI's extraction, ported to Python.

        ``frontend/src/pages/Report.tsx`` does::

            report.summary
                .split("\n")
                .find((line) => line.startsWith("# "))
                ?.replace(/^#\s+/, "")
        """
        import re

        injected = inject_h1_fallback(self.BODY)
        first_h1_line = next(
            line for line in injected.split("\n") if line.startswith("# ")
        )
        title = re.sub(r"^#\s+", "", first_h1_line)
        assert "#" not in title
        assert "**" not in title
        assert "Bottom line" not in title
