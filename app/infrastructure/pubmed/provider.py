"""
provider.py

PubMed literature provider.

Purpose
-------
This module implements the infrastructure adapter responsible for
retrieving biomedical literature from PubMed.

Following the Dependency Inversion Principle, the application layer
depends only on the ``LiteratureSearcher`` interface, while this class
provides the concrete implementation backed by the PubMed (NCBI Entrez)
API.

The provider orchestrates the complete retrieval workflow:

    ResearchQuestion
            │
            ▼
     PubMed query string
            │
            ▼
      PubMedClient.search()
            │
            ▼
      PubMedClient.fetch()
            │
            ▼
       Raw PubMed records
            │
            ▼
        PubMedMapper
            │
            ▼
        List[Paper]

Responsibilities
----------------
- Receive research questions.
- Translate them into PubMed queries.
- Retrieve matching publications.
- Convert raw API responses into domain entities.
- Hide every PubMed-specific implementation detail from the application.

Non-responsibilities
--------------------
This class does NOT:

- Perform HTTP requests.
- Parse XML structures.
- Generate summaries.
- Rank scientific evidence.
- Call Large Language Models.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.interfaces.literature_searcher import LiteratureSearcher

from .client import PubMedClient
from .mapper import PubMedMapper


class PubMedProvider(LiteratureSearcher):
    """
    PubMed implementation of the LiteratureSearcher interface.

    This class coordinates the retrieval of scientific publications from
    PubMed while keeping the application layer completely independent of
    the underlying API.
    """

    def __init__(
        self,
        client: PubMedClient,
        max_results: int = 20,
    ) -> None:
        """
        Initialize the provider.

        Parameters
        ----------
        client
            Configured PubMed client.

        max_results
            Maximum number of publications retrieved for each query.
        """

        self._client = client
        self._max_results = max_results

    # ------------------------------------------------------------------
    # LiteratureSearcher implementation
    # ------------------------------------------------------------------

    def search(
        self,
        question: ResearchQuestion,
    ) -> list[Paper]:
        """
        Retrieve scientific publications relevant to a research question.

        Parameters
        ----------
        question
            User research question.

        Returns
        -------
        list[Paper]
            Retrieved scientific publications.
        """

        query = self._prepare_query(question)

        pmids = self._client.search(
            query=query,
            limit=self._max_results,
        )

        records = self._client.fetch(pmids)

        return self._build_papers(records)

    # ------------------------------------------------------------------
    # Internal helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_query(
        question: ResearchQuestion,
    ) -> str:
        """
        Build a PubMed-compatible query.

        Parameters
        ----------
        question
            User research question.

        Returns
        -------
        str
            Query string understood by PubMed.

        Notes
        -----
        The current implementation simply forwards the user's question.

        Future versions may include:

        - Query expansion
        - MeSH term mapping
        - Synonym generation
        - Boolean optimization
        - Automatic filters
        """

        return question.question.strip()

    def _build_papers(
        self,
        records: list[dict],
    ) -> list[Paper]:
        """
        Convert raw PubMed records into domain entities.

        Parameters
        ----------
        records
            Raw publication records returned by PubMed.

        Returns
        -------
        list[Paper]
            Parsed scientific publications.
        """

        return [
            self._build_paper(record)
            for record in records
        ]

    @staticmethod
    def _build_paper(
        record: dict,
    ) -> Paper:
        """
        Convert a single PubMed record into a Paper entity.

        Parameters
        ----------
        record
            Raw PubMed record.

        Returns
        -------
        Paper
            Domain representation of the publication.
        """

        return PubMedMapper.to_paper(record)


    def get_by_id(
        self,
        paper_id: str,
    ) -> Paper | None:
        """
        Retrieve a scientific publication from PubMed by identifier.

        Parameters
        ----------
        paper_id
            PubMed identifier (PMID) or compatible publication identifier.

        Returns
        -------
        Paper | None
            Matching scientific publication if found.

            Returns None when no publication exists for the supplied
            identifier.

        Notes
        -----
        The provider delegates retrieval to PubMedClient and converts the
        returned raw record into a domain Paper entity using PubMedMapper.
        """

        if not paper_id.strip():
            return None

        records = self._client.fetch(
            [paper_id.strip()]
        )

        if not records:
            return None

        return PubMedMapper.to_paper(
            records[0]
        )