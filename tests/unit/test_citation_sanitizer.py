"""
tests/unit/test_citation_sanitizer.py

Pure-function tests for ``sanitize_citation_markers`` -- the
backend defence-in-depth layer that strips hallucinated
``[paper:N]`` markers (where ``N`` exceeds the bibliography
size) from raw LLM output at the ingest boundary.

Background
----------
The Vancouver / ICMJE prompt tells the LLM not to fabricate
citation indices, but in practice models still emit markers
like ``[paper:18]`` in a 17-paper bibliography. The
sanitizer strips these so they never reach persistent storage
or the rendered page.

The frontend ``linkifyCitationMarkers`` helper also drops
out-of-range markers at render time as a third line of
defence. We test the backend helper here.

Tests cover the full policy:
  - In-range markers: pass through verbatim
  - Out-of-range markers: silently dropped
  - Grouped markers: each entry checked independently;
    valid become links, invalid are silently dropped
  - All-group-invalid: fall back to original text
  - Malformed markers (non-numeric): pass through
  - Empty input: returns empty
  - The logger warning fires exactly once per call when any
    marker is dropped
"""
from __future__ import annotations

import logging

import pytest

from app.infrastructure.llm.citation_sanitizer import (
    sanitize_citation_markers,
)


def _silent_logger() -> logging.Logger:
    """A logger that drops everything -- avoids polluting test output."""
    log = logging.getLogger(f"test_citation_sanitizer_{id(object())}")
    log.handlers = [logging.NullHandler()]
    log.setLevel(logging.CRITICAL)
    log.propagate = False
    return log


class TestSanitizeStandaloneMarkers:
    """Pin the policy for single ``[paper:N]`` markers (no commas)."""

    def test_in_range_passthrough(self):
        assert sanitize_citation_markers(
            "see [paper:5] today.", 20, logger_=_silent_logger(),
        ) == "see [paper:5] today."

    def test_index_one_is_in_range(self):
        """``[paper:1]`` is always in range when ``bibliography_size >= 1``."""
        assert sanitize_citation_markers(
            "[paper:1]", 1, logger_=_silent_logger(),
        ) == "[paper:1]"

    def test_index_equals_size_is_in_range(self):
        """The boundary ``N == bibliography_size`` is in range."""
        assert sanitize_citation_markers(
            "[paper:20]", 20, logger_=_silent_logger(),
        ) == "[paper:20]"

    def test_out_of_range_dropped(self):
        """``N > bibliography_size`` -> silently dropped (empty string)."""
        assert sanitize_citation_markers(
            "see [paper:99] today.", 20, logger_=_silent_logger(),
        ) == "see  today."

    def test_zero_index_dropped(self):
        """Markers use 1-based indexing. ``[paper:0]`` is out of range."""
        assert sanitize_citation_markers(
            "see [paper:0] today.", 20, logger_=_silent_logger(),
        ) == "see  today."

    def test_negative_index_dropped(self):
        """``-1`` is even less than ``1`` -- still dropped."""
        # ``\\-1`` doesn't satisfy the ``\\d+`` regex, so the marker is
        # not matched at all -- it passes through. But ``[paper:-1]``
        # is malformed enough to count as "preserved verbatim" by
        # the regex. Pin that behaviour so we don't accidentally
        # start dropping malformed markers in the future.
        assert sanitize_citation_markers(
            "[paper:-1]", 20, logger_=_silent_logger(),
        ) == "[paper:-1]"


class TestSanitizeGroupedMarkers:
    """Pin the policy for ``[paper:N, paper:M, ...]`` grouped markers."""

    def test_all_in_range_preserves_canonical_paper_form(self):
        """Grouped markers in the LLM's output use a mix of
        ``"N"`` (first element after ``[paper:``) and
        ``"paper:N"`` (subsequent elements). The sanitizer
        normalises everything to the canonical ``[paper:N,
        paper:M, ...]`` form so downstream consumers
        (``report_mapper._build_citations`` regex extraction,
        the Frontend ``linkifyCitationMarkers`` helper) all
        see a consistent shape.

        Note: the sanitizer does NOT convert to a markdown
        link (``[N](#citation-N)``) -- that's the Frontend
        linkifier's job. The backend sanitizer's role is
        strictly to drop hallucinated indices at the ingest
        boundary; doing the link conversion here would
        duplicate the Frontend's work and break the
        ``report_mapper`` regex extraction that depends on
        seeing ``[paper:N]`` literally.
        """
        assert sanitize_citation_markers(
            "see [paper:5, paper:12] today.", 20,
            logger_=_silent_logger(),
        ) == "see [paper:5, paper:12] today."

    def test_normalises_first_element_to_paper_form(self):
        """The first element of a grouped marker has no
        ``paper:`` prefix (the regex ``[paper:N`` consumes it).
        The sanitizer adds it back so the rendered text is
        always ``[paper:N, paper:M, ...]``.
        """
        assert sanitize_citation_markers(
            "[paper:5, paper:12] today.", 20,
            logger_=_silent_logger(),
        ) == "[paper:5, paper:12] today."

    def test_mixed_validity_drops_invalid(self):
        """Mixed groups: invalid entries are silently dropped,
        the rest is re-emitted in canonical ``[paper:N,
        paper:M, ...]`` form.
        """
        # bibliography has 10 entries; user passed 1 and 99 in
        # a single group -- 1 is valid, 99 is not.
        assert sanitize_citation_markers(
            "see [paper:1, paper:99] today.", 10,
            logger_=_silent_logger(),
        ) == "see [paper:1] today."

    def test_two_out_of_three_dropped_silently(self):
        """Three-element group, only the middle valid.
        Order preserved: ``paper:2`` stays at position 2.
        """
        assert sanitize_citation_markers(
            "see [paper:99, paper:2, paper:88] today.", 5,
            logger_=_silent_logger(),
        ) == "see [paper:2] today."

    def test_all_group_invalid_falls_back_to_original(self):
        """If every entry is invalid, fall back to the original
        text. We don't want to silently erase the user's
        context if nothing useful can be rendered.
        """
        text = "see [paper:99, paper:100] today."
        assert sanitize_citation_markers(
            text, 20, logger_=_silent_logger(),
        ) == text

    def test_group_with_one_malformed_piece_falls_back_entirely(self):
        """A group with one piece that doesn't match the
        ``paper:\\d+`` inner pattern (e.g. ``papr:6`` instead
        of ``paper:6``) makes the entire ``[paper:N,
        paper:M, ...]`` shape fail to match the grouped
        regex. The helper then falls back to the original
        text. This is the right tradeoff: a malformed inner
        piece suggests the LLM misformatted the marker, and
        we'd rather surface the original text than silently
        render a half-converted form.

        This contrasts with :class:`TestSanitizeMalformedMarkers`,
        which covers the standalone ``[paper:abc]`` case (the
        regex never matches, so the marker passes through
        unchanged).
        """
        text = "see [paper:5, papr:6, paper:7] today."
        assert sanitize_citation_markers(
            text, 20, logger_=_silent_logger(),
        ) == text

    def test_group_with_all_malformed_falls_back(self):
        """A group where every piece is malformed (none parses as
        a number) returns the original text.
        """
        text = "see [paper:abc, paper:xyz] today."
        assert sanitize_citation_markers(
            text, 20, logger_=_silent_logger(),
        ) == text


class TestSanitizeTextWithNoMarkers:
    """Inputs that don't have any ``[paper:N]`` markers pass through unchanged."""

    def test_no_markers(self):
        text = "this is a plain text with no markers at all."
        assert sanitize_citation_markers(
            text, 20, logger_=_silent_logger(),
        ) == text

    def test_empty_string(self):
        """Empty input returns empty (idempotent)."""
        assert sanitize_citation_markers(
            "", 20, logger_=_silent_logger(),
        ) == ""

    def test_unrelated_brackets(self):
        """Other bracket pairs (``[some note]``, ``[footnote: x]``)
        are not markers -- pass through.
        """
        text = "[some note] p-tau217 [footnote: not a marker] text"
        assert sanitize_citation_markers(
            text, 20, logger_=_silent_logger(),
        ) == text


class TestSanitizeMalformedMarkers:
    """``[paper:]``, ``[paper:abc]``, etc. are not parseable as
    numbers -- pass through unchanged (the regex never matches).
    """

    def test_empty_index(self):
        assert sanitize_citation_markers(
            "[paper:]", 20, logger_=_silent_logger(),
        ) == "[paper:]"

    def test_non_numeric_index(self):
        assert sanitize_citation_markers(
            "[paper:abc]", 20, logger_=_silent_logger(),
        ) == "[paper:abc]"

    def test_decimal_index(self):
        assert sanitize_citation_markers(
            "[paper:1.5]", 20, logger_=_silent_logger(),
        ) == "[paper:1.5]"


class TestSanitizeMixedValidAndInvalidStandalone:
    """Mixed valid-and-invalid standalone markers in the same string.

    Pin the round-trip: the helper should drop only the invalid
    markers, leaving the valid ones (and any unrelated text)
    intact.
    """

    def test_mixed_valid_and_invalid_keeps_only_valid(self):
        assert sanitize_citation_markers(
            "first [paper:1] valid; [paper:99] invalid; [paper:2] valid.",
            5,
            logger_=_silent_logger(),
        ) == "first [paper:1] valid;  invalid; [paper:2] valid."

    def test_preserves_intervening_prose(self):
        """The helper must not mangle prose between markers."""
        result = sanitize_citation_markers(
            "intro [paper:1] mid1 [paper:99] mid2 [paper:2] outro.",
            5,
            logger_=_silent_logger(),
        )
        assert result == "intro [paper:1] mid1  mid2 [paper:2] outro."

    def test_multiple_invalid_dropped_with_one_warning(self):
        """N+ invalid markers -> one consolidated warning, not N."""
        log = logging.getLogger(f"test_multi_invalid_{id(object())}")
        log.handlers = [logging.NullHandler()]
        log.setLevel(logging.WARNING)
        log.propagate = False
        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        cap = Capture()
        log.addHandler(cap)
        sanitize_citation_markers(
            "[paper:99][paper:100][paper:88]", 20, logger_=log,
        )
        # Exactly one warning per sanitization call -- if the LLM
        # hallucinates 50 markers we'd see 50 WARNINGs, which floods
        # the logs. The contract is "one warning per call regardless
        # of how many markers were dropped".
        warning_records = [r for r in records if r.levelno == logging.WARNING]
        assert len(warning_records) == 1
        # And the message must include the count so operators
        # can see the magnitude.
        assert "3" in warning_records[0].getMessage()


class TestSanitizeEdgeCaseBibliographies:
    """Edge cases for the bibliography_size argument."""

    def test_bibliography_size_zero(self):
        """With 0 papers, ANY ``[paper:N]`` marker is out of range
        because valid range is ``1 <= N <= 0`` (empty). The helper
        drops every marker.
        """
        assert sanitize_citation_markers(
            "[paper:1]", 0, logger_=_silent_logger(),
        ) == ""

    def test_bibliography_size_zero_logs_warning(self):
        """A 0-paper bibliography is unusual -- log a warning."""
        log = logging.getLogger(f"test_zero_bib_{id(object())}")
        log.handlers = [logging.NullHandler()]
        log.setLevel(logging.WARNING)
        log.propagate = False
        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        log.addHandler(Capture())
        sanitize_citation_markers(
            "[paper:1] [paper:2]", 0, logger_=log,
        )
        warnings = [r for r in records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    def test_no_log_when_nothing_dropped(self):
        """The cleanest case: every marker is in range, no log
        output. Confirms we're not polluting the log on the
        common path.
        """
        log = logging.getLogger(f"test_no_log_{id(object())}")
        log.handlers = [logging.NullHandler()]
        log.setLevel(logging.DEBUG)  # capture everything
        log.propagate = False
        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        log.addHandler(Capture())
        sanitize_citation_markers(
            "[paper:1] [paper:2]", 5, logger_=log,
        )
        # No warnings, no info -- the call is silent.
        assert records == []
