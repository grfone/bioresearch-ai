"""
workspace_status_response.py

API response schema exposing the lifecycle state of a Research
Workspace.

The schema is the public contract for clients that want to render
the workspace as a lab-bench UI: it surfaces the current state, the
legal next actions, the progress indicator, and the full history of
state transitions.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StateTransitionResponse(BaseModel):
    """
    A single entry in the workspace's state history.

    Attributes
    ----------
    from_state : str
        State before the transition.

    to_state : str
        State after the transition.

    action : str | None
        Action that triggered the transition (or ``None`` for the
        initial record / forced transitions).

    at : datetime
        Timestamp (UTC) of the transition.

    reason : str | None
        Optional human-readable explanation.
    """

    from_state: str
    to_state: str
    action: str | None = None
    at: datetime
    reason: str | None = None


class WorkspaceStatusResponse(BaseModel):
    """
    FSM-aware view of a Research Workspace.

    Returned by the ``GET /workspaces/{id}/transitions`` endpoint and
    embedded in the workspace response so the frontend can render
    the lab-bench progress strip without an extra round-trip.

    Attributes
    ----------
    workspace_id : str
        Unique identifier of the workspace.

    state : str
        Current FSM state (e.g. ``"PAPERS_RETRIEVED"``).

    progress : float
        Coarse progress in [0.0, 1.0].

    allowed_actions : list[str]
        Legal next actions, sorted alphabetically.

    state_history : list[StateTransitionResponse]
        Ordered history of state transitions.

    last_error : str | None
        Last error message if the workspace is in ERROR.

    page : str
        Frontend page token for this state (``"home"``,
        ``"workspace"``, ``"report"``, ``"error"``).

    is_terminal : bool
        Whether the state is a terminal success state.
    """

    model_config = ConfigDict(from_attributes=True)

    workspace_id: str = Field(
        description="Unique identifier of the Research Workspace.",
    )

    state: str = Field(
        description="Current FSM state of the workspace.",
    )

    progress: float = Field(
        ge=0.0,
        le=1.0,
        description="Coarse progress indicator in [0.0, 1.0].",
    )

    allowed_actions: list[str] = Field(
        default_factory=list,
        description="Legal next actions, sorted alphabetically.",
    )

    state_history: list[StateTransitionResponse] = Field(
        default_factory=list,
        description="Ordered history of state transitions.",
    )

    last_error: str | None = Field(
        default=None,
        description="Last error message if the workspace is in ERROR.",
    )

    page: str = Field(
        default="home",
        description=(
            "Frontend page token. One of home, workspace, report, error."
        ),
    )

    is_terminal: bool = Field(
        default=False,
        description="Whether the state is a terminal success state.",
    )

    @classmethod
    def from_session(cls, session: Any) -> "WorkspaceStatusResponse":
        """Build the response from a :class:`ResearchSession`."""
        from app.domain.entities.research_session import ResearchSession

        if not isinstance(session, ResearchSession):
            raise TypeError(
                "WorkspaceStatusResponse.from_session requires a "
                "ResearchSession instance."
            )

        return cls(
            workspace_id=str(session.id),
            state=session.state.value,
            progress=session.progress,
            allowed_actions=[a.value for a in session.allowed_actions()],
            state_history=[
                StateTransitionResponse(
                    from_state=t.from_state.value,
                    to_state=t.to_state.value,
                    action=t.action.value if t.action is not None else None,
                    at=t.at,
                    reason=t.reason,
                )
                for t in session.state_history
            ],
            last_error=session.last_error,
            page=session.state.page,
            is_terminal=session.state.is_terminal,
        )
