"""
paper.py

Domain entity representing a scientific publication.

The Paper entity is one of the core objects in BioResearch AI. It provides
a provider-agnostic representation of a biomedical publication, independent
of where the information was retrieved (e.g., PubMed, Europe PMC,
Semantic Scholar).

This module belongs to the Domain layer and therefore must not depend on
external APIs, databases, or AI providers.

Author:
    Guillermo Ramajo Fernández

Created:
    2026
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities.author import Author
from app.domain.entities.journal import Journal


@dataclass(frozen=True, slots=True)
class Paper:
    """
    Represents a scientific publication.

    This entity encapsulates the metadata associated with a research paper.
    It serves as the canonical representation of literature throughout the
    application and is exchanged between the Domain, Application, and
    Infrastructure layers.

    Attributes
    ----------
    title : str
        Title of the publication.

    authors : list[Author]
        Ordered list of paper authors.

    journal : Journal
        Journal where the paper was published.

    year : int | None
        Publication year.

    abstract : str
        Paper abstract. May be empty if no abstract
        could be retrieved from any source.

    inferred_abstract : bool
        ``True`` when the abstract was retrieved via
        the LLM-based extraction fallback (verbatim
        text pulled from the publisher's HTML page
        by an LLM that was asked to extract -- not
        generate -- the abstract). ``False`` when the
        abstract came from a structured source
        (CrossRef, OpenAlex, PubMed) or from the
        deterministic HTML meta-tag regex. The flag
        exists so the frontend can display a
        provenance badge ("AI-extracted") for
        transparency. Default ``False``.

    doi : str | None
        Digital Object Identifier.

    pmid : str | None
        PubMed identifier.

    keywords : list[str]
        Keywords associated with the publication.

    url : str | None
        URL pointing to the publication.
    """

    title: str

    authors: list[Author] = field(default_factory=list)

    journal: Journal | None = None

    year: int | None = None

    abstract: str = ""

    # Provenance flag for the abstract field. See the
    # docstring above for the contract. Default False
    # so legacy Paper(...) constructions keep working.
    inferred_abstract: bool = False

    doi: str | None = None

    pmid: str | None = None

    keywords: list[str] = field(default_factory=list)

    url: str | None = None

    @property
    def has_abstract(self) -> bool:
        """
        Determine whether the publication contains an abstract.

        Returns
        -------
        bool
            True if a non-empty abstract is available.
        """
        return bool(self.abstract.strip())

    @property
    def has_doi(self) -> bool:
        """
        Determine whether the publication has a DOI.

        Returns
        -------
        bool
            True if the DOI is available.
        """
        return self.doi is not None

    @property
    def has_pmid(self) -> bool:
        """
        Determine whether the publication has a PubMed identifier.

        Returns
        -------
        bool
            True if the PMID is available.
        """
        return self.pmid is not None

    @property
    def first_author(self) -> Author | None:
        """
        Return the first author of the publication.

        Returns
        -------
        Author | None
            The first author if available; otherwise None.
        """
        if not self.authors:
            return None

        return self.authors[0]

    def citation(self) -> str:
        """
        Generate a simple human-readable citation.

        This method intentionally returns a lightweight citation suitable
        for console output and debugging. Dedicated citation formatting
        (APA, MLA, Vancouver, etc.) should be implemented by the
        Citation domain entity.

        Returns
        -------
        str
            A concise citation string.
        """
        first_author = self.first_author

        if first_author is None:
            author = "Unknown Author"
        else:
            author = first_author.full_name

        year = self.year if self.year is not None else "n.d."

        return f"{author} ({year}). {self.title}"

    def short_summary(self, max_length: int = 250) -> str:
        """
        Return a shortened version of the abstract.

        Parameters
        ----------
        max_length : int, default=250
            Maximum number of characters to return.

        Returns
        -------
        str
            Truncated abstract suitable for previews.
        """
        if len(self.abstract) <= max_length:
            return self.abstract

        return self.abstract[:max_length].rstrip() + "..."