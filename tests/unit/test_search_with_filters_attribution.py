"""
test_search_with_filters_attribution.py

Integration-style tests for the ``search_with_filters``
entry point of ``WorkspaceOrchestrator`` — specifically
the path that populates ``session.paper_sources`` with the
per-paper source attribution.

These exercise the wiring between the orchestrator,
``MultiSourceSearcher``, and ``ResearchSession.replace_papers``
without hitting any real network or LLM. The unit-level
shape checks live in ``test_paper_source_map.py``.
"""

from __future__ import annotations

import pytest

from app.application.services.workspace_orchestrator import (
    WorkspaceOrchestrator,
)
from app.core.enums.search_source import SearchSource
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_session import ResearchSession
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.interfaces.literature_searcher import LiteratureSearcher
from app.domain.interfaces.report_generator import ReportGenerator
from app.domain.interfaces.comparison_generator import (
    ComparisonGenerator,
)
from app.domain.value_objects.search_filters import SearchFilters
from app.domain.value_objects.search_result import SearchResult
from app.infrastructure.literature.multi_source import MultiSourceSearcher


class _StubPerSourceSearcher(LiteratureSearcher):
    """Stub that yields a fixed list of papers tagged with a
    specific source."""

    def __init__(
        self,
        source: SearchSource,
        results: list[tuple[str | None, str | None, str, str]],
    ) -> None:
        """
        Parameters
        ----------
        source : SearchSource
            Which source this stub represents. Used by the
            ``MultiSourceSearcher`` adapter when building the
            ``SearchResult`` envelope.
        results : list[tuple[str | None, str | None, str, str]]
            ``[(pmid_or_None, doi_or_None, title, abstract)]``.
        """
        super().__init__()
        self._source = source
        self._results = results

    def search(self, question) -> list[Paper]:
        # Legacy single-source entry point — not used in
        # these tests; ``search_with_filters`` is the path
        # under test. Return [] to make accidental use
        # obvious.
        return []

    def search_with_filters(self, filters: SearchFilters):
        return [
            SearchResult(
                paper=Paper(
                    title=title,
                    pmid=pmid if pmid else None,
                    doi=doi if doi else None,
                    abstract=abstract,
                ),
                source=self._source,
                confidence=0.9,
            )
            for pmid, doi, title, abstract in self._results
        ]

    def get_by_id(self, paper_id: str) -> Paper | None:
        return None

    def default_source(self) -> SearchSource:  # type: ignore[override]
        return self._source


class _StubLLM(LLMProvider):
    def generate(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def agenerate(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


class _StubReportGenerator(ReportGenerator):
    def generate(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


class _StubComparisonGenerator(ComparisonGenerator):
    def generate(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def fake_repo():
    """Tiny in-memory repository to back the orchestrator."""

    class _Repo:
        def __init__(self):
            self.store: dict = {}

        def create(self, session: ResearchSession) -> None:
            self.store[session.id] = session

        def get(self, workspace_id):
            return self.store[workspace_id]

        def update(self, session: ResearchSession) -> ResearchSession:
            self.store[session.id] = session
            return session

    return _Repo()


def _orchestrator(
    *,
    repo,
    multi_source: MultiSourceSearcher,
) -> WorkspaceOrchestrator:
    """Build a WorkspaceOrchestrator wired to the multi-source
    searcher and a stubbed LLM / report / comparison stack."""
    return WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=multi_source,
        llm_provider=_StubLLM(),
        report_generator=_StubReportGenerator(),
        comparison_generator=_StubComparisonGenerator(),
    )


class TestSearchWithFiltersAttribution:
    def test_session_paper_sources_is_populated_after_search(
        self,
        fake_repo,
    ) -> None:
        multi = MultiSourceSearcher(
            searchers={
                SearchSource.PUBMED: _StubPerSourceSearcher(
                    SearchSource.PUBMED,
                    [
                        ("11111", None, "PubMed paper", ""),
                    ],
                ),
                SearchSource.OPENALEX: _StubPerSourceSearcher(
                    SearchSource.OPENALEX,
                    [
                        (None, "10.1/openalex", "OpenAlex paper", ""),
                    ],
                ),
            },
        )
        orch = _orchestrator(repo=fake_repo, multi_source=multi)
        ws = ResearchSession(
            question=ResearchQuestion(question="What is X?"),
        )
        fake_repo.create(ws)

        result = orch.search_with_filters(
            ws.id,
            filters=SearchFilters(query="What is X?"),
        )

        # The orchestrator returns the updated session —
        # the paper_sources map should be populated.
        assert "11111" in result.paper_sources
        assert "10.1/openalex" in result.paper_sources
        assert result.paper_sources["11111"] == "pubmed"
        assert result.paper_sources["10.1/openalex"] == "openalex"

    def test_session_paper_sources_is_persisted_in_repository(
        self,
        fake_repo,
    ) -> None:
        multi = MultiSourceSearcher(
            searchers={
                SearchSource.OPENALEX: _StubPerSourceSearcher(
                    SearchSource.OPENALEX,
                    [
                        (None, "10.1/x", "X", ""),
                    ],
                ),
            },
        )
        orch = _orchestrator(repo=fake_repo, multi_source=multi)
        ws = ResearchSession(
            question=ResearchQuestion(question="What is X?"),
        )
        fake_repo.create(ws)

        orch.search_with_filters(
            ws.id,
            filters=SearchFilters(query="What is X?"),
        )

        # Reload from the repository — the attribution
        # should have been persisted alongside the papers.
        loaded = fake_repo.get(ws.id)
        assert loaded.paper_sources["10.1/x"] == "openalex"

    def test_restricted_source_set_only_includes_those_sources(
        self,
        fake_repo,
    ) -> None:
        multi = MultiSourceSearcher(
            searchers={
                SearchSource.PUBMED: _StubPerSourceSearcher(
                    SearchSource.PUBMED,
                    [("1", None, "PubMed", "")],
                ),
                SearchSource.OPENALEX: _StubPerSourceSearcher(
                    SearchSource.OPENALEX,
                    [(None, "10.1/oa", "OpenAlex", "")],
                ),
            },
        )
        orch = _orchestrator(repo=fake_repo, multi_source=multi)
        ws = ResearchSession(
            question=ResearchQuestion(question="What is X?"),
        )
        fake_repo.create(ws)

        # Restrict to OpenAlex only.
        result = orch.search_with_filters(
            ws.id,
            filters=SearchFilters(query="What is X?"),
            sources=[SearchSource.OPENALEX],
        )

        # Only OpenAlex attribution should be present.
        assert "10.1/oa" in result.paper_sources
        assert "1" not in result.paper_sources
        assert result.paper_sources["10.1/oa"] == "openalex"

    def test_legacy_search_does_not_populate_paper_sources(
        self,
        fake_repo,
    ) -> None:
        # The legacy single-source path strips the
        # ``SearchResult`` envelope without attribution —
        # legacy users should NOT suddenly see a
        # ``"via PubMed"`` badge on pre-existing papers.
        # Verify the legacy ``search`` method leaves
        # ``paper_sources`` empty.
        multi = MultiSourceSearcher(
            searchers={
                SearchSource.PUBMED: _StubPerSourceSearcher(
                    SearchSource.PUBMED,
                    [
                        ("12345", None, "Legacy paper", ""),
                    ],
                ),
            },
        )
        orch = _orchestrator(repo=fake_repo, multi_source=multi)
        ws = ResearchSession(
            question=ResearchQuestion(question="What is X?"),
        )
        fake_repo.create(ws)

        result = orch.search(ws.id)

        # Legacy path: no paper_sources map.
        assert result.paper_sources == {}
        assert "12345" not in result.paper_sources
