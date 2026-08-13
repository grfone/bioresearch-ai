"""
Unit tests for the CitationValidator (anti-fabrication guard).

These tests verify that fabricated citations are rejected by the
validator and that valid citations pass through.
"""

from __future__ import annotations

import pytest

from app.application.validation.citation_validator import CitationValidator
from app.core.enums.citation_style import CitationStyleEnum
from app.core.exceptions import CitationValidationError
from app.domain.entities.citation import Citation
from app.domain.entities.evidence_comparison import EvidenceComparison
from app.domain.entities.evidence_matrix import EvidenceMatrix, MatrixCell
from app.domain.entities.finding import Contradiction, Finding
from app.domain.entities.paper import Paper
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.summary import Summary


def _paper(pmid: str | None = None, doi: str | None = None, title: str = "T") -> Paper:
    return Paper(title=title, pmid=pmid, doi=doi, abstract="x")


# ---------------------------------------------------------------------------
# is_allowed
# ---------------------------------------------------------------------------


def test_is_allowed_accepts_pmid_prefix() -> None:
    v = CitationValidator([_paper(pmid="12345")])
    assert v.is_allowed("pmid:12345")


def test_is_allowed_accepts_bare_pmid() -> None:
    v = CitationValidator([_paper(pmid="12345")])
    assert v.is_allowed("12345")


def test_is_allowed_accepts_doi_prefix() -> None:
    v = CitationValidator([_paper(doi="10.1/foo")])
    assert v.is_allowed("doi:10.1/foo")


def test_is_allowed_rejects_unknown_pmid() -> None:
    v = CitationValidator([_paper(pmid="12345")])
    assert not v.is_allowed("99999")


def test_is_allowed_rejects_empty() -> None:
    v = CitationValidator([_paper(pmid="12345")])
    assert not v.is_allowed("")


# ---------------------------------------------------------------------------
# validate_finding
# ---------------------------------------------------------------------------


def test_validate_finding_accepts_known_pmid() -> None:
    v = CitationValidator([_paper(pmid="12345")])
    v.validate_finding(
        Finding(claim="x", paper_ids=["pmid:12345"], evidence_strength="strong")
    )


def test_validate_finding_rejects_fabricated_pmid() -> None:
    v = CitationValidator([_paper(pmid="12345")])
    with pytest.raises(CitationValidationError) as exc:
        v.validate_finding(
            Finding(claim="x", paper_ids=["pmid:99999"])
        )
    assert "99999" in str(exc.value)


def test_validate_finding_accepts_mixed_form() -> None:
    v = CitationValidator([_paper(pmid="12345")])
    v.validate_finding(
        Finding(claim="x", paper_ids=["12345", "pmid:12345"])
    )


# ---------------------------------------------------------------------------
# validate_evidence_comparison
# ---------------------------------------------------------------------------


def _comparison_with_consensus(paper_ids: list[str]) -> EvidenceComparison:
    return EvidenceComparison(
        consensus=[Finding(claim="x", paper_ids=paper_ids)],
        used_paper_ids=paper_ids,
    )


def test_validate_comparison_passes_when_all_papers_in_set() -> None:
    papers = [_paper(pmid="1"), _paper(pmid="2")]
    v = CitationValidator(papers)
    v.validate_evidence_comparison(
        _comparison_with_consensus(["pmid:1", "pmid:2"])
    )


def test_validate_comparison_rejects_fabricated_pmid() -> None:
    papers = [_paper(pmid="1")]
    v = CitationValidator(papers)
    with pytest.raises(CitationValidationError):
        v.validate_evidence_comparison(
            _comparison_with_consensus(["pmid:1", "pmid:99999"])
        )


def test_validate_comparison_validates_matrix() -> None:
    papers = [_paper(pmid="1")]
    v = CitationValidator(papers)
    matrix = EvidenceMatrix(
        columns=["Methods"],
        rows=[
            MatrixCell(paper_id="pmid:1", facets={"Methods": "RCT"}),
            MatrixCell(paper_id="pmid:99999", facets={"Methods": "Observational"}),
        ],
        used_paper_ids=["pmid:1", "pmid:99999"],
    )
    comparison = EvidenceComparison(
        matrix=matrix,
        used_paper_ids=["pmid:1"],
    )
    with pytest.raises(CitationValidationError):
        v.validate_evidence_comparison(comparison)


def test_validate_comparison_validates_contradictions() -> None:
    papers = [_paper(pmid="1")]
    v = CitationValidator(papers)
    comparison = EvidenceComparison(
        contradictions=[
            Contradiction(
                topic="efficacy",
                description="disagreement",
                paper_ids=["pmid:1", "pmid:99999"],
            )
        ],
        used_paper_ids=["pmid:1"],
    )
    with pytest.raises(CitationValidationError):
        v.validate_evidence_comparison(comparison)


# ---------------------------------------------------------------------------
# validate_report
# ---------------------------------------------------------------------------


def test_validate_report_accepts_known_citation() -> None:
    paper = _paper(pmid="12345")
    v = CitationValidator([paper])
    report = ResearchReport(
        summary=Summary(text="x", papers_used=[paper]),
        citations=[Citation(paper=paper)],
    )
    v.validate_report(report)


def test_validate_report_rejects_unknown_citation() -> None:
    paper = _paper(pmid="12345")
    foreign = _paper(pmid="99999")
    v = CitationValidator([paper])
    report = ResearchReport(
        summary=Summary(text="x", papers_used=[paper]),
        citations=[Citation(paper=foreign)],
    )
    with pytest.raises(CitationValidationError):
        v.validate_report(report)
