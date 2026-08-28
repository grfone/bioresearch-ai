"""
workspace.py

REST API endpoints for BioResearch AI Research Workspaces.

Purpose
-------
This module exposes HTTP endpoints responsible for managing biomedical
research workspaces.

A Research Workspace represents the persistent state of a biomedical
investigation, including:

- the initial research question;
- retrieved scientific literature;
- generated summaries;
- generated reports;
- workflow metadata.

The API layer is responsible only for:

- HTTP request handling;
- request validation;
- response serialization;
- translating application exceptions into HTTP responses.

Business logic remains inside the application layer.

Architecture
------------

             HTTP Client
                  |
                  |
            FastAPI Router
                  |
                  |
          ResearchAssistant
                  |
                  |
          WorkspaceService
                  |
                  |
        Workspace Use Cases
                  |
                  |
        WorkspaceRepository


Endpoints
----------

POST /workspaces
    Create a new research workspace.

GET /workspaces/{workspace_id}
    Retrieve an existing workspace.

PUT /workspaces/{workspace_id}
    Persist workspace modifications.

Future versions may support:

- workspace sharing;
- authentication;
- user ownership;
- collaborative research;
- workspace export;
- workspace versioning.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status

from app.api.schemas.workspace_request import (
    WorkspaceRequest,
)

from app.api.schemas.workspace_response import (
    WorkspaceResponse,
)

from app.application.services.research_assistant import (
    ResearchAssistant,
)

from app.config.container import get_research_assistant

# Import the domain ResearchQuestion if needed
# from app.domain.entities.research_question import ResearchQuestion


router = APIRouter(
    prefix="/workspaces",
    tags=["Workspaces"],
)


# ``get_research_assistant`` is imported from
# ``app.config.container`` so the canonical dependency
# provider (with its module-level singleton cache) is used.
# This avoids building a fresh ``ResearchAssistant`` on
# every request -- ``Container.build()`` constructs a new
# orchestrator, search use case, summarizer, and report
# generator every call. The shared instance is safe
# because the underlying components are stateless across
# requests (the workspace repository has its own
# singleton via ``Container._workspace_repository``).


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace(
    request: WorkspaceRequest,
    assistant: ResearchAssistant = Depends(
        get_research_assistant
    ),
) -> WorkspaceResponse:
    """
    Create a new biomedical research workspace.

    Parameters
    ----------
    request
        Workspace creation payload.

    assistant
        Application facade dependency.

    Returns
    -------
    WorkspaceResponse
        Newly created workspace.

    Raises
    ------
    HTTPException
        If workspace creation fails.
    """
    try:
        workspace = assistant.create_workspace(
            request.question
        )

        # Use from_domain to properly map the domain object to the response schema
        return WorkspaceResponse.from_domain(
            workspace
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
)
def get_workspace(
    workspace_id: UUID,
    assistant: ResearchAssistant = Depends(
        get_research_assistant
    ),
) -> WorkspaceResponse:
    """
    Retrieve a biomedical research workspace.

    Parameters
    ----------
    workspace_id
        Unique workspace identifier.

    assistant
        Application facade dependency.

    Returns
    -------
    WorkspaceResponse
        Serialized research workspace.

    Raises
    ------
    HTTPException
        If the workspace does not exist.
    """
    try:
        workspace = assistant.get_workspace(
            workspace_id
        )

        return WorkspaceResponse.from_domain(
            workspace
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.put(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
)
def update_workspace(
    workspace_id: UUID,
    request: WorkspaceRequest,
    assistant: ResearchAssistant = Depends(
        get_research_assistant
    ),
) -> WorkspaceResponse:
    """
    Update an existing research workspace.

    Notes
    -----
    The current workspace model is aggregate-based, meaning the complete
    ResearchSession object must eventually be reconstructed before saving.

    This endpoint currently supports the workspace lifecycle contract.
    More granular updates may be introduced later:

    - add papers;
    - update summary;
    - regenerate report;
    - append research notes.

    Parameters
    ----------
    workspace_id
        Workspace identifier.

    request
        Updated workspace information.

    assistant
        Application facade dependency.

    Returns
    -------
    WorkspaceResponse
        Updated workspace.
    """
    try:
        # Retrieve the existing workspace
        workspace = assistant.get_workspace(workspace_id)

        # Convert the string question to a ResearchQuestion object
        # Ensure ResearchQuestion is imported.
        # If your domain expects a plain string, you can remove this conversion.
        from app.domain.entities.research_question import ResearchQuestion
        workspace.question = ResearchQuestion(question=request.question)

        # Persist the updated workspace
        # Assuming the method is called 'update_workspace' – adjust if needed.
        updated_workspace = assistant.update_workspace(workspace)

        return WorkspaceResponse.from_domain(
            updated_workspace
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )