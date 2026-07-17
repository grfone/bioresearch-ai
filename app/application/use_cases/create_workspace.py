"""
create_workspace.py

Application use case responsible for creating a new Research Workspace.

Purpose
-------
This module defines the CreateWorkspaceUseCase, which initializes a new
ResearchSession and persists it through the configured
WorkspaceRepository.

Within Clean Architecture, this use case belongs to the Application layer.
Its responsibility is to coordinate the creation of a workspace while
remaining independent of persistence technologies and presentation
frameworks.

Responsibilities
----------------
- Validate the incoming research question.
- Create a new ResearchSession.
- Persist the workspace.
- Return the persisted workspace.

The use case intentionally contains very little business logic.
Complex workspace lifecycle management belongs to dedicated application
services or future orchestration workflows.

Architecture
------------

      Research Question
              │
              ▼
 CreateWorkspaceUseCase
              │
              ▼
    WorkspaceRepository
              │
              ▼
      ResearchSession

Future versions may support:

- user ownership;
- collaborative workspaces;
- project templates;
- metadata initialization;
- automatic workspace naming;
- audit logging.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_session import ResearchSession
from app.domain.interfaces.workspace_repository import WorkspaceRepository


class CreateWorkspaceUseCase:
    """
    Create and persist a new biomedical research workspace.

    This use case initializes a new :class:`ResearchSession` from an
    existing :class:`ResearchQuestion` domain entity and delegates its
    persistence to the configured :class:`WorkspaceRepository`.

    The use case assumes that the supplied ResearchQuestion has already
    been validated by the domain model.
    """

    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
    ) -> None:
        """
        Initialize the use case.

        Parameters
        ----------
        workspace_repository
            Repository responsible for workspace persistence.
        """

        self._workspace_repository = workspace_repository

    def execute(
        self,
        question: ResearchQuestion,
    ) -> ResearchSession:
        """
        Create a new research workspace.

        A new :class:`ResearchSession` aggregate is initialized using the
        supplied research question and persisted through the configured
        repository.

        Parameters
        ----------
        question
            Validated biomedical research question.

        Returns
        -------
        ResearchSession
            Newly created and persisted research workspace.

        Raises
        ------
        ValueError
            If the supplied research question is None.
        """

        if question is None:
            raise ValueError(
                "Research question cannot be None."
            )

        workspace = ResearchSession(
            question=question,
        )

        return self._workspace_repository.create(
            workspace
        )