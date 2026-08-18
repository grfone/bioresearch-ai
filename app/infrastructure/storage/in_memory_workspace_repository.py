"""
in_memory_workspace_repository.py

In-memory implementation of the WorkspaceRepository interface.

Purpose
-------
This module provides an in-memory persistence implementation for
ResearchSession entities.

It is primarily intended for:

- Local development.
- Unit testing.
- Rapid prototyping.
- Demonstration environments.

The repository stores research workspaces in a Python dictionary keyed by
their UUID identifier.

Because all data is stored in application memory, this implementation is
not suitable for production deployments where persistence, durability,
and scalability are required.

The implementation respects the WorkspaceRepository contract, allowing it
to be replaced by persistent storage solutions such as:

- PostgreSQL.
- MongoDB.
- Redis.
- Cloud databases.
- File-based storage.

Responsibilities
----------------
- Persist newly created research workspaces.
- Retrieve existing research workspaces.
- Update workspace state.
- Delete research workspaces.
- Verify workspace existence.
- List stored workspaces.

Architecture
------------

                Application Layer
                        │
                        ▼
            WorkspaceRepository
                        │
                        ▼
      InMemoryWorkspaceRepository
                        │
                        ▼
        dict[UUID, ResearchSession]

This implementation contains no business logic.
Its responsibility is limited to persistence management.

Thread Safety
-------------
This repository is not thread-safe.

It should only be used in environments where concurrent writes are not
required.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from uuid import UUID

from app.core.enums.workspace_state import WorkspaceState
from app.domain.entities.research_session import ResearchSession
from app.domain.interfaces.workspace_repository import WorkspaceRepository


class InMemoryWorkspaceRepository(WorkspaceRepository):
    """
    In-memory implementation of the WorkspaceRepository interface.

    Research workspaces are stored in an internal dictionary indexed by
    their UUID identifier.

    Notes
    -----
    Data is lost when the application process terminates.

    This implementation is intended for:

    - Local development.
    - Automated tests.
    - Early prototypes.
    - Example applications.

    Production systems should replace this repository with a persistent
    implementation.
    """

    def __init__(self) -> None:
        """
        Initialize an empty in-memory workspace repository.
        """

        self._workspaces: dict[UUID, ResearchSession] = {}

    def create(
        self,
        workspace: ResearchSession,
    ) -> ResearchSession:
        """
        Persist a newly created research workspace.

        Parameters
        ----------
        workspace
            Research session aggregate to persist.

        Returns
        -------
        ResearchSession
            Persisted research session.

        Raises
        ------
        ValueError
            If a workspace with the same UUID already exists.
        """

        if workspace.id in self._workspaces:
            raise ValueError(
                f"Workspace '{workspace.id}' already exists."
            )

        self._workspaces[workspace.id] = workspace

        return workspace

    def get(
        self,
        workspace_id: UUID,
    ) -> ResearchSession:
        """
        Retrieve a research workspace by UUID.

        Parameters
        ----------
        workspace_id
            Unique identifier of the workspace.

        Returns
        -------
        ResearchSession
            Requested research session.

        Raises
        ------
        ValueError
            If the workspace does not exist.
        """

        workspace = self._workspaces.get(
            workspace_id
        )

        if workspace is None:
            raise ValueError(
                f"Workspace '{workspace_id}' was not found."
            )

        return workspace

    def update(
        self,
        workspace: ResearchSession,
    ) -> ResearchSession:
        """
        Persist modifications made to an existing workspace.

        Parameters
        ----------
        workspace
            Updated research session aggregate.

        Returns
        -------
        ResearchSession
            Updated persisted research session.

        Raises
        ------
        ValueError
            If the workspace does not exist.
        """

        if workspace.id not in self._workspaces:
            raise ValueError(
                f"Workspace '{workspace.id}' does not exist."
            )

        self._workspaces[workspace.id] = workspace

        return workspace

    def delete(
        self,
        workspace_id: UUID,
    ) -> None:
        """
        Remove a research workspace.

        Parameters
        ----------
        workspace_id
            Unique identifier of the workspace.

        Raises
        ------
        ValueError
            If the workspace does not exist.
        """

        if workspace_id not in self._workspaces:
            raise ValueError(
                f"Workspace '{workspace_id}' does not exist."
            )

        del self._workspaces[workspace_id]

    def exists(
        self,
        workspace_id: UUID,
    ) -> bool:
        """
        Determine whether a workspace exists.

        Parameters
        ----------
        workspace_id
            Unique identifier of the workspace.

        Returns
        -------
        bool
            True if the workspace exists, otherwise False.
        """

        return workspace_id in self._workspaces

    def list_workspaces(
        self,
    ) -> list[ResearchSession]:
        """
        Retrieve all stored research workspaces.

        Returns
        -------
        list[ResearchSession]
            Collection of stored research sessions.

        Notes
        -----
        Returns a shallow copy of the internal collection to prevent
        callers from modifying repository storage directly.
        """

        return list(
            self._workspaces.values()
        )

    @property
    def workspace_count(
        self,
    ) -> int:
        """
        Return the number of stored research workspaces.

        Returns
        -------
        int
            Number of persisted workspaces.
        """

        return len(self._workspaces)

    def workspace_state_counts(self) -> dict[str, int]:
        """Count workspaces per FSM state, zero-filling every state.

        In-memory implementation: one linear pass over
        the dict of stored workspaces, incrementing the
        counter for each session's state.
        """
        counts = {state.value: 0 for state in WorkspaceState}
        for session in self._workspaces.values():
            counts[session.state.value] += 1
        return counts

    def clear(
        self,
    ) -> None:
        """
        Remove all stored research workspaces.

        Notes
        -----
        This method is intended primarily for testing and local
        development environments.
        """

        self._workspaces.clear()