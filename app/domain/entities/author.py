"""
author.py

Domain entity representing an author of a scientific publication.

This module defines the :class:`Author` entity, one of the core domain
objects used throughout BioResearch AI. Authors are associated with
scientific papers and provide attribution and affiliation information.

The domain layer is intentionally independent of external services,
databases, or AI frameworks. Consequently, this class contains only
business-relevant information and no infrastructure-specific logic.
"""

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Author:
    """
    Represents an author of a scientific publication.

    Attributes:
        first_name:
            The author's given name.

        last_name:
            The author's family name.

        affiliation:
            The institution or organization with which the author is
            affiliated. This field is optional because affiliation
            information is not always available from external databases.

    Example:
        author = Author(
            first_name="Jane",
            last_name="Doe",
            affiliation="Massachusetts Institute of Technology"
            )

            author.full_name
            'Jane Doe'
    """

    first_name: str
    last_name: str
    affiliation: str | None = None

    @property
    def full_name(self) -> str:
        """
        Return the author's full name.

        Returns:
            The author's full name in the format
            "<first_name> <last_name>".

        Example:
            author.full_name
            'Jane Doe'
        """
        return f"{self.first_name} {self.last_name}"

    def __str__(self) -> str:
        """
        Return a human-readable representation of the author.

        Returns:
            The author's full name.
        """
        return self.full_name