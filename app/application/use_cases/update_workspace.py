"""
update_workspace.py

Application use case for updating research workspaces.

Purpose
-------
This module defines the :class:`UpdateWorkspaceUseCase`, responsible for
persisting modifications made to an existing biomedical research
workspace.

Within the application architecture, the use case coordinates the update
operation by validating the workspace state and delegating persistence to
the workspace repository abstraction.

The use case contains no infrastructure-specific logic and remains
independent of the underlying storage technology.

Typical modifications include:

- Newly retrieved scientific papers
- Updated evidence summaries
- Generated research reports
- Researcher annotations
- Metadata changes
- Timestamp updates

Architecture
------------

        Client / Service
               │
               ▼
    UpdateWorkspaceUseCase
               │
               ▼
     WorkspaceRepository
               │
      Infrastructure Layer

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.domain.entities.research_session import ResearchSession
from app.domain.interfaces.workspace_repository import WorkspaceRepository


class UpdateWorkspaceUseCase:
    """
    Persist modifications to an existing research workspace.

    This use case serves as the application boundary for saving updates
    made to a :class:`ResearchSession`.

    The workspace is expected to have already been modified by previous
    application workflows (e.g., literature retrieval, evidence
    summarization, report generation, or note creation).

    The use case validates the supplied workspace before delegating the
    persistence operation to the configured repository.
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
        workspace: ResearchSession,
    ) -> ResearchSession:
        """
        Persist an updated research workspace.

        Parameters
        ----------
        workspace
            Research session containing the latest application state.

        Returns
        -------
        ResearchSession
            Persisted workspace.

        Raises
        ------
        ValueError
            If the supplied workspace is invalid.
        """

        if workspace is None:
            raise ValueError(
                "Workspace cannot be None."
            )

        workspace.touch()

        return self._workspace_repository.update(
            workspace
        )