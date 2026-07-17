"""
workspace_service.py

Application service for Research Workspace management.

Purpose
-------
This module defines the :class:`WorkspaceService`, responsible for
coordinating workspace lifecycle operations within the BioResearch AI
application.

The service acts as an application-level façade over workspace-related
use cases. External clients should interact with this service rather than
calling individual use cases directly.

The service does not contain domain business rules or persistence logic.
It coordinates application workflows and delegates responsibilities to
the appropriate use cases.

Typical clients include:

- ResearchAssistant façade
- REST APIs
- Command-line interfaces
- Streamlit applications
- Jupyter notebooks
- MCP servers
- Agent-to-Agent (A2A) systems
- LangGraph workflows

Current Responsibilities
------------------------
The service coordinates:

- Research workspace creation.
- Research workspace retrieval.
- Research workspace updates.

Future versions may support:

- Workspace duplication.
- Workspace archival.
- Workspace export/import.
- Session versioning.
- Collaboration.
- Sharing.
- Research history.
- Automatic checkpoints.

Architecture
------------

                  Client
                    │
                    ▼
             WorkspaceService
          ┌─────────┼─────────┐
          ▼         ▼         ▼
     Create UC   Get UC   Update UC
          │         │         │
          └─────────┼─────────┘
                    ▼
          WorkspaceRepository

The public interface of this service should remain stable while internal
implementation details evolve.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from uuid import UUID

from app.application.use_cases.create_workspace import CreateWorkspaceUseCase
from app.application.use_cases.get_workspace import GetWorkspaceUseCase
from app.application.use_cases.update_workspace import UpdateWorkspaceUseCase

from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_session import ResearchSession


class WorkspaceService:
    """
    High-level application service for research workspace management.

    This service provides a stable application interface for workspace
    lifecycle operations while hiding the internal organization of the
    underlying use cases.

    Parameters
    ----------
    create_workspace_use_case
        Creates new research workspaces.

    get_workspace_use_case
        Retrieves existing research workspaces.

    update_workspace_use_case
        Persists modifications made to research workspaces.
    """

    def __init__(
        self,
        create_workspace_use_case: CreateWorkspaceUseCase,
        get_workspace_use_case: GetWorkspaceUseCase,
        update_workspace_use_case: UpdateWorkspaceUseCase,
    ) -> None:
        """
        Initialize the workspace service.

        Parameters
        ----------
        create_workspace_use_case
            Configured workspace creation use case.

        get_workspace_use_case
            Configured workspace retrieval use case.

        update_workspace_use_case
            Configured workspace update use case.
        """

        self._create_workspace_use_case = (
            create_workspace_use_case
        )

        self._get_workspace_use_case = (
            get_workspace_use_case
        )

        self._update_workspace_use_case = (
            update_workspace_use_case
        )

    def create_workspace(
        self,
        question: str,
    ) -> ResearchSession:
        """
        Create a new biomedical research workspace.

        The supplied question is converted into a domain
        :class:`ResearchQuestion` entity. Validation of the question
        belongs to the domain model.

        Parameters
        ----------
        question
            Initial biomedical research question.

        Returns
        -------
        ResearchSession
            Newly created research session.
        """

        research_question = ResearchQuestion(
            question=question,
        )

        return self._create_workspace_use_case.execute(
            research_question
        )

    def get_workspace(
        self,
        workspace_id: UUID,
    ) -> ResearchSession:
        """
        Retrieve an existing research workspace.

        Parameters
        ----------
        workspace_id
            UUID identifying the research session.

        Returns
        -------
        ResearchSession
            Retrieved research session.
        """

        return self._get_workspace_use_case.execute(
            workspace_id
        )

    def update_workspace(
        self,
        workspace: ResearchSession,
    ) -> ResearchSession:
        """
        Persist modifications made to a research workspace.

        Parameters
        ----------
        workspace
            Updated research session aggregate.

        Returns
        -------
        ResearchSession
            Persisted research session.
        """

        return self._update_workspace_use_case.execute(
            workspace
        )