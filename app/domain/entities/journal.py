"""
journal.py

Domain entity representing a scientific journal.

This module defines the :class:`Journal` entity, which models a scientific
journal independently of any specific publication.

The Journal entity belongs to the Domain layer of the application and
contains only business-related information. It must not depend on external
libraries, APIs, databases, or infrastructure components.

Examples
--------
    journal = Journal(
        name="Nature",
        issn="0028-0836",
        publisher="Springer Nature"
    )

    journal.name
    'Nature'
"""

from dataclasses import dataclass


@dataclass(slots=True)
class Journal:
    """
    Represents a scientific journal.

    A journal is the publication venue where one or more scientific papers
    are published.

    Notes
    -----
    This entity intentionally represents only the journal itself.
    Information such as volume, issue, page numbers, and publication year
    belongs to individual papers rather than the journal.

    Attributes
    ----------
    name : str
        Official journal name.

    issn : str | None, default=None
        International Standard Serial Number.

    publisher : str | None, default=None
        Publishing organization responsible for the journal.
    """

    name: str
    issn: str | None = None
    publisher: str | None = None

    @property
    def display_name(self) -> str:
        """
        Return a human-readable journal name.

        Returns
        -------
        str
            The journal name.

        Examples
        --------
        journal.display_name
        'Nature'
        """
        return self.name

    def __str__(self) -> str:
        """
        Return the journal name.

        Returns
        -------
        str
            The journal name.
        """
        return self.name