"""
tests/unit/test_report_mapper.py

Tests for ``ReportMapper.map()`` -- the orchestrator that converts
an LLM response + Summary into a ResearchReport.

The mapper must:
  - Build a deduplicated citations list from ``summary.papers_used``
  - Order citations by first appearance in ``summary.body`` so the
    most-referenced papers are listed first
  - Cap at ``_MAX_CITATIONS`` so the UI stays manageable
  - Surface limitations and future work from the LLM output
  - Stamp the LLM model and token counts in the report metadata

Confidence (a self-evaluative number produced by the LLM) has
been removed because it's not a useful signal -- the LLM is
working from papers the user supplied, so "confidence" is
tautological. The data-derived confidence floor was a band-aid.
"""
from app.domain.entities.author import Author
from app.domain.entities.citation import Citation
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.summary import Summary
from app.domain.models.llm_response import LLMResponse
from app.infrastructure.llm.report_mapper import ReportMapper


def _paper(title: str, doi: str | None = None) -> Paper:
    """Build a minimal Paper -- only fields the mapper inspects."""
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


# -- Citations ---------------------------------------------------------


def test_mapper_populates_citations_from_summary_papers() -> None:
    paper_a = _paper("Paper Alpha")
    paper_b = _paper("Paper Beta")
    summary = _summary("Paper Alpha and Paper Beta.", [paper_a, paper_b])

    report = ReportMapper().map(_response("Body of the report."), summary)

    assert len(report.citations) == 2
    titles = [c.paper.title for c in report.citations]
    assert "Paper Alpha" in titles
    assert "Paper Beta" in titles


def test_mapper_orders_citations_by_first_appearance_in_summary() -> None:
    paper_a = _paper("Paper Alpha")
    paper_b = _paper("Paper Beta")
    paper_c = _paper("Paper Gamma")
    # Summary text mentions Gamma first, then Alpha, then Beta.
    summary = _summary(
        "Paper Gamma and Paper Alpha and Paper Beta appear in this order. "
        "Paper Gamma again. Paper Alpha again. Paper Beta again.",
        [paper_a, paper_b, paper_c],
    )

    report = ReportMapper().map(_response("Body of the report."), summary)
    titles = [c.paper.title for c in report.citations]
    assert titles == ["Paper Gamma", "Paper Alpha", "Paper Beta"]


def test_mapmer_deduplicates_by_doi() -> None:
    # Two papers that share a DOI (e.g. preprint + journal version)
    # should appear only once.
    paper_a = _paper("Preprint version", doi="10.1038/nature14539")
    paper_b = _paper("Journal version", doi="10.1038/nature14539")
    summary = _summary(
        "Preprint version and Journal version both contribute.",
        [paper_a, paper_b],
    )

    report = ReportMapper().map(_response("Body of the report."), summary)
    assert len(report.citations) == 1
    # The first occurrence wins (preprint, which appears first in
    # ``papers_used``).
    assert report.citations[0].paper.title == "Preprint version"


def test_mapper_includes_all_workspace_papers_no_cap() -> None:
    """The bibliography includes every workspace paper (no cap).

    Previously the mapper truncated at ``_MAX_CITATIONS = 20``
    which silently dropped papers the LLM did not cite. After
    the 2026-08-31 FSM-fix iteration the user asked for the
    full bibliography on every report so they could verify
    ``workspace.papers`` matched ``report.citations`` exactly.

    A 25-paper workspace now produces a 25-citation report.
    ADR-019 enforces ``citations ⊆ workspace.papers`` at the
    entity layer so there's no risk of citations escaping the
    workspace, and the user-facing report always reflects the
    exact corpus they curated.
    """
    papers = [_paper(f"Paper Number {i:02d}") for i in range(25)]
    summary_text = " ".join(p.title for p in papers)
    summary = _summary(summary_text, papers)

    report = ReportMapper().map(_response("Body of the report."), summary)
    assert len(report.citations) == 25
    # Every workspace paper appears in the bibliography.
    citation_titles = {c.paper.title for c in report.citations}
    assert citation_titles == {p.title for p in papers}


def test_mapper_includes_papers_not_cited_by_llm() -> None:
    """Papers the LLM didn't cite are still in the bibliography.

    Previously the mapper dropped any paper the LLM did not
    mention in the body. The user complained that this left
    them unable to verify which papers were "actually used"
    when the LLM focused on a subset. Now every workspace paper
    appears, so a missing paper from the body's ``[paper:N]``
    markers is detectable by the user.

    Ordering: marker-cited papers first (Phase 1), then
    substring-matched (Phase 2), then remaining workspace
    papers in corpus order (Phase 3). With no markers and no
    substring matches here, Phase 3 puts both papers in
    corpus order.
    """
    paper_in_text = _paper("Paper In Text", doi="10.1038/in_text")
    paper_out_of_text = _paper("Paper Out Of Text", doi="10.1038/out_of")
    summary = _summary("Paper In Text is discussed.", [paper_in_text, paper_out_of_text])

    report = ReportMapper().map(_response("Body of the report."), summary)
    titles = [c.paper.title for c in report.citations]
    assert "Paper In Text" in titles
    # Both papers appear -- even the one not mentioned in the body.
    assert "Paper Out Of Text" in titles
    # Corpus order preserved within the same phase.
    assert titles == ["Paper In Text", "Paper Out Of Text"]


def test_mapper_returns_empty_citations_when_no_papers() -> None:
    summary = _summary("No papers at all.", [])
    report = ReportMapper().map(_response("Body of the report."), summary)
    assert report.citations == []


def test_mapper_each_citation_is_apa_style_string() -> None:
    paper = _paper("Title", doi="10.1038/nature14539")
    summary = _summary("Title is here.", [paper])

    report = ReportMapper().map(_response("Body of the report."), summary)
    formatted = str(report.citations[0])
    # APA-style citation -- not the abstract dataclass repr.
    assert "Author, A." in formatted
    assert "Title" in formatted
    assert "Nature" in formatted
    assert "(2024)" in formatted
    assert "https://doi.org/10.1038/nature14539" in formatted


# -- Limitations / Future Work ----------------------------------------


def test_mapper_extracts_limitations_section() -> None:
    summary = _summary("Body of the report.", [_paper("Paper")])
    response_text = (
        "Executive Summary\n\nSynthesis.\n\n"
        "## Limitations\n"
        "- Sample size is small\n"
        "- Only English-language papers\n\n"
        "## Future Work\n"
        "- Replicate with larger cohort\n"
    )
    report = ReportMapper().map(_response(response_text), summary)
    assert "Sample size is small" in report.limitations
    assert "Only English-language papers" in report.limitations


def test_mapper_extracts_future_work_section() -> None:
    summary = _summary("Body of the report.", [_paper("Paper")])
    response_text = (
        "Executive Summary\n\nSynthesis.\n\n"
        "## Limitations\n"
        "- One limitation\n\n"
        "## Future Work\n"
        "- Run a meta-analysis\n"
        "- Cross-validate with animal models\n"
    )
    report = ReportMapper().map(_response(response_text), summary)
    assert "Run a meta-analysis" in report.future_work
    assert "Cross-validate with animal models" in report.future_work


# -- Metadata ---------------------------------------------------------


def test_mapmer_metadata_includes_citation_count() -> None:
    papers = [_paper(f"Paper Number {i:02d}") for i in range(5)]
    summary = _summary(" ".join(p.title for p in papers), papers)
    report = ReportMapper().map(_response("Body of the report."), summary)
    assert report.metadata.get("citation_count") == "5"
