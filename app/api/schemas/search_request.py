"""
search_request.py

API request schema for biomedical literature search.

This module defines the request model accepted by the literature search
endpoint.

Request schemas belong to the Presentation layer of the application and
are responsible for validating incoming HTTP payloads before they are
converted into domain entities.

The SearchRequest intentionally contains no business logic. It serves
only as a contract between API clients and the application.

Architecture
------------

        HTTP Request (JSON)
                │
                ▼
          SearchRequest
                │
                ▼
      ResearchQuestion (Domain)
                │
                ▼
    SearchLiteratureUseCase

Validation
----------
The schema validates:

- presence of the research question;
- minimum and maximum length;
- automatic whitespace trimming;
- rejection of unexpected fields.

Notes
-----
The request model is intentionally independent of the Domain layer.

The API is responsible for converting a SearchRequest into a
ResearchQuestion before invoking the corresponding application use case.

Author
------
Guillermo Ramajo Fernández
"""

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class SearchRequest(BaseModel):
    """
    Request model for biomedical literature search.

    A SearchRequest represents a scientific question submitted by a user
    wishing to retrieve relevant publications from biomedical literature
    databases.

    Attributes
    ----------
    question : str
        Scientific research question.

    Examples
    --------
    {
        "question": "Compare KRAS G12C inhibitors in non-small cell lung cancer."
    }

    Future Extensions
    -----------------
    Future versions of this request model may support:

    - preferred literature source;
    - publication date filters;
    - publication type filters;
    - maximum number of retrieved papers;
    - language selection;
    - MeSH term constraints;
    - species filters.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    question: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description=(
            "Biomedical research question used to retrieve relevant "
            "scientific publications."
        ),
        examples=[
            "What are the latest biomarkers for Alzheimer's disease?",
            "Compare KRAS G12C inhibitors.",
            "Summarize the evidence supporting CAR-T therapy in glioblastoma.",
        ],
    )