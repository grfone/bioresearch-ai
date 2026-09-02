"""
tests/unit/test_report_mapper_markers.py

Regression tests for the marker-based citation matching in
``ReportMapper._build_citations``.

Why this file exists
--------------------
Real LLM summaries paraphrase paper titles. The original title-
substring matcher found zero citations in production even with
20 papers loaded, because the LLM rewrote every title in the
synthesis. The fix: have the summary prompt number papers as
``[paper:1]``, ``[paper:2]``, ... and ask the LLM to preserve
those markers verbatim. The mapper then extracts markers from
the summary text and uses them as the primary citation signal.

These tests pin the marker-extraction + substring-fallback path.
The full pick-up-1 contract (summary prompt emits markers) is
exercised in ``test_summarize_papers_prompt.py``.
"""
from app.domain.entities.author import Author
from app.domain.entities.citation import Citation
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.summary import Summary
from app.domain.models.llm_response import LLMResponse
from app.infrastructure.llm.report_mapper import ReportMapper


def _paper(title: str, doi: str | None = None) -> Paper:
    """Build a Paper with the minimal fields the mapper inspects."""
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


def test_marker_driven_citations_in_appearance_order() -> None:
    """Papers cited by ``[paper:N]`` markers appear in the citation
    list in the order their markers first appear in the text."""
    papers = [
        _paper("Alzheimer biomarker blood test cohort"),
        _paper("Tau PET imaging longitudinal study"),
        _paper("ApoE genotype risk stratification"),
    ]
    # Markers appear in the order [3, 1, 2] -- not the natural
    # 1, 2, 3 -- because the LLM cited paper 3 first. The mapper
    # should preserve the cited order, not the natural order.
    summary = _summary(
        "[paper:3] found X. [paper:1] found Y. [paper:2] found Z.",
        papers,
    )
    report = ReportMapper().map(_response("Body."), summary)

    titles = [c.paper.title for c in report.citations]
    assert titles == [
        "ApoE genotype risk stratification",
        "Alzheimer biomarker blood test cohort",
        "Tau PET imaging longitudinal study",
    ]


def test_markers_out_of_range_are_ignored() -> None:
    """An out-of-range marker (``[paper:99]`` in a 3-paper list) is
    silently dropped. This guards against LLM hallucinations like
    ``[paper:99]`` that would otherwise silently extend the
    citation list to non-existent papers.

    As of the 2026-08-31 FSM-fix iteration, every workspace
    paper appears in the bibliography regardless of marker
    citation. The marker-driven Phase 1 only sees
    ``[paper:1]`` and ``[paper:2]`` (paper 99 is dropped because
    it's out of range), but Phase 3 includes ``Paper Three``
    from the corpus regardless.
    """
    papers = [_paper("Paper One"), _paper("Paper Two"), _paper("Paper Three")]
    summary = _summary(
        "[paper:1] cited. [paper:99] hallucinated. [paper:2] cited.",
        papers,
    )
    report = ReportMapper().map(_response("Body."), summary)
    titles = [c.paper.title for c in report.citations]
    # The hallucinated marker [paper:99] must not extend the
    # bibliography to a non-existent paper. All three real
    # workspace papers appear; their order follows Phase 1 +
    # Phase 3 (corpus order for the rest).
    assert "Paper One" in titles
    assert "Paper Two" in titles
    assert "Paper Three" in titles
    assert len(report.citations) == 3


def test_substring_fallback_when_no_markers_present() -> None:
    """If the summary contains no ``[paper:N]`` markers (e.g. an
    older prompt or a model that ignored the marker instruction),
    the mapper falls back to title/DOI substring matching so the
    pipeline still produces citations for papers mentioned by
    their literal title or DOI."""
    papers = [
        _paper("SpecificPaperTitle12345"),
        _paper("OtherPaperTitle67890"),
    ]
    summary = _summary(
        "We saw SpecificPaperTitle12345 clearly. "
        "OtherPaperTitle67890 was less clear.",
        papers,
    )
    report = ReportMapper().map(_response("Body."), summary)
    titles = [c.paper.title for c in report.citations]
    assert "SpecificPaperTitle12345" in titles
    assert "OtherPaperTitle67890" in titles


def test_substring_match_on_doi() -> None:
    """DOI substring matching is a separate fallback from title
    matching. This test pins that path: paper B has no title in
    the text but its DOI is present, so the mapper should still
    pick it up via the DOI match."""
    papers = [
        _paper("Title One", doi="10.1038/nature14539"),
        _paper("Title Two", doi="10.1126/science.abc1234"),
    ]
    summary = _summary(
        "Two papers discussed. "
        "See 10.1038/nature14539 and 10.1126/science.abc1234.",
        papers,
    )
    report = ReportMapper().map(_response("Body."), summary)
    titles = [c.paper.title for c in report.citations]
    assert "Title One" in titles
    assert "Title Two" in titles


def test_uncited_papers_are_included_in_bibliography() -> None:
    """Papers the LLM didn't cite in the body are still in the
    bibliography (Phase 3 fallback).

    Previously the mapper dropped papers that appeared in
    neither markers nor text on the grounds that "citing them
    would be misleading." The user complained that this left
    them unable to verify which papers were actually available
    at INTERMEDIATE when the LLM focused on a subset. Now every
    workspace paper appears -- marker-cited first, substring-
    matched second, remaining corpus third.
    """
    papers = [
        _paper("Paper Cited"),  # cited via marker
        _paper("Paper Not Cited"),  # not in text at all
        _paper("Paper Cited by Substring"),  # title appears in text
    ]
    summary = _summary(
        "[paper:1] is well-supported. Paper Cited by Substring "
        "had weaker evidence.",
        papers,
    )
    report = ReportMapper().map(_response("Body."), summary)
    titles = [c.paper.title for c in report.citations]
    # Every workspace paper appears -- including the one the LLM
    # didn't mention in the body.
    assert "Paper Cited" in titles
    assert "Paper Cited by Substring" in titles
    assert "Paper Not Cited" in titles
    assert len(report.citations) == 3


def test_doi_dedup_across_marker_and_substring() -> None:
    """Two papers that share a DOI are deduped regardless of which
    signal matched them. Preprint + journal version of the same
    paper should produce a single citation."""
    paper_preprint = _paper(
        "Preprint version", doi="10.1038/nature14539"
    )
    paper_journal = _paper(
        "Journal version", doi="10.1038/nature14539"
    )
    summary = _summary(
        "[paper:1] is well-supported. Preprint version is the preprint.",
        [paper_preprint, paper_journal],
    )
    report = ReportMapper().map(_response("Body."), summary)
    assert len(report.citations) == 1
    # First occurrence wins (marker for paper 1 = preprint).
    assert report.citations[0].paper.title == "Preprint version"


def test_no_citations_when_no_papers_at_all() -> None:
    """When the workspace has zero papers, the bibliography is
    empty -- there's nothing to cite.

    The mapper's Phase 3 (corpus-order inclusion) iterates
    ``range(len(papers))``, so an empty ``papers_used`` produces
    an empty citation list. This distinguishes the "no
    corpus" case (Phase 3 contributes nothing) from the
    "non-empty corpus, LLM didn't cite anything" case
    (Phase 3 includes every corpus paper).
    """
    papers: list = []
    summary = _summary(
        "The research field is broad and multifaceted.",
        papers,
    )
    report = ReportMapper().map(_response("Body."), summary)
    assert report.citations == []
