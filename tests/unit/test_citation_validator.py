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
from app.domain.entities.finding import Finding
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
# validate_report
# ---------------------------------------------------------------------------


def test_validate_report_accepts_known_citation() -> None:
    paper = _paper(pmid="12345")
    v = CitationValidator([paper])
    report = ResearchReport(
        summary=Summary(body="x", papers_used=[paper]),
        citations=[Citation(paper=paper)],
    )
    v.validate_report(report)


def test_validate_report_rejects_unknown_citation() -> None:
    paper = _paper(pmid="12345")
    foreign = _paper(pmid="99999")
    v = CitationValidator([paper])
    report = ResearchReport(
        summary=Summary(body="x", papers_used=[paper]),
        citations=[Citation(paper=foreign)],
    )
    with pytest.raises(CitationValidationError):
        v.validate_report(report)
