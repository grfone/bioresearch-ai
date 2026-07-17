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
- Europe PMC
- Semantic Scholar
- CrossRef
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