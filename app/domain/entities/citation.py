"""
citation.py

Domain entity representing a bibliographic citation.

A Citation encapsulates the logic required to transform a scientific paper
into a formatted reference according to a specific citation style (e.g. APA,
MLA, Vancouver).

The formatted citation is intentionally **not stored**. Instead, it is
generated on demand from the associated Paper entity. This prevents
inconsistencies between the paper metadata and the rendered citation.

Future versions may support additional citation styles and export formats
such as BibTeX, RIS, or EndNote.

Author
------
Guillermo Ramajo Fernández
"""

from dataclasses import dataclass

from app.core.enums.citation_style import CitationStyleEnum
from app.domain.entities.paper import Paper


@dataclass(slots=True)
class Citation:
    """
    Represents a bibliographic citation for a scientific publication.

    Parameters
    ----------
    paper : Paper
        Scientific publication to be cited.

    style : CitationStyleEnum, default=CitationStyleEnum.APA
        Citation format to use.

    Notes
    -----
    This class belongs to the Domain layer and therefore contains no
    dependency on external citation libraries.

    Formatting logic should remain lightweight. If more sophisticated
    formatting becomes necessary, this class can delegate the work to a
    dedicated CitationFormatter service in the Application layer.
    """

    paper: Paper
    style: CitationStyleEnum = CitationStyleEnum.APA

    def format(self) -> str:
        """
        Generate a formatted citation.

        Returns
        -------
        str
            The formatted citation.

        Raises
        ------
        NotImplementedError
            Until citation formatting is implemented.
        """
        raise NotImplementedError(
            f"Citation formatting for {self.style.value} "
            "has not been implemented yet."
        )

    def to_markdown(self) -> str:
        """
        Return the citation formatted for Markdown documents.

        Returns
        -------
        str
            Markdown representation of the citation.
        """
        return f"- {self.format()}"

    def to_dict(self) -> dict:
        """
        Serialize the citation into a dictionary.

        Returns
        -------
        dict
            Serializable representation of the citation.
        """
        return {
            "style": self.style.value,
            "paper_title": self.paper.title,
            "doi": self.paper.doi,
            "pmid": self.paper.pmid,
        }

    def __str__(self) -> str:
        """
        Return the formatted citation.

        Returns
        -------
        str
            Human-readable citation.
        """
        return self.format()