"""
papers.py

REST API endpoints for biomedical literature retrieval.

This module exposes endpoints responsible for searching and retrieving
scientific publications from supported biomedical literature databases.

The route belongs to the Presentation layer of BioResearch AI and serves
as the entry point for clients wishing to perform literature searches.

The module intentionally contains no business logic. Its responsibilities
are limited to:

- validating HTTP requests;
- invoking the application layer;
- translating domain objects into API response schemas;
- returning appropriate HTTP status codes.

Architecture
------------

        HTTP Request
              │
              ▼
         Papers Router
              │
              ▼
      ResearchAssistant
              │
              ▼
 SearchLiteratureUseCase
              │
              ▼
   LiteratureSearcher
              │
              ▼
           PubMed

Future versions may support:

- pagination;
- publication date filters;
- MeSH filtering;
- journal filtering;
- sorting;
- semantic search;
- multiple literature providers.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status

from app.application.services.research_assistant import (
    ResearchAssistant,
)

from app.config.container import get_research_assistant

from app.api.schemas.search_request import SearchRequest
from app.api.schemas.search_response import SearchResponse


router = APIRouter(
    prefix="/papers",
    tags=["Scientific Literature"],
)


@router.post(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search biomedical literature",
    description="""
Search biomedical literature relevant to a scientific research question.

The endpoint queries the configured literature provider (currently
PubMed) and returns the retrieved scientific publications.

Future versions may support multiple providers and advanced search
strategies.
""",
)
def search_papers(
    request: SearchRequest,
    assistant: Annotated[
        ResearchAssistant,
        Depends(get_research_assistant),
    ],
) -> SearchResponse:
    """
    Retrieve biomedical literature.

    Parameters
    ----------
    request : SearchRequest
        Biomedical research question.

    assistant : ResearchAssistant
        Application facade responsible for orchestrating literature
        retrieval.

    Returns
    -------
    SearchResponse
        Retrieved scientific publications.

    Raises
    ------
    HTTPException
        Returned if the request cannot be processed.
    """

    try:

        #
        # NOTE
        # ----
        # This method assumes ResearchAssistant will expose a future
        # `search_papers()` method.
        #
        # For the current milestone, implement:
        #
        # papers = assistant.search_papers(request.question)
        #
        # instead of calling the use case directly.
        #

        papers = assistant.search_papers(
            request.question
        )

        return SearchResponse.from_papers(
            query=request.question,
            papers=papers,
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while searching biomedical literature.",
        ) from exc