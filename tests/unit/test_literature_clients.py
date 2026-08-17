"""
test_literature_clients.py

Unit tests for the new multi-source literature clients:
OpenAlex, Europe PMC, bioRxiv, and the MultiSourceSearcher
fan-out adapter.

Each client test mocks the HTTP layer via httpx's MockTransport
so the tests don't hit the network. The MultiSourceSearcher test
exercises the fan-out, dedupe, and ranking logic against stub
searchers — no network needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.enums.search_source import SearchSource, default_sources
from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.interfaces.literature_searcher import LiteratureSearcher
from app.domain.value_objects.search_filters import (
    SearchDocumentType,
    SearchFilters,
    SortBy,
)
from app.domain.value_objects.search_result import SearchResult
from app.infrastructure.literature.biorxiv_client import BiorxivSearcher
from app.infrastructure.literature.europe_pmc_client import (
    EuropePMCSearcher,
)
from app.infrastructure.literature.multi_source import (
    MultiSourceSearcher,
)
from app.infrastructure.literature.openalex_client import (
    OpenAlexSearcher,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _make_paper(
    *,
    title: str = "Test paper",
    doi: str | None = None,
    pmid: str | None = None,
    year: int | None = 2024,
    authors: list[Author] | None = None,
    journal: Journal | None = None,
) -> Paper:
    return Paper(
        title=title,
        authors=authors or [],
        journal=journal,
        year=year,
        abstract="",
        doi=doi,
        pmid=pmid,
        keywords=[],
        url=None,
    )


class _MockTransport(httpx.BaseTransport):
    """httpx mock transport that returns canned responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self._calls: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._calls.append(request)
        if not self._responses:
            return httpx.Response(
                500, content=b"mock exhausted"
            )
        return self._responses.pop(0)


def _client_with_mock(
    transport: _MockTransport,
) -> tuple[httpx.Client, _MockTransport]:
    http_client = httpx.Client(transport=transport)
    return http_client, transport


# ---------------------------------------------------------------------
# OpenAlex client
# ---------------------------------------------------------------------


def _openalex_record(
    *,
    doi: str | None = None,
    title: str = "Alzheimer's Disease: The Amyloid Cascade Hypothesis",
    year: int = 1992,
    authorships: list[dict[str, Any]] | None = None,
    abstract_words: dict[str, list[int]] | None = None,
    ids: dict[str, Any] | None = None,
    cited_by_count: int = 0,
    open_access: bool = False,
    primary_location: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal OpenAlex record."""
    return {
        "id": "https://openalex.org/W4376614794",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "title": title,
        "publication_year": year,
        "publication_date": f"{year}-05-29",
        "authorships": authorships or [],
        "primary_location": primary_location,
        "abstract_inverted_index": abstract_words,
        "keywords": [],
        "ids": ids or {},
        "open_access": {"is_oa": open_access, "oa_status": "gold"},
        "cited_by_count": cited_by_count,
    }


class TestOpenAlexSearcher:
    def test_default_source_is_openalex(self):
        with OpenAlexSearcher() as s:
            assert s.default_source() == SearchSource.OPENALEX

    def test_search_returns_results(self):
        record = _openalex_record(
            doi="10.1126/science.1566067",
            authorships=[
                {
                    "author": {"display_name": "John Hardy"},
                    "institutions": [
                        {"display_name": "Imperial College"}
                    ],
                },
                {
                    "author": {"display_name": "Gerald Higgins"},
                    "institutions": [],
                },
            ],
            abstract_words={
                "Amyloid": [0, 4],
                "cascade": [1],
                "hypothesis": [2],
                "in": [3],
            },
        )
        transport = _MockTransport(
            [httpx.Response(200, json={"results": [record]})]
        )
        http_client, mock = _client_with_mock(transport)
        client = OpenAlexSearcher(client=http_client)
        try:
            results = client.search_with_filters(
                SearchFilters(query="amyloid", max_results=5)
            )
        finally:
            client.close()

        assert len(results) == 1
        r = results[0]
        assert r.source == SearchSource.OPENALEX
        assert r.paper.title.startswith("Alzheimer's Disease")
        assert r.paper.doi == "10.1126/science.1566067"
        assert r.paper.year == 1992
        assert r.paper.authors[0].first_name == "John"
        assert r.paper.authors[0].last_name == "Hardy"
        assert r.paper.authors[0].affiliation == "Imperial College"
        # Abstract reconstructed in correct order: position 0 = "Amyloid",
        # 1 = "cascade", 2 = "hypothesis", 3 = "in", 4 = "Amyloid".
        assert r.paper.abstract == "Amyloid cascade hypothesis in Amyloid"

    def test_search_skips_broken_records(self):
        """A record without a title should not poison the batch."""
        bad = {"id": "W1"}  # no title
        good = _openalex_record(doi="10.1038/nature12373")
        transport = _MockTransport(
            [httpx.Response(200, json={"results": [bad, good]})]
        )
        http_client, mock = _client_with_mock(transport)
        client = OpenAlexSearcher(client=http_client)
        try:
            results = client.search_with_filters(
                SearchFilters(query="nature")
            )
        finally:
            client.close()
        assert len(results) == 1
        assert results[0].paper.doi == "10.1038/nature12373"

    def test_search_handles_http_error(self):
        transport = _MockTransport(
            [httpx.Response(503, content=b"upstream down")]
        )
        http_client, mock = _client_with_mock(transport)
        client = OpenAlexSearcher(client=http_client)
        try:
            results = client.search_with_filters(
                SearchFilters(query="foo")
            )
        finally:
            client.close()
        assert results == []

    def test_search_extracts_pmid_from_ids(self):
        record = _openalex_record(
            doi="10.1038/nature12373",
            ids={"pmid": "https://pubmed.ncbi.nlm.nih.gov/37286123"},
        )
        transport = _MockTransport(
            [httpx.Response(200, json={"results": [record]})]
        )
        http_client, mock = _client_with_mock(transport)
        client = OpenAlexSearcher(client=http_client)
        try:
            results = client.search_with_filters(
                SearchFilters(query="foo")
            )
        finally:
            client.close()
        assert results[0].paper.pmid == "37286123"

    def test_search_with_sort_newest_first(self):
        """``NEWEST_FIRST`` adds ``sort=publication_date:desc``."""
        transport = _MockTransport(
            [httpx.Response(200, json={"results": []})]
        )
        http_client, mock = _client_with_mock(transport)
        client = OpenAlexSearcher(client=http_client)
        try:
            client.search_with_filters(
                SearchFilters(
                    query="foo",
                    sort_by=SortBy.NEWEST_FIRST,
                )
            )
        finally:
            client.close()
        # The first call's URL should have sort=publication_date:desc.
        assert mock._calls, "no HTTP call was made"
        first_url = str(mock._calls[0].url)
        assert "sort=publication_date%3Adesc" in first_url or (
            "sort=publication_date" in first_url
        )

    def test_get_by_id_returns_paper(self):
        record = _openalex_record(doi="10.1126/science.1566067")
        transport = _MockTransport([httpx.Response(200, json=record)])
        http_client, mock = _client_with_mock(transport)
        client = OpenAlexSearcher(client=http_client)
        try:
            paper = client.get_by_id("10.1126/science.1566067")
        finally:
            client.close()
        assert paper is not None
        assert paper.doi == "10.1126/science.1566067"


# ---------------------------------------------------------------------
# Europe PMC client
# ---------------------------------------------------------------------


def _epmc_record(
    *,
    title: str = "Lipid dynamics in the amyloid cascade",
    doi: str = "10.1002/cbic.70398",
    pmid: str = "42218803",
    year: int = 2026,
    first_author_first: str = "Sofia",
    first_author_last: str = "Serravalle",
    journal_title: str = "Chembiochem",
    abstract: str = "We review the role of lipid dynamics.",
    pub_year_str: str = "2026",
    first_publication_date: str = "2026-06-01",
    cited_by_count: int = 0,
    is_open_access: str = "N",
    keywords: list[str] | None = None,
    mesh: list[str] | None = None,
    full_text_urls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "doi": doi,
        "pmid": pmid,
        "pmcid": "PMC12328507",
        "journalInfo": {
            "yearOfPublication": year,
            "journal": [
                {
                    "title": journal_title,
                    "ISSN": {
                        "print": "1439-4227",
                        "electronic": "1439-7633",
                    },
                }
            ],
        },
        "authorList": {
            "author": [
                {
                    "firstName": first_author_first,
                    "lastName": first_author_last,
                    "fullName": f"{first_author_first} {first_author_last}",
                }
            ]
        },
        "abstractText": abstract,
        "keywordList": {"keyword": keywords or []},
        "meshHeadingList": {
            "meshHeading": [
                {"descriptorName": m} for m in (mesh or [])
            ]
        },
        "fullTextUrlList": {"fullTextUrl": full_text_urls or []},
        "citedByCount": cited_by_count,
        "isOpenAccess": is_open_access,
        "firstPublicationDate": first_publication_date,
        "pubYear": pub_year_str,
    }


class TestEuropePMCSearcher:
    def test_default_source_is_europe_pmc(self):
        with EuropePMCSearcher() as s:
            assert s.default_source() == SearchSource.EUROPE_PMC

    def test_search_returns_results(self):
        record = _epmc_record()
        envelope = {"resultList": {"result": [record]}}
        transport = _MockTransport(
            [httpx.Response(200, json=envelope)]
        )
        http_client, mock = _client_with_mock(transport)
        client = EuropePMCSearcher(client=http_client)
        try:
            results = client.search_with_filters(
                SearchFilters(query="amyloid", max_results=5)
            )
        finally:
            client.close()
        assert len(results) == 1
        r = results[0]
        assert r.source == SearchSource.EUROPE_PMC
        assert r.paper.title.startswith("Lipid dynamics")
        assert r.paper.doi == "10.1002/cbic.70398"
        assert r.paper.pmid == "42218803"
        assert r.paper.year == 2026
        assert r.paper.journal is not None
        assert r.paper.journal.name == "Chembiochem"
        assert r.paper.authors[0].first_name == "Sofia"
        assert r.paper.authors[0].last_name == "Serravalle"
        assert r.paper.abstract.startswith("We review")

    def test_search_includes_year_range_in_query(self):
        """The query string should embed ``FIRST_PDATE:[Y TO Y]``."""
        transport = _MockTransport(
            [httpx.Response(200, json={"resultList": {"result": []}})]
        )
        http_client, mock = _client_with_mock(transport)
        client = EuropePMCSearcher(client=http_client)
        try:
            client.search_with_filters(
                SearchFilters(
                    query="amyloid",
                    since_year=2020,
                    until_year=2024,
                )
            )
        finally:
            client.close()
        # Inspect the request URL — the query param contains the
        # range.
        first_call = mock._calls[0]
        url_bytes = str(first_call.url).encode()
        assert b"FIRST_PDATE" in url_bytes
        assert b"2020-01-01" in url_bytes
        assert b"2024-12-31" in url_bytes

    def test_search_with_oa_only_adds_open_access_y(self):
        transport = _MockTransport(
            [httpx.Response(200, json={"resultList": {"result": []}})]
        )
        http_client, mock = _client_with_mock(transport)
        client = EuropePMCSearcher(client=http_client)
        try:
            client.search_with_filters(
                SearchFilters(query="x", open_access_only=True)
            )
        finally:
            client.close()
        assert b"OPEN_ACCESS%3AY" in str(mock._calls[0].url).encode()

    def test_get_by_id_pmid(self):
        record = _epmc_record()
        envelope = {"resultList": {"result": [record]}}
        transport = _MockTransport(
            [httpx.Response(200, json=envelope)]
        )
        http_client, mock = _client_with_mock(transport)
        client = EuropePMCSearcher(client=http_client)
        try:
            paper = client.get_by_id("42218803")
        finally:
            client.close()
        assert paper is not None
        assert paper.pmid == "42218803"

    def test_get_by_id_returns_none_on_empty(self):
        transport = _MockTransport(
            [httpx.Response(200, json={"resultList": {"result": []}})]
        )
        http_client, mock = _client_with_mock(transport)
        client = EuropePMCSearcher(client=http_client)
        try:
            paper = client.get_by_id("99999999")
        finally:
            client.close()
        assert paper is None


# ---------------------------------------------------------------------
# bioRxiv client
# ---------------------------------------------------------------------


def _biorxiv_record(
    *,
    title: str = "A new route for integron cassette dissemination",
    doi: str = "10.1101/2022.09.11.507474",
    preprint_date: str = "2022-09-13",
    authors: str = (
        "Loot, C.; Millot, G.; Richard, E.; Darracq, B."
    ),
    category: str = "genetics",
    abstract: str = "Integrons are genetic...",
    published_journal: str | None = None,
) -> dict[str, Any]:
    return {
        "preprint_title": title,
        "preprint_doi": doi,
        "preprint_date": preprint_date,
        "preprint_authors": authors,
        "preprint_category": category,
        "preprint_abstract": abstract,
        "published_journal": published_journal,
    }


class TestBiorxivSearcher:
    def test_default_source_is_biorxiv(self):
        with BiorxivSearcher() as s:
            assert s.default_source() == SearchSource.BIORXIV

    def test_invalid_server_rejected(self):
        with pytest.raises(ValueError):
            BiorxivSearcher(server="not-a-server")

    def test_search_with_no_date_window_returns_empty(self):
        """bioRxiv can't search by query — only by date window."""
        transport = _MockTransport([])  # no responses needed
        http_client, mock = _client_with_mock(transport)
        client = BiorxivSearcher(client=http_client)
        try:
            results = client.search_with_filters(
                SearchFilters(query="anything")
            )
        finally:
            client.close()
        assert results == []
        assert mock._calls == []  # No HTTP call made.

    def test_search_with_date_window_returns_results(self):
        record = _biorxiv_record()
        envelope = {
            "messages": [
                {"status": "ok", "total": "1", "count": 1}
            ],
            "collection": [record],
        }
        transport = _MockTransport(
            [httpx.Response(200, json=envelope)]
        )
        http_client, mock = _client_with_mock(transport)
        client = BiorxivSearcher(client=http_client)
        try:
            results = client.search_with_filters(
                SearchFilters(
                    query="amyloid",  # ignored by bioRxiv
                    since_year=2022,
                    until_year=2022,
                    max_results=5,
                )
            )
        finally:
            client.close()
        assert len(results) == 1
        r = results[0]
        assert r.source == SearchSource.BIORXIV
        assert r.paper.title.startswith("A new route")
        assert r.paper.doi == "10.1101/2022.09.11.507474"
        assert r.paper.year == 2022
        assert r.paper.pmid is None  # bioRxiv never has PMID.
        assert r.paper.keywords == ["genetics"]

    def test_get_by_id_returns_paper(self):
        record = _biorxiv_record()
        envelope = {"collection": [record]}
        transport = _MockTransport(
            [httpx.Response(200, json=envelope)]
        )
        http_client, mock = _client_with_mock(transport)
        client = BiorxivSearcher(client=http_client)
        try:
            paper = client.get_by_id("10.1101/2022.09.11.507474")
        finally:
            client.close()
        assert paper is not None
        assert paper.doi == "10.1101/2022.09.11.507474"

    def test_parse_authors_handles_comma_initials(self):
        """``"Last, F."`` format."""
        from app.infrastructure.literature.biorxiv_client import (
            _parse_authors,
        )

        authors = _parse_authors("Loot, C.; Millot, G.")
        assert authors[0].first_name == "C."
        assert authors[0].last_name == "Loot"
        assert authors[1].first_name == "G."
        assert authors[1].last_name == "Millot"

    def test_parse_authors_handles_space_format(self):
        """``"First Last"`` format."""
        from app.infrastructure.literature.biorxiv_client import (
            _parse_authors,
        )

        authors = _parse_authors("Fermin Travi; Pablo Polosecki")
        assert authors[0].first_name == "Fermin"
        assert authors[0].last_name == "Travi"


# ---------------------------------------------------------------------
# MultiSourceSearcher
# ---------------------------------------------------------------------


class _StubSearcher(LiteratureSearcher):
    """Minimal LiteratureSearcher stub for fan-out tests."""

    def __init__(self, results: list[SearchResult]) -> None:
        super().__init__()
        self._results = results
        self.calls: list[SearchFilters] = []

    def search(self, question) -> list[Paper]:
        """Legacy single-source entry point — delegates to
        :meth:`search_with_filters` and unwraps the
        SearchResult to the Paper payload.
        """
        results = self.search_with_filters(
            SearchFilters(query=question.question)
        )
        return [r.paper for r in results]

    def search_with_filters(self, filters: SearchFilters) -> list[SearchResult]:
        self.calls.append(filters)
        # Filter the cached results by query match so each
        # test exercises dedup + ranking meaningfully.
        out: list[SearchResult] = []
        for r in self._results:
            if filters.query.lower() in r.paper.title.lower():
                out.append(r)
        return out

    def get_by_id(self, paper_id: str) -> Paper | None:
        for r in self._results:
            if r.paper.doi and r.paper.doi == paper_id:
                return r.paper
            if r.paper.pmid and r.paper.pmid == paper_id:
                return r.paper
        return None

    def default_source(self) -> SearchSource:  # type: ignore[override]
        return SearchSource.PUBMED


class TestMultiSourceSearcher:
    def test_fan_out_calls_every_registered_source(self):
        pubmed = _StubSearcher([])
        openalex = _StubSearcher([])
        mss = MultiSourceSearcher(
            {SearchSource.PUBMED: pubmed, SearchSource.OPENALEX: openalex}
        )
        mss.search_with_filters(SearchFilters(query="foo"))
        assert len(pubmed.calls) == 1
        assert len(openalex.calls) == 1

    def test_dedupes_on_doi(self):
        paper_a = _make_paper(
            title="Paper A", doi="10.1234/example", year=2024
        )
        paper_b = _make_paper(
            title="Paper B", doi="10.1234/other", year=2024
        )
        # Both sources return the same paper — same DOI.
        same_doi_result_pubmed = SearchResult(
            paper=paper_a, source=SearchSource.PUBMED, confidence=0.9
        )
        same_doi_result_openalex = SearchResult(
            paper=paper_a, source=SearchSource.OPENALEX, confidence=0.7
        )
        only_pubmed = SearchResult(
            paper=paper_b, source=SearchSource.PUBMED, confidence=0.5
        )

        pubmed = _StubSearcher([same_doi_result_pubmed, only_pubmed])
        openalex = _StubSearcher([same_doi_result_openalex])
        mss = MultiSourceSearcher(
            {SearchSource.PUBMED: pubmed, SearchSource.OPENALEX: openalex}
        )
        results = mss.search_with_filters(
            SearchFilters(query="Paper", max_results=10)
        )
        assert len(results) == 2  # deduped
        dois = {r.paper.doi for r in results}
        assert dois == {"10.1234/example", "10.1234/other"}
        # The deduped paper's confidence is the average (0.8).
        example = next(
            r for r in results if r.paper.doi == "10.1234/example"
        )
        assert example.confidence == pytest.approx(0.8)

    def test_dedupes_on_pmid_when_no_doi(self):
        paper = _make_paper(title="Paper X", pmid="12345", year=2024)
        pubmed_result = SearchResult(
            paper=paper, source=SearchSource.PUBMED, confidence=0.9
        )
        europe_pmc_result = SearchResult(
            paper=paper, source=SearchSource.EUROPE_PMC, confidence=0.7
        )
        pubmed = _StubSearcher([pubmed_result])
        europe_pmc = _StubSearcher([europe_pmc_result])
        mss = MultiSourceSearcher(
            {
                SearchSource.PUBMED: pubmed,
                SearchSource.EUROPE_PMC: europe_pmc,
            }
        )
        results = mss.search_with_filters(
            SearchFilters(query="Paper", max_results=10)
        )
        assert len(results) == 1
        assert results[0].paper.pmid == "12345"

    def test_ranks_newer_papers_higher(self):
        """Newer papers rank above older papers with similar
        confidence thanks to the recency boost."""
        # PubMed has slightly higher confidence; OpenAlex
        # slightly lower. Both are realistic.
        old = SearchResult(
            paper=_make_paper(title="Paper Old", year=2010),
            source=SearchSource.PUBMED,
            confidence=0.85,
        )
        new = SearchResult(
            paper=_make_paper(title="Paper New", year=2025),
            source=SearchSource.OPENALEX,
            confidence=0.7,
        )
        pubmed = _StubSearcher([old])
        openalex = _StubSearcher([new])
        mss = MultiSourceSearcher(
            {SearchSource.PUBMED: pubmed, SearchSource.OPENALEX: openalex}
        )
        results = mss.search_with_filters(
            SearchFilters(query="Paper", max_results=10)
        )
        assert len(results) == 2
        assert results[0].paper.year == 2025  # New beats Old.

    def test_search_with_sources_restricts_subset(self):
        a = _StubSearcher([])
        b = _StubSearcher([])
        c = _StubSearcher([])
        mss = MultiSourceSearcher(
            {
                SearchSource.PUBMED: a,
                SearchSource.OPENALEX: b,
                SearchSource.EUROPE_PMC: c,
            }
        )
        mss.search_with_sources(
            SearchFilters(query="foo"),
            sources=[SearchSource.PUBMED],
        )
        assert len(a.calls) == 1
        assert len(b.calls) == 0
        assert len(c.calls) == 0

    def test_search_with_sources_falls_back_to_defaults_when_empty(
        self,
    ):
        """Calling with no matching sources warns and falls
        back to all registered sources."""
        a = _StubSearcher([])
        b = _StubSearcher([])
        mss = MultiSourceSearcher(
            {
                SearchSource.PUBMED: a,
                SearchSource.OPENALEX: b,
            }
        )
        # Empty sources iterable — falls back.
        mss.search_with_sources(
            SearchFilters(query="foo"),
            sources=[],
        )
        assert len(a.calls) == 1
        assert len(b.calls) == 1

    def test_partial_failure_does_not_break_search(self):
        """A source that raises is logged and skipped."""

        class _BoomSearcher(_StubSearcher):
            def search_with_filters(self, filters):
                raise RuntimeError("simulated upstream outage")

        good = _StubSearcher(
            [
                SearchResult(
                    paper=_make_paper(title="Good paper"),
                    source=SearchSource.PUBMED,
                    confidence=0.7,
                )
            ]
        )
        boom = _BoomSearcher([])
        mss = MultiSourceSearcher(
            {
                SearchSource.PUBMED: good,
                SearchSource.OPENALEX: boom,
            }
        )
        results = mss.search_with_filters(
            SearchFilters(query="Good")
        )
        assert len(results) == 1
        assert results[0].paper.title == "Good paper"


# ---------------------------------------------------------------------
# SearchSource enum
# ---------------------------------------------------------------------


class TestSearchSourceEnum:
    def test_from_string_lowercases(self):
        assert (
            SearchSource.from_string("OPENALEX") == SearchSource.OPENALEX
        )

    def test_from_string_falls_back_to_pubmed(self):
        assert (
            SearchSource.from_string("not-a-source")
            == SearchSource.PUBMED
        )

    def test_default_sources_includes_pubmed_and_openalex(self):
        defaults = default_sources()
        assert SearchSource.PUBMED in defaults
        assert SearchSource.OPENALEX in defaults
