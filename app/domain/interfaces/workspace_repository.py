"""
workspace_repository.py

Interface defining the persistence contract for Research Workspaces.

Purpose
-------
This module declares the abstract repository responsible for managing the
persistence lifecycle of :class:`ResearchSession` entities.

The repository interface belongs to the application's core architecture
and defines the operations required to store and retrieve research
workspaces without exposing any infrastructure details.

Concrete implementations belong to the Infrastructure layer and may use
different persistence mechanisms while respecting this contract.

Responsibilities
----------------
Implementations of this interface must support:

- Creating new research workspaces.
- Retrieving existing research workspaces.
- Persisting workspace modifications.
- Removing research workspaces.
- Checking workspace existence.
- Listing available research workspaces.

Possible implementations include:

- In-memory repositories.
- SQLite repositories.
- PostgreSQL repositories.
- MongoDB repositories.
- Redis-backed repositories.
- Cloud persistence solutions.

Architecture
------------

          Application Layer
                 │
                 ▼
       WorkspaceRepository
                 │
                 ▼
       Infrastructure Layer
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
    InMemory  SQL     NoSQL

The application depends exclusively on this abstraction.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.research_session import ResearchSession


class WorkspaceRepository(ABC):
    """
    Abstract repository contract for ResearchSession persistence.

    A WorkspaceRepository defines the operations required by application
    use cases to manage the lifecycle of research workspaces.

    Implementations are responsible for persistence details while exposing
    a consistent interface to the application layer.
    """

    @abstractmethod
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
        """

        raise NotImplementedError

    @abstractmethod
    def get(
        self,
        workspace_id: UUID,
    ) -> ResearchSession:
        """
        Retrieve a research workspace by identifier.

        Parameters
        ----------
        workspace_id
            Unique UUID identifying the research session.

        Returns
        -------
        ResearchSession
            Retrieved research session.

        Raises
        ------
        ValueError
            If no workspace exists with the supplied identifier.
        """

        raise NotImplementedError

    @abstractmethod
    def update(
        self,
        workspace: ResearchSession,
    ) -> ResearchSession:
        """
        Persist modifications made to an existing workspace.

        Parameters
        ----------
        workspace
            Research session containing updated state.

        Returns
        -------
        ResearchSession
            Updated persisted research session.
        """

        raise NotImplementedError

    @abstractmethod
    def delete(
        self,
        workspace_id: UUID,
    ) -> None:
        """
        Remove a research workspace.

        Parameters
        ----------
        workspace_id
            Unique UUID identifying the workspace to remove.

        Raises
        ------
        ValueError
            If no workspace exists with the supplied identifier.
        """

        raise NotImplementedError

    @abstractmethod
    def exists(
        self,
        workspace_id: UUID,
    ) -> bool:
        """
        Determine whether a research workspace exists.

        Parameters
        ----------
        workspace_id
            Unique UUID identifying the workspace.

        Returns
        -------
        bool
            True if the workspace exists, otherwise False.
        """

        raise NotImplementedError

    @abstractmethod
    def list_workspaces(
        self,
    ) -> list[ResearchSession]:
        """
        Retrieve all stored research workspaces.

        Returns
        -------
        list[ResearchSession]
            Collection of available research sessions.
        """

        raise NotImplementedError