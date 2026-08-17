"""
literature_searcher.py

Domain interface defining the contract for biomedical literature retrieval.

Purpose
-------
This module declares the abstract interface responsible for retrieving
scientific publications relevant to biomedical research workflows.

Following the Dependency Inversion Principle, the application layer
depends only on this abstraction and remains completely independent of
specific literature providers or external APIs.

Concrete implementations may retrieve publications from different sources
without requiring modifications to the application layer.

Supported implementations may include:

- PubMed
- OpenAlex
- Europe PMC
- bioRxiv / medRxiv
- CrossRef (identifier resolver only)
- Local document repositories
- Vector databases
- MCP-compatible knowledge providers

Architecture
------------

Application Layer
        |
        |
LiteratureSearcher (interface)
        |
        |
Infrastructure Implementations

The interface represents the boundary between the Application and
Infrastructure layers.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod

from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion


class LiteratureSearcher(ABC):
    """
    Abstract interface for biomedical literature retrieval.

    Implementations are responsible for locating scientific publications
    and returning them as domain entities.

    The interface intentionally hides provider-specific details such as:

    - HTTP communication.
    - Authentication.
    - XML/JSON parsing.
    - Pagination.
    - Rate limiting.
    - Provider-specific response formats.
    - External identifier systems.

    The application layer interacts exclusively with this abstraction.
    """

    @abstractmethod
    def search(
        self,
        question: ResearchQuestion,
    ) -> list[Paper]:
        """
        Retrieve publications relevant to a research question.

        This is the legacy single-source entry point. Kept for
        backward compatibility with the original PubMed-only
        flow. New clients SHOULD override
        :meth:`search_with_filters` for full filter support;
        the default ``search_with_filters`` implementation
        delegates here so the legacy method keeps working.

        Parameters
        ----------
        question : ResearchQuestion
            Scientific question submitted by the researcher.

        Returns
        -------
        list[Paper]
            Scientific publications represented as domain entities.
        """
        ...

    def search_with_filters(self, filters):
        """Retrieve publications with the full filter bundle.

        This is the modern entry point. Each provider implementation
        SHOULD override this for full filter support; the default
        delegates to :meth:`search` so legacy single-source
        providers continue to work unchanged.

        Parameters
        ----------
        filters : SearchFilters
            Bundle of filters (query, year bounds, sort, max
            results, open-access flag, document types).

        Returns
        -------
        list[SearchResult]
            :class:`SearchResult` records. Each carries the
            source attribution (:class:`SearchSource`) and a
            confidence score in [0.0, 1.0].

        Notes
        -----
        Providers should silently drop filter values they don't
        support — e.g. bioRxiv's chronological dump ignores
        ``sort_by``. The :class:`MultiSourceSearcher` reconciles
        the partial results.
        """
        # Local imports to avoid a circular import at module
        # load time (search_filters / search_result import
        # back into the domain layer).
        from app.domain.value_objects.search_filters import (
            SearchFilters,
        )
        from app.domain.value_objects.search_result import (
            SearchResult,
        )
        from app.core.enums.search_source import SearchSource

        if not isinstance(filters, SearchFilters):
            raise TypeError(
                "search_with_filters requires a SearchFilters "
                "instance; got "
                f"{type(filters).__name__}."
            )
        question = ResearchQuestion(question=filters.query)
        papers = self.search(question)
        source = self.default_source()
        return [
            SearchResult(paper=p, source=source)
            for p in papers[: filters.max_results]
        ]

    def default_source(self):
        """Which :class:`SearchSource` does this searcher
        represent? Subclasses override for OpenAlex / Europe
        PMC / bioRxiv; default is :attr:`SearchSource.PUBMED`
        for backward compatibility.
        """
        from app.core.enums.search_source import SearchSource

        return SearchSource.PUBMED

    # ``default_source`` has no abstract decorator so we
    # don't force subclasses to override it — the type
    # annotation lives on the implementation, not the
    # abstract method, to avoid a forward reference cycle.

    @abstractmethod
    def get_by_id(
        self,
        paper_id: str,
    ) -> Paper | None:
        """
        Retrieve a scientific publication by identifier.

        This method provides access to an individual publication when the
        identifier is already known.

        The identifier format is intentionally provider-independent.
        Implementations may support identifiers such as:

        - PMID
        - DOI
        - Accession identifiers
        - Internal repository identifiers

        Parameters
        ----------
        paper_id : str
            External or internal identifier of the publication.

        Returns
        -------
        Paper | None
            Matching scientific publication if found.

            Returns None when no publication exists for the supplied
            identifier.

        Notes
        -----
        Concrete implementations are responsible for interpreting the
        identifier and communicating with the underlying literature source.
        """
        ...
