"""
paper_request.py

Pydantic request schema for creating a ``Paper`` from a manual
user upload (as opposed to retrieving one from PubMed). The user
fills in a small form in the frontend; the backend validates the
fields and persists the paper into the workspace.

The minimum required field is the title. Everything else
(authors, journal, year, abstract, doi, pmid, keywords, url) is
optional — papers with just a title are valid scaffolding that
the user can flesh out later.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


# --- nested value objects -------------------------------------------------
# Mirrors the request payload shape used by the existing
# AuthorResponse / JournalResponse but exposed as input types so the
# frontend can submit them directly.


class AuthorRequest(BaseModel):
    """Author submitted by the user."""

    model_config = ConfigDict(from_attributes=True)

    full_name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, strip_whitespace=True),
    ]
    given_name: str | None = None
    family_name: str | None = None


class JournalRequest(BaseModel):
    """Journal submitted by the user."""

    model_config = ConfigDict(from_attributes=True)

    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=300, strip_whitespace=True),
    ]
    issn: str | None = None
    publisher: str | None = None


# --- the paper itself -----------------------------------------------------


class PaperRequest(BaseModel):
    """Payload the frontend sends to ``POST /workspaces/{id}/papers``.

    Attributes
    ----------
    title : str
        Paper title. Required.

    authors : list[AuthorRequest]
        Ordered list of authors. Defaults to an empty list.

    journal : JournalRequest | None
        Publishing journal. Optional.

    year : int | None
        Publication year. Optional.

    abstract : str
        Paper abstract. Optional, defaults to empty string.

    doi : str | None
        Digital Object Identifier. Optional.

    pmid : str | None
        PubMed identifier. Optional.

    keywords : list[str]
        Keywords associated with the publication.

    url : str | None
        URL pointing to the publication.
    """

    model_config = ConfigDict(from_attributes=True)

    title: Annotated[
        str,
        StringConstraints(min_length=1, max_length=500, strip_whitespace=True),
    ]
    authors: list[AuthorRequest] = Field(default_factory=list)
    journal: JournalRequest | None = None
    year: int | None = Field(default=None, ge=1500, le=2200)
    abstract: str = ""
    doi: str | None = None
    pmid: str | None = None
    keywords: list[str] = Field(default_factory=list)
    url: str | None = None