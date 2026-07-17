"""
search.py

REST API routes for biomedical literature search.

Purpose
-------
This module exposes HTTP endpoints responsible for retrieving scientific
publications relevant to a biomedical research question.

The API layer belongs to the Presentation layer of BioResearch AI and
acts as an adapter between external clients and the application facade.

The router is intentionally independent of:

- PubMed
- Literature providers
- Search algorithms
- Database implementations
- LLM providers

All business logic remains inside the Application and Domain layers.

Responsibilities
-----------------
This module is responsible for:

- Receiving validated HTTP requests.
- Delegating search operations to ResearchAssistant.
- Converting domain Paper entities into API response models.
- Returning serialized HTTP responses.

Architecture
------------

        HTTP Client
             |
             |
      SearchRequest
             |
             |
        API Router
             |
             |
     ResearchAssistant
             |
             |
 SearchLiteratureUseCase
             |
             |
 LiteratureSearcher
             |
             |
        List[Paper]
             |
             |
      SearchResponse
             |
             |
        HTTP JSON


Future versions may extend this router with:

- Pagination support.
- Advanced search filters.
- Multiple literature providers.
- Semantic search options.
- Search history.
- Query expansion controls.
- Ranking configuration.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status

from app.api.schemas.search_request import SearchRequest
from app.api.schemas.search_response import SearchResponse

from app.application.services.research_assistant import (
    ResearchAssistant,
)

from app.config.container import Container


router = APIRouter(
    prefix="/search",
    tags=["Literature Search"],
)


def get_research_assistant() -> ResearchAssistant:
    """
    Retrieve the configured application facade.

    This dependency provider exposes the application composition root
    to the API layer without allowing HTTP controllers to instantiate
    infrastructure dependencies directly.

    Returns
    -------
    ResearchAssistant
        Fully configured BioResearch AI application facade.
    """

    return Container.build()


@router.post(
    "",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search biomedical literature",
    description=(
        "Retrieve scientific publications relevant to a biomedical "
        "research question."
    ),
)
def search_literature(
    request: SearchRequest,
    assistant: ResearchAssistant = Depends(
        get_research_assistant
    ),
) -> SearchResponse:
    """
    Search biomedical literature.

    The endpoint receives a validated research question, delegates the
    retrieval workflow to the application facade, and converts the
    resulting domain Paper entities into an API response.

    Parameters
    ----------
    request : SearchRequest
        Validated biomedical research question submitted by the client.

    assistant : ResearchAssistant
        Application facade providing access to research capabilities.

    Returns
    -------
    SearchResponse
        Serialized search results containing scientific publications.

    Raises
    ------
    HTTPException
        HTTP 400 if the research question is invalid.

        HTTP 500 if an unexpected application error occurs.

    Notes
    -----
    The API layer deliberately does not know:

    - which literature database is queried;
    - how queries are constructed;
    - how papers are ranked;
    - how results are processed.

    Those concerns belong to the Application and Infrastructure layers.
    """

    try:
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
            detail=(
                "Unexpected error while searching scientific literature."
            ),
        ) from exc