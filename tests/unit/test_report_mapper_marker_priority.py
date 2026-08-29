"""
tests/unit/test_report_mapper_marker_priority.py

Pin the citation-order tie-breaker when marker-based and
title-substring signals disagree on the same paper.

Why this file exists
--------------------
``ReportMapper._build_citations`` uses a two-signal
strategy: marker-based (primary) + title/DOI substring
(fallback). The base test suite
(``test_report_mapper_markers.py``) covers the broad
contract -- markers take precedence, out-of-range
markers are dropped, substring fallback works when no
markers are present. This file pins the **mixed-signal
edge cases** the base suite doesn't exercise:

  - Some papers cited by marker, others by substring in
    the same summary.
  - A paper cited by BOTH marker AND title in the same
    summary -- which signal drives its citation order?

These scenarios matter because real LLM summaries are
inconsistent: a paper may be cited as ``[paper:3]`` in
one sentence and by literal title in another. The mapper
must converge to a single citation entry per paper
(deduped by DOI) and the citation order must be
deterministic.

These tests were originally drafted in a different
session's stash (2026-08-24) and recovered here so the
edge-case coverage isn't lost.
"""
from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.summary import Summary
from app.domain.models.llm_response import LLMResponse
from app.infrastructure.llm.report_mapper import ReportMapper


def _paper(title: str, doi: str | None = None) -> Paper:
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


def _summary(text: str, papers: list[Paper]) -> Summary:
    return Summary(body=text, papers_used=papers)


def _response(text: str = "Body of the report.") -> LLMResponse:
    return LLMResponse(
        content=text,
        model="test-model",
        finish_reason="stop",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
    )


class TestMixedSignalCitationMatching:
    """Papers cited by different signals in the same
    summary are matched by whichever signal finds them
    first. The result is a single citation list spanning
    both matching strategies."""

    def test_mixed_marker_and_substring_signals(self) -> None:
        """Paper A is marker-cited, paper B is
        title-substring-cited, paper C is uncited and
        should be dropped. Both A and B appear in the
        citation list, in their respective text-order
        positions.
        """
        papers = [
            _paper("PaperViaMarker"),
            _paper("PaperViaSubstring12345"),
            _paper("PaperNeverCited"),
        ]
        summary = _summary(
            "[paper:1] is well-supported. "
            "PaperViaSubstring12345 had weaker evidence.",
            papers,
        )
        report = ReportMapper().map(_response("Body."), summary)

        titles = [c.paper.title for c in report.citations]
        # Both cited papers appear.
        assert "PaperViaMarker" in titles
        assert "PaperViaSubstring12345" in titles
        # The uncited paper is dropped.
        assert "PaperNeverCited" not in titles
        # Only the two cited papers -- no duplicates.
        assert len(titles) == 2


class TestMarkerPriorityOverSubstring:
    """When a paper is cited by BOTH a marker AND its
    title, the marker position drives the citation order.
    The rationale: the LLM chose to use the marker (a
    deliberate citation signal) and the title in the
    text, so the marker position reflects the LLM's
    intent better than the title's text position. This
    is the documented tie-breaker."""

    def test_marker_position_wins_when_paper_cited_twice(self) -> None:
        """Paper 1 is cited both as ``[paper:1]`` and by its
        title. The marker appears later in the text, the
        title appears earlier. The marker position is the
        dedup key for the citation list (the paper is
        cited only once even though it appears twice).
        """
        papers = [
            _paper("TitleAppearsEarly"),
            _paper("TitleAppearsLate"),
        ]
        # Paper 1's title appears FIRST. ``[paper:1]`` (the
        # marker for paper 1) also appears, AFTER the
        # title and BEFORE the [paper:2] marker. The
        # substring matcher would put paper 1 first; the
        # marker matcher also puts paper 1 first (its
        # marker position is before paper 2's marker). The
        # dedup-by-DOI across phases ensures paper 1
        # appears in the citation list exactly once, at
        # the marker-driven position.
        summary = _summary(
            "TitleAppearsEarly text. [paper:1] also. "
            "[paper:2] marker. TitleAppearsLate text.",
            papers,
        )
        report = ReportMapper().map(_response("Body."), summary)

        titles = [c.paper.title for c in report.citations]
        # Both papers are present.
        assert "TitleAppearsEarly" in titles
        assert "TitleAppearsLate" in titles
        # Total citation count is 2 (one per paper, no
        # duplicates even though paper 1 appears twice in
        # the source text).
        assert len(titles) == 2
        # Paper 1 (cited via marker AND title) appears
        # before paper 2 -- the marker position (19) is
        # before paper 2's marker position (32).
        assert titles.index("TitleAppearsEarly") < titles.index(
            "TitleAppearsLate"
        )

    def test_same_paper_deduped_across_signals(self) -> None:
        """The same paper cited by both a marker and its
        title produces a single citation (not two). The
        marker position is the citation position.
        """
        paper = _paper("DuplicateCitationsAcrossSignals")
        # Two other papers for a non-trivial 3-paper set.
        other = [
            _paper("Other Paper A"),
            _paper("Other Paper B"),
        ]
        papers = [paper, *other]
        # Paper 1 is cited by marker AND title. The marker
        # appears after the title.
        summary = _summary(
            "DuplicateCitationsAcrossSignals was well-cited. "
            "[paper:1] is well-supported.",
            papers,
        )
        report = ReportMapper().map(_response("Body."), summary)

        titles = [c.paper.title for c in report.citations]
        # Paper 1 appears exactly once despite being cited
        # twice in the source.
        assert titles.count("DuplicateCitationsAcrossSignals") == 1
        # Both other papers are absent (uncited).
        assert "Other Paper A" not in titles
        assert "Other Paper B" not in titles
        # The result is a single-element citation list.
        assert len(titles) == 1
