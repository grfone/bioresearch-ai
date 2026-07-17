"""
get_workspace.py

Application use case for retrieving research workspaces.

Purpose
-------
This module defines the :class:`GetWorkspaceUseCase`, responsible for
retrieving an existing :class:`ResearchSession` from the configured
workspace repository.

Within Clean Architecture, the use case belongs to the Application layer
and depends exclusively on the repository abstraction defined by the
application. It contains no knowledge of persistence technologies,
presentation frameworks, or external services.

The use case provides the application entry point for loading previously
created biomedical research workspaces.

Responsibilities
----------------
The use case coordinates the following operations:

- Validate the workspace identifier.
- Retrieve the corresponding research session.
- Return the requested aggregate.

Future versions may additionally support:

- Authorization and access control.
- Optimistic concurrency control.
- Audit logging.
- Cached retrieval.
- Lazy loading of workspace resources.
- Workspace versioning.

Architecture
------------

          Workspace Identifier
                    │
                    ▼
        GetWorkspaceUseCase
                    │
                    ▼
        WorkspaceRepository
                    │
                    ▼
           ResearchSession

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from uuid import UUID

from app.domain.entities.research_session import ResearchSession
from app.domain.interfaces.workspace_repository import WorkspaceRepository


class GetWorkspaceUseCase:
    """
    Retrieve an existing biomedical research workspace.

    The GetWorkspaceUseCase coordinates the retrieval of a previously
    created :class:`ResearchSession` while remaining independent of the
    underlying persistence mechanism.

    Parameters
    ----------
    workspace_repository
        Repository responsible for retrieving research workspaces.
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
            Configured repository used to retrieve research workspaces.
        """

        self._workspace_repository = workspace_repository

    def execute(
        self,
        workspace_id: UUID,
    ) -> ResearchSession:
        """
        Retrieve a research workspace.

        Parameters
        ----------
        workspace_id
            Unique identifier of the research workspace.

        Returns
        -------
        ResearchSession
            Retrieved research session.

        Raises
        ------
        ValueError
            If the supplied workspace identifier is None.
        """

        if workspace_id is None:
            raise ValueError(
                "Workspace identifier cannot be None."
            )

        return self._workspace_repository.get(
            workspace_id
        )