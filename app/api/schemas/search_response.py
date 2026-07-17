"""
search_response.py

API response schemas for biomedical literature search.

This module defines the response models returned by the literature search
endpoint.

Response schemas belong to the Presentation layer and are responsible for
serializing domain entities into JSON representations suitable for HTTP
responses.

Unlike domain entities, response schemas are optimized for client
applications and remain independent of the internal implementation of
the system.

Architecture
------------

                Domain Layer

             List[Paper]
                   │
                   ▼
          SearchResponse
                   │
                   ▼
              HTTP JSON

The response models intentionally mirror the domain hierarchy:

SearchResponse
    └── PaperResponse
            ├── AuthorResponse
            └── JournalResponse

This design allows client applications to evolve independently of the
domain layer while preserving a rich representation of biomedical
literature.

Future versions may include:

- pagination
- search execution metrics
- ranking scores
- MeSH annotations
- semantic search metadata
- citation counts
- journal impact factors

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from app.domain.entities.paper import Paper


class AuthorResponse(BaseModel):
    """
    Serialized representation of a scientific author.

    Attributes
    ----------
    first_name : str
        Author's given name.

    last_name : str
        Author's family name.

    full_name : str
        Full author name.

    affiliation : str | None
        Author affiliation, when available.
    """

    model_config = ConfigDict(from_attributes=True)

    first_name: str

    last_name: str

    full_name: str

    affiliation: str | None = None


class JournalResponse(BaseModel):
    """
    Serialized representation of a scientific journal.

    Attributes
    ----------
    name : str
        Journal name.

    issn : str | None
        International Standard Serial Number.

    publisher : str | None
        Journal publisher.
    """

    model_config = ConfigDict(from_attributes=True)

    name: str

    issn: str | None = None

    publisher: str | None = None


class PaperResponse(BaseModel):
    """
    Serialized representation of a scientific publication.

    This schema exposes publication metadata while remaining independent
    of the internal domain model.

    Attributes
    ----------
    title : str
        Publication title.

    authors : list[AuthorResponse]
        Ordered list of publication authors.

    journal : JournalResponse | None
        Publishing journal.

    year : int | None
        Publication year.

    abstract : str
        Publication abstract.

    doi : str | None
        Digital Object Identifier.

    pmid : str | None
        PubMed identifier.

    keywords : list[str]
        Publication keywords.

    url : str | None
        URL pointing to the publication.
    """

    model_config = ConfigDict(from_attributes=True)

    title: str

    authors: list[AuthorResponse] = Field(default_factory=list)

    journal: JournalResponse | None = None

    year: int | None = None

    abstract: str = ""

    doi: str | None = None

    pmid: str | None = None

    keywords: list[str] = Field(default_factory=list)

    url: str | None = None

    @classmethod
    def from_domain(cls, paper: Paper) -> "PaperResponse":
        """
        Create a PaperResponse from a domain Paper entity.

        Parameters
        ----------
        paper : Paper
            Scientific publication.

        Returns
        -------
        PaperResponse
            Serialized publication.
        """

        journal = None

        if paper.journal is not None:
            journal = JournalResponse(
                name=paper.journal.name,
                issn=paper.journal.issn,
                publisher=paper.journal.publisher,
            )

        return cls(
            title=paper.title,
            authors=[
                AuthorResponse(
                    first_name=author.first_name,
                    last_name=author.last_name,
                    full_name=author.full_name,
                    affiliation=author.affiliation,
                )
                for author in paper.authors
            ],
            journal=journal,
            year=paper.year,
            abstract=paper.abstract,
            doi=paper.doi,
            pmid=paper.pmid,
            keywords=paper.keywords,
            url=paper.url,
        )


class SearchResponse(BaseModel):
    """
    Response returned after a biomedical literature search.

    A SearchResponse represents the complete result of a literature
    retrieval operation, including search metadata and the retrieved
    scientific publications.

    Attributes
    ----------
    query : str
        Original research question.

    source : str
        Literature provider.

    total_results : int
        Number of retrieved publications.

    retrieved_at : datetime
        UTC timestamp indicating when the search completed.

    papers : list[PaperResponse]
        Retrieved publications.
    """

    model_config = ConfigDict(from_attributes=True)

    query: str = Field(
        description="Original biomedical research question."
    )

    source: str = Field(
        description="Literature provider used for the search.",
        examples=["PubMed"],
    )

    total_results: int = Field(
        ge=0,
        description="Number of retrieved publications.",
    )

    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp indicating when the search completed.",
    )

    papers: list[PaperResponse] = Field(
        default_factory=list,
        description="Retrieved scientific publications.",
    )

    @property
    def has_results(self) -> bool:
        """
        Determine whether the search returned any publications.

        Returns
        -------
        bool
            True if one or more publications were retrieved.
        """
        return self.total_results > 0

    @classmethod
    def from_papers(
        cls,
        query: str,
        papers: list[Paper],
        source: str = "PubMed",
    ) -> "SearchResponse":
        """
        Create a SearchResponse from domain Paper entities.

        Parameters
        ----------
        query : str
            Original biomedical research question.

        papers : list[Paper]
            Retrieved publications.

        source : str, default="PubMed"
            Literature provider.

        Returns
        -------
        SearchResponse
            Serialized API response.
        """

        return cls(
            query=query,
            source=source,
            total_results=len(papers),
            papers=[
                PaperResponse.from_domain(paper)
                for paper in papers
            ],
        )