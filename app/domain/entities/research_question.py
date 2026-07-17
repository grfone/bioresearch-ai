"""
research_question.py

Domain entity representing a biomedical research question.

This module defines the `ResearchQuestion` entity, which encapsulates the
scientific question provided by a user together with any metadata required
to perform literature retrieval and downstream reasoning.

The entity belongs to the Domain layer of the application and therefore
contains no infrastructure-specific logic (e.g., PubMed queries, LLM calls,
or database operations). Its purpose is to model the problem being solved,
independently of how the application retrieves or processes information.

Examples
--------
    question = ResearchQuestion(
        question="What is the role of KRAS G12D in pancreatic cancer?",
        keywords=["KRAS", "G12D", "pancreatic cancer"]
    )
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class ResearchQuestion:
    """
    Represents a biomedical research question.

    A research question is the starting point of every workflow in
    BioResearch AI. It contains the original question submitted by the
    user together with optional metadata that can guide literature
    retrieval or downstream analysis.

    Attributes
    ----------
    question : str
        The original research question provided by the user.

    keywords : list[str]
        Keywords extracted manually or automatically from the question.
        These can be used by literature search engines to improve
        retrieval quality.

    filters : dict[str, str]
        Optional search constraints.

        Examples include:

        - publication year
        - journal
        - organism
        - publication type
        - language

        NOTE:
        This field may eventually be replaced by a dedicated
        `SearchFilters` entity as the project evolves.
    """

    question: str

    keywords: list[str] = field(default_factory=list)

    filters: dict[str, str] = field(default_factory=dict)

    def has_keywords(self) -> bool:
        """
        Determine whether the research question already contains keywords.

        Returns
        -------
        bool
            True if one or more keywords have been assigned;
            otherwise False.
        """
        return len(self.keywords) > 0

    def add_keyword(self, keyword: str) -> None:
        """
        Add a keyword to the research question.

        Duplicate keywords (case-insensitive) are ignored.

        Parameters
        ----------
        keyword : str
            Keyword to add.
        """
        normalized = keyword.strip()

        if not normalized:
            return

        existing = {k.lower() for k in self.keywords}

        if normalized.lower() not in existing:
            self.keywords.append(normalized)

    def __str__(self) -> str:
        """
        Return a human-readable representation of the research question.

        Returns
        -------
        str
            The original question.
        """
        return self.question