"""
workspace_response.py

API response schema representing a complete BioResearch AI Research
Workspace.

The WorkspaceResponse is the primary object exchanged between the backend
API and client applications. It provides a snapshot of an entire
biomedical investigation, including the research question, retrieved
literature, generated summaries, reports, and execution metadata.

Unlike domain entities, response schemas are optimized for serialization
and client consumption. They define the external contract of the REST API
without exposing internal implementation details.

Architecture
------------

            ResearchSession
                    │
                    ▼
         WorkspaceResponse
                    │
                    ▼
              HTTP Response
                    │
                    ▼
         Web UI / Desktop / Mobile

The WorkspaceResponse is intentionally designed to evolve as BioResearch
AI gains new capabilities, allowing additional information to be exposed
without modifying the underlying domain model.

Future versions may include:

- Agent execution history
- LangGraph execution traces
- MCP tool calls
- Biological database queries
- User annotations
- Saved prompts
- Experimental plans
- Evidence graphs
- Uploaded documents

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from app.api.schemas.search_response import PaperResponse

if TYPE_CHECKING:
    from app.domain.entities.research_session import ResearchSession


class WorkspaceResponse(BaseModel):
    """
    Serialized representation of a biomedical Research Workspace.

    A workspace represents the complete state of a scientific
    investigation.

    Attributes
    ----------
    workspace_id : str
        Unique identifier of the workspace.

    question : str
        Original biomedical research question.

    papers : list[PaperResponse]
        Scientific publications currently loaded into the workspace.

    total_papers : int
        Number of retrieved publications.

    summary : str | None
        Current evidence synthesis.

    report_available : bool
        Indicates whether a final research report has been generated.

    created_at : datetime
        Workspace creation timestamp (UTC).

    updated_at : datetime
        Last modification timestamp (UTC).

    status : str
        Current workspace status.

    Notes
    -----
    The response intentionally contains only data required by the
    presentation layer. Internal workflow objects remain hidden inside
    the application and domain layers.
    """

    model_config = ConfigDict(from_attributes=True)

    workspace_id: str = Field(
        description="Unique identifier of the Research Workspace."
    )

    question: str = Field(
        description="Original biomedical research question."
    )

    status: str = Field(
        description="Current workspace state.",
        examples=[
            "Created",
            "Searching",
            "Summarizing",
            "Completed"
        ]
    )

    papers: list[PaperResponse] = Field(
        default_factory=list,
        description="Scientific publications loaded into the workspace."
    )

    total_papers: int = Field(
        ge=0,
        description="Total number of retrieved publications."
    )

    summary: str | None = Field(
        default=None,
        description="Current evidence synthesis."
    )

    report_available: bool = Field(
        default=False,
        description="Whether a final report has been generated."
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Workspace creation timestamp."
    )

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last workspace update timestamp."
    )

    @property
    def has_papers(self) -> bool:
        """
        Determine whether the workspace contains scientific papers.

        Returns
        -------
        bool
            True if one or more publications have been retrieved.
        """
        return self.total_papers > 0

    @property
    def has_summary(self) -> bool:
        """
        Determine whether an evidence summary exists.

        Returns
        -------
        bool
            True if a summary has been generated.
        """
        return bool(self.summary)

    @classmethod
    def empty(
        cls,
        workspace_id: str,
        question: str,
    ) -> "WorkspaceResponse":
        """
        Create an empty Research Workspace.

        Parameters
        ----------
        workspace_id : str
            Workspace identifier.

        question : str
            Initial research question.

        Returns
        -------
        WorkspaceResponse
            Newly initialized workspace.
        """
        return cls(
            workspace_id=workspace_id,
            question=question,
            status="Created",
            papers=[],
            total_papers=0,
        )

    @classmethod
    def from_domain(cls, session: "ResearchSession") -> "WorkspaceResponse":
        """
        Build a WorkspaceResponse from a domain ResearchSession object.

        This method bridges the domain layer and the presentation layer by
        extracting and transforming data from the domain aggregate into the
        API response schema.

        It handles:
        - Extracting the workspace ID (either `id` or `workspace_id`).
        - Extracting the question text from a potential `ResearchQuestion` object.
        - Computing `total_papers` from the `papers` list.
        - Normalizing the status (handling Enums).
        - Detecting report availability.
        - Providing fallback timestamps if not present.

        Parameters
        ----------
        session : ResearchSession
            The domain workspace aggregate.

        Returns
        -------
        WorkspaceResponse
            Serialized response ready for HTTP transmission.

        Raises
        ------
        AttributeError
            If required attributes are missing from the session object.
        """
        # Workspace ID: try `id` then `workspace_id`
        workspace_id = getattr(session, "id", None)
        if workspace_id is None:
            workspace_id = getattr(session, "workspace_id", None)
        if workspace_id is None:
            raise AttributeError("ResearchSession has neither 'id' nor 'workspace_id'.")

        # Question: extract string from ResearchQuestion if needed
        question_obj = getattr(session, "question", None)
        if question_obj is None:
            raise AttributeError("ResearchSession missing 'question'.")
        if hasattr(question_obj, "question"):
            question_text = question_obj.question
        else:
            question_text = str(question_obj)

        # Papers
        papers = getattr(session, "papers", [])
        total_papers = len(papers)
        paper_responses = [PaperResponse.from_domain(p) for p in papers]

        # Status: handle Enum or string
        status = getattr(session, "status", "Created")
        if hasattr(status, "value"):
            status = status.value
        if not isinstance(status, str):
            status = str(status)

        # Summary
        summary = getattr(session, "summary", None)

        # Report availability
        report = getattr(session, "report", None)
        report_available = report is not None

        # Timestamps
        created_at = getattr(session, "created_at", None)
        if created_at is None:
            created_at = datetime.now(UTC)
        updated_at = getattr(session, "updated_at", None)
        if updated_at is None:
            updated_at = datetime.now(UTC)

        return cls(
            workspace_id=str(workspace_id),
            question=question_text,
            status=status,
            papers=paper_responses,
            total_papers=total_papers,
            summary=summary,
            report_available=report_available,
            created_at=created_at,
            updated_at=updated_at,
        )