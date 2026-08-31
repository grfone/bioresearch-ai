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

    published_report_available : bool
        Indicates whether a PDF has been rendered for download
        by the PUBLISH action. Independent of ``report_available``:
        a workspace may have a generated report but not yet a PDF
        (the user can publish at any time after REPORT), and
        conversely a workspace published once will keep its PDF
        even if the underlying report is regenerated.

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

    state: str = Field(
        description="Current FSM state of the workspace.",
        examples=[
            "CREATED",
            "PAPERS_RETRIEVED",
            "SUMMARIZED",
            "REPORTED",
            "COMPLETED",
        ],
    )

    status: str = Field(
        description=(
            "Backwards-compatible status string. Always matches the "
            "FSM state value. New clients should prefer 'state'."
        ),
        examples=["CREATED", "SUMMARIZED", "REPORTED"],
    )

    allowed_actions: list[str] = Field(
        default_factory=list,
        description="Legal next actions, sorted alphabetically.",
    )

    progress: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Coarse progress indicator in [0.0, 1.0].",
    )

    last_error: str | None = Field(
        default=None,
        description="Last error message if the workspace is in ERROR.",
    )

    last_error_at: datetime | None = Field(
        default=None,
        description=(
            "UTC timestamp of when the workspace entered ERROR and "
            "``last_error`` was set. ``None`` when ``last_error`` is "
            "``None``. Pairs with ``last_error`` so the UI can show "
            "\"X seconds ago\" / \"at HH:MM:SS\" for diagnostic clarity, "
            "especially after a container restart."
        ),
    )

    papers: list[PaperResponse] = Field(
        default_factory=list,
        description="Scientific publications loaded into the workspace."
    )

    total_papers: int = Field(
        ge=0,
        description="Total number of retrieved publications."
    )

    paper_sources: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per-paper source attribution — maps paper "
            "identifier (PMID, DOI, or URL) to the "
            "SearchSource enum value that returned it "
            "(\"pubmed\" / \"openalex\" / \"europe_pmc\" / "
            "\"biorxiv\"). Empty for legacy "
            "PubMed-only workspaces."
        ),
    )

    summary: str | None = Field(
        default=None,
        description="Current evidence synthesis."
    )

    report_available: bool = Field(
        default=False,
        description="Whether a final report has been generated."
    )

    published_report_available: bool = Field(
        default=False,
        description=(
            "Whether a PDF has been rendered and persisted via the "
            "PUBLISH action. Independent of ``report_available``: "
            "see the field docs on the pydantic class."
        ),
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
            paper_sources={},
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

        # Per-paper source attribution. Lives at the session
        # level so dedupe across sources doesn't lose the
        # original ``SearchResult.source``. Empty dict for
        # workspaces that pre-date the multi-source flow or
        # were created via legacy add_paper.
        paper_sources = getattr(session, "paper_sources", None)
        if not isinstance(paper_sources, dict):
            paper_sources = {}

        # State: prefer the FSM state if present, otherwise fall back
        # to the legacy ``status`` attribute.
        state = getattr(session, "state", None)
        if state is not None and hasattr(state, "value"):
            state_value = state.value
        else:
            legacy_status = getattr(session, "status", "CREATED")
            state_value = str(legacy_status).upper()

        # Status mirror (backwards-compatible).
        status_value = state_value

        # Allowed actions
        allowed_actions_method = getattr(session, "allowed_actions", None)
        if callable(allowed_actions_method):
            allowed_actions = [
                a.value for a in allowed_actions_method()
            ]
        else:
            allowed_actions = []

        # Progress
        progress = float(getattr(session, "progress", 0.0))

        # Summary
        summary = getattr(session, "summary", None)
        summary_text = None
        if summary is not None and hasattr(summary, "body"):
            summary_text = summary.body
        elif isinstance(summary, str):
            summary_text = summary

        # Report availability
        report = getattr(session, "report", None)
        report_available = report is not None

        # Published-report availability (PDF downloaded via the
        # GET /workspaces/{id}/published-report.pdf endpoint).
        # Set by the PUBLISH action. Independent of
        # ``report_available`` -- a workspace can be in REPORTED
        # state with a generated report but not yet published
        # (no PDF on the session), or vice versa after a
        # workspace has been COMPLETED via the legacy COMPLETE
        # action (report but no PDF). The UI uses this flag to
        # decide whether the "Download PDF" button is enabled.
        published_report = getattr(session, "published_report", None)
        published_report_available = published_report is not None

        # Last error
        last_error = getattr(session, "last_error", None)
        # ``last_error_at`` is set alongside ``last_error`` on
        # every state transition that enters ERROR -- so when
        # ``last_error`` is None, ``last_error_at`` is also
        # None. Reading via ``getattr`` keeps backward compat
        # with pre-v5 in-memory sessions (the field defaults
        # to None on the dataclass anyway).
        last_error_at = getattr(session, "last_error_at", None)

        # Timestamps
        created_at = getattr(session, "created_at", None)
        if created_at is None:
            created_at = datetime.now(UTC)
        updated_at = getattr(session, "updated_at", None)
        if updated_at is None:
            updated_at = datetime.now(UTC)

        return cls(
            paper_sources=paper_sources,
            workspace_id=str(workspace_id),
            question=question_text,
            state=state_value,
            status=status_value,
            allowed_actions=allowed_actions,
            progress=progress,
            last_error=last_error,
            last_error_at=last_error_at,
            papers=paper_responses,
            total_papers=total_papers,
            summary=summary_text,
            report_available=report_available,
            published_report_available=published_report_available,
            created_at=created_at,
            updated_at=updated_at,
        )