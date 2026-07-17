"""
mapper.py

PubMed record mapper.

Purpose
-------
This module implements the Anti-Corruption Layer (ACL) responsible for
translating raw PubMed records returned by the NCBI Entrez API into the
domain entities used throughout BioResearch AI.

The structure returned by PubMed is deeply nested and tightly coupled to
the external service. The remainder of the application should never
depend on that representation. Instead, this mapper isolates every
PubMed-specific detail behind a stable domain model.

Architecture
------------

NCBI Entrez API
        │
        ▼
Raw PubMed Record
        │
        ▼
   PubMedMapper
        │
        ▼
Paper
Author
Journal

Responsibilities
----------------
- Convert raw PubMed records into domain entities.
- Handle missing metadata gracefully.
- Isolate PubMed-specific parsing logic.
- Provide a stable interface to the application layer.

Non-responsibilities
--------------------
This class does NOT:

- Perform HTTP requests.
- Search PubMed.
- Generate summaries.
- Call language models.
- Apply business rules.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper


class PubMedMapper:
    """
    Utility class responsible for translating PubMed records into domain
    entities.

    All methods are stateless and deterministic, making the mapper easy
    to test and reuse.
    """

    @classmethod
    def to_paper(cls, record: dict) -> Paper:
        """
        Convert a PubMed record into a Paper entity.

        Parameters
        ----------
        record
            Raw publication metadata returned by the Entrez API.

        Returns
        -------
        Paper
            Domain representation of the publication.
        """

        return Paper(
            title=cls._extract_title(record),
            abstract=cls._extract_abstract(record),
            authors=cls.to_authors(record),
            journal=cls.to_journal(record),
            year=cls._extract_year(record),
            doi=cls._extract_doi(record),
            pmid=cls._extract_pmid(record),
            keywords=cls._extract_keywords(record),
            url=cls._extract_url(record),
        )

    @classmethod
    def to_authors(cls, record: dict) -> list[Author]:
        """
        Extract the list of publication authors.

        Missing author information results in an empty list.

        Parameters
        ----------
        record
            Raw PubMed publication.

        Returns
        -------
        list[Author]
            Parsed author entities.
        """

        try:
            author_list = (
                record["MedlineCitation"]["Article"]["AuthorList"]
            )
        except (KeyError, IndexError, TypeError):
            return []

        authors: list[Author] = []

        for author in author_list:
            authors.append(
                Author(
                    first_name=author.get("ForeName", ""),
                    last_name=author.get("LastName", ""),
                )
            )

        return authors

    @classmethod
    def to_journal(cls, record: dict) -> Journal:
        """
        Extract journal information.

        Parameters
        ----------
        record
            Raw PubMed publication.

        Returns
        -------
        Journal
            Parsed journal entity.
        """

        journal = (
            record.get("MedlineCitation", {})
            .get("Article", {})
            .get("Journal", {})
        )

        return Journal(
            name=journal.get("Title", ""),
            issn=journal.get("ISSN"),
        )

    @staticmethod
    def _extract_title(record: dict) -> str:
        """
        Extract the publication title.
        """

        return (
            record.get("MedlineCitation", {})
            .get("Article", {})
            .get("ArticleTitle", "")
        )

    @staticmethod
    def _extract_abstract(record: dict) -> str:
        """
        Extract the publication abstract.

        Returns an empty string when no abstract is available.
        """

        try:
            abstract = (
                record["MedlineCitation"]
                ["Article"]
                ["Abstract"]
                ["AbstractText"]
            )

            return " ".join(str(section) for section in abstract)

        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def _extract_year(record: dict) -> int | None:
        """
        Extract the publication year.

        Returns
        -------
        int | None
            Publication year if available.
        """

        try:
            year = (
                record["MedlineCitation"]
                ["Article"]
                ["Journal"]
                ["JournalIssue"]
                ["PubDate"]
                ["Year"]
            )

            return int(year)

        except (KeyError, ValueError, TypeError):
            return None

    @staticmethod
    def _extract_doi(record: dict) -> str | None:
        """
        Extract the DOI.
        """

        article_ids = (
            record.get("PubmedData", {})
            .get("ArticleIdList", [])
        )

        for identifier in article_ids:
            if identifier.attributes.get("IdType") == "doi":
                return str(identifier)

        return None

    @staticmethod
    def _extract_pmid(record: dict) -> str | None:
        """
        Extract the PubMed identifier.
        """

        try:
            return str(record["MedlineCitation"]["PMID"])

        except (KeyError, TypeError):
            return None

    @staticmethod
    def _extract_keywords(record: dict) -> list[str]:
        """
        Extract publication keywords.

        Returns an empty list if keywords are unavailable.
        """

        try:
            keywords = (
                record["MedlineCitation"]["KeywordList"][0]
            )

            return [str(keyword) for keyword in keywords]

        except (KeyError, IndexError, TypeError):
            return []

    @staticmethod
    def _extract_url(record: dict) -> str | None:
        """
        Build the canonical PubMed URL.
        """

        pmid = PubMedMapper._extract_pmid(record)

        if pmid is None:
            return None

        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"