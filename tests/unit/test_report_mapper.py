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


def test_mapper_caps_citation_count() -> None:
    # 25 papers -> capped at 20 (the configured _MAX_CITATIONS).
    papers = [_paper(f"Paper Number {i:02d}") for i in range(25)]
    summary_text = " ".join(p.title for p in papers)
    summary = _summary(summary_text, papers)

    report = ReportMapper().map(_response("Body of the report."), summary)
    assert len(report.citations) == 20


def test_mapper_skips_papers_not_mentioned_in_summary() -> None:
    paper_in_text = _paper("Paper In Text", doi="10.1038/in_text")
    paper_out_of_text = _paper("Paper Out Of Text", doi="10.1038/out_of")
    summary = _summary("Paper In Text is discussed.", [paper_in_text, paper_out_of_text])

    report = ReportMapper().map(_response("Body of the report."), summary)
    titles = [c.paper.title for c in report.citations]
    assert "Paper In Text" in titles
    assert "Paper Out Of Text" not in titles


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
