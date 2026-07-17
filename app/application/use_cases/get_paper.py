"""
get_paper.py

Application Use Case
--------------------

This module contains the GetPaperUseCase, responsible for retrieving a
single scientific publication from a literature source.

The use case coordinates the application workflow required to obtain a
specific Paper entity while remaining independent of concrete literature
providers.

The application layer depends only on abstractions. Therefore, this use
case does not know whether the publication is retrieved from:

- PubMed
- Europe PMC
- Semantic Scholar
- Local repositories
- Vector databases
- Future MCP-based literature tools

Responsibilities
----------------
This use case is responsible for:

- Validating the requested paper identifier.
- Delegating retrieval to a literature provider abstraction.
- Returning a domain Paper entity.

It is intentionally lightweight. Provider-specific retrieval logic,
API communication, caching, retries, and ranking strategies belong to the
Infrastructure layer.

Architecture
------------

              Client
                |
                |
        ResearchAssistant
                |
                |
          GetPaperUseCase
                |
                |
     LiteraturePaperProvider
                |
                |
              Paper


Future versions may support:

- Multiple identifier types (PMID, DOI, accession numbers).
- Literature source selection.
- Paper metadata enrichment.
- Citation graph retrieval.
- Full-text availability checks.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.domain.entities.paper import Paper
from app.domain.interfaces.literature_searcher import LiteratureSearcher


class GetPaperUseCase:
    """
    Retrieve a scientific publication by identifier.

    This use case represents the application-level operation required to
    obtain an individual scientific publication.

    The use case depends on the LiteratureSearcher abstraction rather than
    a concrete implementation, allowing the infrastructure layer to change
    without affecting application logic.

    Parameters
    ----------
    literature_searcher : LiteratureSearcher
        Abstraction responsible for accessing scientific literature sources.

    Notes
    -----
    Although the LiteratureSearcher interface was originally designed for
    search operations, it is intentionally reused here until a dedicated
    PaperRepository or LiteratureProvider abstraction is introduced.

    This keeps the architecture simple while the project evolves.
    """

    def __init__(
        self,
        literature_searcher: LiteratureSearcher,
    ) -> None:
        """
        Initialize the GetPaper use case.

        Parameters
        ----------
        literature_searcher : LiteratureSearcher
            Provider abstraction used to retrieve publications.
        """

        self._literature_searcher = literature_searcher

    def execute(
        self,
        paper_id: str,
    ) -> Paper:
        """
        Retrieve a scientific publication.

        Parameters
        ----------
        paper_id : str
            Identifier of the publication.

            Depending on the configured literature provider, this may be:

            - PubMed identifier (PMID)
            - DOI
            - External accession identifier

        Returns
        -------
        Paper
            Domain entity representing the scientific publication.

        Raises
        ------
        ValueError
            If the supplied identifier is empty.

        LookupError
            If the publication cannot be found.

        Notes
        -----
        The use case deliberately performs no provider-specific logic.
        Retrieval strategy belongs to the infrastructure implementation.
        """

        normalized_id = paper_id.strip()

        if not normalized_id:
            raise ValueError(
                "Paper identifier cannot be empty."
            )

        paper = self._literature_searcher.get_by_id(
            normalized_id
        )

        if paper is None:
            raise LookupError(
                f"No scientific publication found for identifier: "
                f"{normalized_id}"
            )

        return paper