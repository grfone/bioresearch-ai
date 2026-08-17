"""
test_paper_source_map.py

Unit tests for ``_build_paper_source_map`` and
``_paper_keys`` — the orchestrator helpers that build the
per-paper source attribution dict exposed via
``WorkspaceResponse.paper_sources``.

The helper itself is small but the data-shape assumptions
matter: dedup across sources, key priority (PMID over DOI
over URL), the "first source wins" rule, and the empty-list
fallback for identifier-less papers (e.g. structured PDF
extraction results with no DOI).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application.services.workspace_orchestrator import (
    _build_paper_source_map,
    _paper_keys,
)
from app.core.enums.search_source import SearchSource


def _result(
    *,
    title: str = "Untitled",
    doi: str | None = None,
    pmid: str | None = None,
    url: str | None = None,
    source: SearchSource = SearchSource.PUBMED,
) -> SimpleNamespace:
    """Build a fake ``SearchResult`` (paper + source)."""
    return SimpleNamespace(
        paper=SimpleNamespace(
            title=title,
            doi=doi,
            pmid=pmid,
            url=url,
        ),
        source=source,
    )


class TestPaperKeys:
    """``_paper_keys`` returns PMID → DOI → URL in priority order."""

    def test_returns_pmid_first(self):
        paper = SimpleNamespace(
            pmid="12345",
            doi="10.1/foo",
            url="https://example.com/12345",
        )
        assert _paper_keys(paper) == ["12345", "10.1/foo", "https://example.com/12345"]

    def test_skips_missing_pmid(self):
        paper = SimpleNamespace(
            pmid=None,
            doi="10.1/foo",
            url="https://example.com/12345",
        )
        assert _paper_keys(paper) == ["10.1/foo", "https://example.com/12345"]

    def test_returns_empty_when_no_identifiers(self):
        # Structured PDF extraction may produce a paper with
        # no PMID, no DOI, and no URL — the helper must
        # return an empty list, not a list with None or "".
        paper = SimpleNamespace(
            pmid=None,
            doi=None,
            url=None,
        )
        assert _paper_keys(paper) == []

    def test_skips_empty_string_identifiers(self):
        paper = SimpleNamespace(
            pmid="",
            doi="  ",
            url="https://example.com/x",
        )
        # Only the URL is non-empty after stripping.
        assert _paper_keys(paper) == ["https://example.com/x"]

    def test_strips_whitespace(self):
        paper = SimpleNamespace(
            pmid="  12345  ",
            doi="10.1/foo",
            url="https://example.com",
        )
        assert _paper_keys(paper) == ["12345", "10.1/foo", "https://example.com"]


class TestBuildPaperSourceMap:
    """``_build_paper_source_map`` produces paper-id → source maps."""

    def test_single_paper_single_source(self):
        results = [
            _result(
                pmid="12345",
                doi="10.1/foo",
                source=SearchSource.OPENALEX,
            ),
        ]
        out = _build_paper_source_map(results)
        assert out == {
            "12345": "openalex",
            "10.1/foo": "openalex",
        }

    def test_pmid_is_preferred_key_when_both_present(self):
        # The PMID is the first key for any paper that has
        # both; dedup later only matches on PMID if a later
        # paper shares that PMID.
        results = [
            _result(
                pmid="12345",
                doi="10.1/foo",
                source=SearchSource.OPENALEX,
            ),
        ]
        out = _build_paper_source_map(results)
        # Both PMID and DOI are in the map.
        assert "12345" in out
        assert "10.1/foo" in out

    def test_first_source_wins_on_dedup(self):
        # If the same DOI appears from two sources, the
        # higher-ranked source wins (since results are
        # already sorted by confidence × recency).
        results = [
            _result(
                pmid="12345",
                doi="10.1/foo",
                source=SearchSource.PUBMED,
            ),
            _result(
                pmid="67890",
                doi="10.1/foo",  # dedupe target
                source=SearchSource.OPENALEX,
            ),
        ]
        out = _build_paper_source_map(results)
        # The first paper's PMID ("12345") maps to pubmed.
        assert out["12345"] == "pubmed"
        # The DOI "10.1/foo" was first seen in the pubmed
        # result, so it stays pubmed. The OpenAlex result's
        # PMID ("67890") is unique to it.
        assert out["10.1/foo"] == "pubmed"
        assert out["67890"] == "openalex"

    def test_multiple_papers_multiple_sources(self):
        results = [
            _result(
                pmid="1",
                source=SearchSource.PUBMED,
            ),
            _result(
                doi="10.1/openalex",
                source=SearchSource.OPENALEX,
            ),
            _result(
                pmid="2",
                source=SearchSource.EUROPE_PMC,
            ),
            _result(
                doi="10.1/biorxiv",
                source=SearchSource.BIORXIV,
            ),
        ]
        out = _build_paper_source_map(results)
        assert out["1"] == "pubmed"
        assert out["10.1/openalex"] == "openalex"
        assert out["2"] == "europe_pmc"
        assert out["10.1/biorxiv"] == "biorxiv"

    def test_empty_results_returns_empty_dict(self):
        assert _build_paper_source_map([]) == {}

    def test_identifier_less_paper_is_skipped(self):
        # A structured PDF extraction result with no DOI and
        # no PMID — the helper must not crash or include a
        # None / "" key.
        results = [
            _result(
                title="Some PDF paper",
                pmid=None,
                doi=None,
                url=None,
                source=SearchSource.OPENALEX,
            ),
            _result(
                pmid="99999",
                source=SearchSource.PUBMED,
            ),
        ]
        out = _build_paper_source_map(results)
        assert "99999" in out
        # No None or empty-string keys.
        for key in out:
            assert key, f"unexpected empty key: {key!r}"
        assert len(out) == 1

    def test_source_enum_is_serialised_to_value(self):
        # The helper unwraps ``SearchSource.OPENALEX`` (the
        # enum value) into the string ``"openalex"`` — the
        # frontend expects the string form.
        results = [
            _result(pmid="1", source=SearchSource.OPENALEX),
        ]
        out = _build_paper_source_map(results)
        assert out["1"] == "openalex"
        assert isinstance(out["1"], str)

    def test_source_string_passes_through(self):
        # Defensive: if a caller hands in a plain string
        # instead of an enum (e.g. via dependency injection
        # in tests), the helper falls back to ``str(...)``
        # rather than crashing.
        results = [
            SimpleNamespace(
                paper=SimpleNamespace(
                    pmid="1",
                    doi=None,
                    url=None,
                ),
                source="openalex",  # string, not enum
            ),
        ]
        out = _build_paper_source_map(results)
        assert out["1"] == "openalex"

    def test_url_only_paper_is_included(self):
        # Some papers (e.g. from Europe PMC with no PMID/DOI
        # but a fulltext URL) have only a URL. The helper
        # should still include them.
        results = [
            _result(
                title="URL-only paper",
                pmid=None,
                doi=None,
                url="https://europepmc.org/article/MED/99999",
                source=SearchSource.EUROPE_PMC,
            ),
        ]
        out = _build_paper_source_map(results)
        assert (
            out["https://europepmc.org/article/MED/99999"]
            == "europe_pmc"
        )
