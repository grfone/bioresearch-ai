"""
knowledge_base.py

Defines the abstract interface for biological knowledge sources.

A KnowledgeBase represents any external source of biomedical information,
such as PubMed, UniProt, OpenTargets, ChEMBL, ClinicalTrials.gov, or an
internal vector database.

The application layer interacts exclusively with this interface rather
than concrete implementations. This follows the Dependency Inversion
Principle, allowing knowledge providers to be replaced without modifying
business logic.

Examples
--------
Future implementations include:

- PubMedKnowledgeBase
- UniProtKnowledgeBase
- OpenTargetsKnowledgeBase
- ClinicalTrialsKnowledgeBase
- ChromaKnowledgeBase
- FAISSKnowledgeBase

Notes
-----
This interface intentionally avoids exposing implementation-specific
details (HTTP requests, SQL queries, vector search, etc.). Those belong
to the Infrastructure layer.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class KnowledgeBase(ABC):
    """
    Abstract interface for biomedical knowledge providers.

    Concrete implementations expose biological knowledge while hiding
    the underlying data source.

    The application layer should depend only on this interface,
    allowing new knowledge providers to be incorporated without
    changing the core application logic.
    """

    @abstractmethod
    def search(self, query: str) -> list[Any]:
        """
        Search the knowledge base.

        Parameters
        ----------
        query : str
            User query or search expression.

        Returns
        -------
        list[Any]
            A collection of domain objects matching the query.

        Notes
        -----
        The returned objects depend on the implementation.
        Examples include Paper, Protein, Gene, Disease, Drug,
        Clinical Trial, or other biological entities.
        """
        raise NotImplementedError

    @abstractmethod
    def retrieve(self, identifier: str) -> Any:
        """
        Retrieve a specific entity by its unique identifier.

        Parameters
        ----------
        identifier : str
            Identifier defined by the underlying knowledge source
            (e.g. PMID, DOI, UniProt accession, Ensembl ID).

        Returns
        -------
        Any
            The requested domain object.

        Raises
        ------
        LookupError
            If the requested entity cannot be found.
        """
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """
        Determine whether the knowledge source is currently available.

        Returns
        -------
        bool
            True if the provider is reachable and operational,
            False otherwise.
        """
        raise NotImplementedError