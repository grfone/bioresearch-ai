"""
search_literature.py

Application Use Case
--------------------

This module contains the SearchLiteratureUseCase, responsible for retrieving
scientific publications relevant to a user's research question.

The use case coordinates the application's business logic while remaining
independent of any specific literature provider (e.g. PubMed, OpenAlex,
Europe PMC, bioRxiv).

By depending only on the LiteratureSearcher interface, different search
implementations can be introduced without modifying this use case.

Responsibilities
----------------
- Validate the incoming research question / filter bundle.
- Delegate the search operation to a LiteratureSearcher.
- Return the retrieved Paper entities (legacy) or SearchResult records
  with per-source attribution (new).

This class intentionally contains very little logic. Complex retrieval
strategies (multi-source fan-out, ranking, dedupe, retries) belong
inside the concrete searcher (``MultiSourceSearcher`` for the fan-out)
or dedicated services.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from collections.abc import Iterable

from app.core.enums.search_source import SearchSource
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.interfaces.literature_searcher import LiteratureSearcher
from app.domain.value_objects.search_filters import SearchFilters
from app.domain.value_objects.search_result import SearchResult


class SearchLiteratureUseCase:
    """Retrieve scientific literature for a research question.

    This use case represents the first step in the BioResearch AI pipeline.

        Research Question
                |
                ▼
        SearchLiteratureUseCase
                |
                ▼
        LiteratureSearcher
                |
                ▼
           List[Paper]

    Notes
    -----
    The use case depends exclusively on the LiteratureSearcher abstraction.

    The legacy single-source path (``execute(question)``) is preserved
    for the ``/api/search`` endpoint, which still takes a
    ``ResearchQuestion`` and returns ``list[Paper]``. New code paths
    (the Advanced Search modal in the UI, the
    ``WorkspaceOrchestrator.search`` action) use
    ``execute_with_filters(filters, sources)`` and get back
    ``list[SearchResult]`` with per-source attribution.

    Multi-source fan-out is handled by the searcher itself
    (``MultiSourceSearcher``) — the use case just forwards the
    filter bundle.
    """

    def __init__(self, literature_searcher: LiteratureSearcher) -> None:
        """Initialize the use case.

        Parameters
        ----------
        literature_searcher : LiteratureSearcher
            Concrete implementation (or ``MultiSourceSearcher``
            wrapper) responsible for retrieving publications.
        """
        self._literature_searcher = literature_searcher

    def execute(self, question: ResearchQuestion) -> list[Paper]:
        """Search scientific literature related to a research question.

        Legacy single-source entry point. Delegates to
        ``execute_with_filters`` and unwraps the ``SearchResult``
        envelope to ``list[Paper]`` for backward compatibility
        with the ``/api/search`` route.

        Parameters
        ----------
        question : ResearchQuestion
            User's scientific question.

        Returns
        -------
        list[Paper]
            List of retrieved scientific publications.

        Raises
        ------
        ValueError
            If the research question is empty.
        """
        if not question.question.strip():
            raise ValueError("Research question cannot be empty.")

        filters = SearchFilters(query=question.question)
        results = self.execute_with_filters(filters)
        return [r.paper for r in results]

    def execute_with_filters(
        self,
        filters: SearchFilters,
        sources: Iterable[SearchSource] | None = None,
    ) -> list[SearchResult]:
        """Search with the full filter bundle and optional source set.

        New (multi-source) entry point. Used by the
        ``WorkspaceOrchestrator.search`` action when the
        Advanced Search modal supplies a filter bundle.

        Parameters
        ----------
        filters : SearchFilters
            Bundle of filters (query, year bounds, sort, max
            results, open-access flag, document types).
        sources : Iterable[SearchSource] | None
            Optional restricted source set. When supplied, the
            underlying ``MultiSourceSearcher`` only fans out
            to those sources (if they're registered). When
            ``None``, every registered source is used.

        Returns
        -------
        list[SearchResult]
            :class:`SearchResult` records. Each carries the
            source attribution (:class:`SearchSource`) and a
            confidence score in [0.0, 1.0].

        Raises
        ------
        ValueError
            If ``filters.query`` is empty (validated by the
            ``SearchFilters`` ``__post_init__``).
        """
        # The MultiSourceSearcher exposes a
        # ``search_with_sources`` method; the
        # ``LiteratureSearcher`` interface itself only has
        # ``search_with_filters``. We dispatch via the
        # richer interface when available so the
        # source-restriction semantics work.
        if sources is not None and hasattr(
            self._literature_searcher, "search_with_sources"
        ):
            return self._literature_searcher.search_with_sources(  # type: ignore[attr-defined]
                filters, sources
            )
        return self._literature_searcher.search_with_filters(filters)
