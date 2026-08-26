"""
workspace_state.py

Enumeration of the finite set of states a Research Workspace can be in.

Purpose
-------
A Research Workspace follows a deterministic lifecycle. The state
machine is the single source of truth for "what can happen next" in the
BioResearch AI platform. By centralising the states in one enum we
make transitions explicit, testable, and impossible to bypass by
accident.

States are organised into a tiered lifecycle that mirrors the actual
research workflow:

    CREATED
        │  search
        ▼
    SEARCHING   (transient)
        │
        ▼
    PAPERS_RETRIEVED
        │  summarize
        ▼
    SUMMARIZING  (transient)
        │
        ▼
    SUMMARIZED
        │  compare_evidence
        ▼
    COMPARING    (transient)
        │
        ▼
    COMPARED
        │  generate_report
        ▼
    REPORTING    (transient)
        │
        ▼
    REPORTED ─┬─► PUBLISHING (transient) ─► COMPLETED
             │                               ▲
             │                               │
             │  archive / mark done          │
             └─────────────────────────────►┘

ERROR is reachable from any non-terminal state and can be returned
from ERROR to the previous state on retry.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from enum import Enum


class WorkspaceState(str, Enum):
    """
    Discrete states of a Research Workspace.

    The string values are the canonical serialised form used in the
    SQLite database and the REST API. They are deliberately stable so
    that external clients can rely on them.

    Members
    -------
    CREATED
        Workspace exists, no literature retrieved yet.

    SEARCHING
        PubMed request is in flight. Transient.

    PAPERS_RETRIEVED
        At least one paper has been retrieved and stored. No summary yet.

    SUMMARIZING
        Evidence summarisation is in flight. Transient.

    SUMMARIZED
        Evidence summary exists. No cross-paper comparison yet.

    COMPARING
        Cross-paper evidence comparison is in flight. Transient.

    COMPARED
        Cross-paper comparison exists. No final report yet.

    REPORTING
        Final report generation is in flight. Transient.

    REPORTED
        Final report exists. Workspace still mutable (more papers
        can be added and intermediate steps can be re-run).

    PUBLISHING
        PDF export of the final report is in flight. Transient.
        Like ``REPORTING``, this is short-lived; the next durable
        state is ``COMPLETED`` once the PDF bytes have been
        generated and stored on the workspace.

    COMPLETED
        Terminal success state. The workspace is finished and ready for
        export / sharing.

    ERROR
        A non-terminal failure occurred. The runtime records the reason
        on the session and can be recovered to the previous state on
        retry.
    """

    CREATED = "CREATED"
    SEARCHING = "SEARCHING"
    PAPERS_RETRIEVED = "PAPERS_RETRIEVED"
    SUMMARIZING = "SUMMARIZING"
    SUMMARIZED = "SUMMARIZED"
    COMPARING = "COMPARING"
    COMPARED = "COMPARED"
    REPORTING = "REPORTING"
    REPORTED = "REPORTED"
    PUBLISHING = "PUBLISHING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"

    @property
    def is_transient(self) -> bool:
        """
        Whether the state represents an in-flight operation.

        Transient states (SEARCHING, SUMMARIZING, COMPARING, REPORTING)
        are not durable end states. They describe the system while an
        external request is running.

        Returns
        -------
        bool
            True if the state is transient.
        """
        return self in _TRANSIENT_STATES

    @property
    def is_terminal(self) -> bool:
        """
        Whether the state is a terminal success state.

        Returns
        -------
        bool
            True if the state is a terminal success state.
        """
        return self is WorkspaceState.COMPLETED


_TRANSIENT_STATES: frozenset[WorkspaceState] = frozenset(
    {
        WorkspaceState.SEARCHING,
        WorkspaceState.SUMMARIZING,
        WorkspaceState.COMPARING,
        WorkspaceState.REPORTING,
        WorkspaceState.PUBLISHING,
    }
)


# ---------------------------------------------------------------------------
# Workspace actions
# ---------------------------------------------------------------------------
#
# The FSM is action-driven. Each action maps to a single legal transition
# from each state. The transition table is the authoritative description
# of the workflow; the orchestrator consumes it directly.
# ---------------------------------------------------------------------------


class WorkspaceAction(str, Enum):
    """
    Discrete actions that can be requested on a Research Workspace.

    Each action is a verb that the orchestrator interprets as a request
    to advance the workspace state through the FSM.

    Members
    -------
    SEARCH
        Trigger a PubMed search for the workspace's question.

    SUMMARIZE
        Synthesise the current papers into an evidence summary.

    COMPARE
        Cross-paper evidence comparison (consensus, contradictions,
        gaps, future directions).

    REPORT
        Generate the final structured research report.

    COMPLETE
        Manually mark the workspace as finished.

    PUBLISH
        Render the workspace's final report as a PDF and mark
        the workspace as COMPLETED. This is the document-export
        action -- it produces a downloadable PDF and advances
        the FSM through PUBLISHING to COMPLETED. Legal only
        from REPORTED because the report must exist before we
        can render it. See ADR-009.

    RETRY
        Recover from an ERROR state by returning to the previous state.

    ADD_PAPER
        Add a paper directly (e.g. manual curation). Does not change
        state but is recorded as a legal action.

    REMOVE_PAPER
        Remove a paper from the workspace. Recorded as an action; if
        the last paper is removed the state degrades to PAPERS_RETRIEVED
        or CREATED based on the resulting count.
    """

    SEARCH = "search"
    SUMMARIZE = "summarize"
    COMPARE = "compare"
    REPORT = "report"
    COMPLETE = "complete"
    PUBLISH = "publish"
    RETRY = "retry"
    ADD_PAPER = "add_paper"
    REMOVE_PAPER = "remove_paper"


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------
#
# Keys are the current state, values are {action: next_state}. Actions
# absent from a state's mapping are illegal. The transition table is the
# authoritative FSM specification and is consumed by both the
# ResearchSession (pure domain) and the WorkspaceOrchestrator
# (application). Keeping it in one module makes the FSM auditable.
# ---------------------------------------------------------------------------

TRANSITIONS: dict[WorkspaceState, dict[WorkspaceAction, WorkspaceState]] = {
    WorkspaceState.CREATED: {
        WorkspaceAction.SEARCH: WorkspaceState.SEARCHING,
        WorkspaceAction.ADD_PAPER: WorkspaceState.PAPERS_RETRIEVED,
    },
    WorkspaceState.SEARCHING: {
        # SEARCHING is transient — the orchestrator flips to either
        # PAPERS_RETRIEVED (success) or ERROR (failure) once the
        # underlying request completes.
        WorkspaceAction.RETRY: WorkspaceState.CREATED,
    },
    WorkspaceState.PAPERS_RETRIEVED: {
        WorkspaceAction.SEARCH: WorkspaceState.SEARCHING,
        WorkspaceAction.SUMMARIZE: WorkspaceState.SUMMARIZING,
        # ``REPORT`` is allowed from ``PAPERS_RETRIEVED`` so a
        # user with papers but no summary can still get a
        # report with one click. The orchestrator
        # (``WorkspaceOrchestrator.report``) auto-runs the
        # summarisation step when ``session.summary is None``;
        # the state machine just records the user-visible
        # transition. See ADR-008 for the rationale.
        WorkspaceAction.REPORT: WorkspaceState.REPORTING,
        WorkspaceAction.REMOVE_PAPER: WorkspaceState.PAPERS_RETRIEVED,
        WorkspaceAction.ADD_PAPER: WorkspaceState.PAPERS_RETRIEVED,
    },
    WorkspaceState.SUMMARIZING: {
        WorkspaceAction.RETRY: WorkspaceState.PAPERS_RETRIEVED,
    },
    WorkspaceState.SUMMARIZED: {
        WorkspaceAction.SUMMARIZE: WorkspaceState.SUMMARIZING,
        WorkspaceAction.SEARCH: WorkspaceState.SEARCHING,
        WorkspaceAction.COMPARE: WorkspaceState.COMPARING,
        WorkspaceAction.REPORT: WorkspaceState.REPORTING,
        WorkspaceAction.ADD_PAPER: WorkspaceState.SUMMARIZED,
        WorkspaceAction.REMOVE_PAPER: WorkspaceState.SUMMARIZED,
    },
    WorkspaceState.COMPARING: {
        WorkspaceAction.RETRY: WorkspaceState.SUMMARIZED,
    },
    WorkspaceState.COMPARED: {
        WorkspaceAction.COMPARE: WorkspaceState.COMPARING,
        WorkspaceAction.SUMMARIZE: WorkspaceState.SUMMARIZING,
        WorkspaceAction.SEARCH: WorkspaceState.SEARCHING,
        WorkspaceAction.REPORT: WorkspaceState.REPORTING,
        WorkspaceAction.ADD_PAPER: WorkspaceState.COMPARED,
        WorkspaceAction.REMOVE_PAPER: WorkspaceState.COMPARED,
    },
    WorkspaceState.REPORTING: {
        WorkspaceAction.RETRY: WorkspaceState.COMPARED,
    },
    WorkspaceState.REPORTED: {
        WorkspaceAction.SUMMARIZE: WorkspaceState.SUMMARIZING,
        WorkspaceAction.COMPARE: WorkspaceState.COMPARING,
        WorkspaceAction.SEARCH: WorkspaceState.SEARCHING,
        WorkspaceAction.REPORT: WorkspaceState.REPORTING,
        WorkspaceAction.COMPLETE: WorkspaceState.COMPLETED,
        WorkspaceAction.PUBLISH: WorkspaceState.PUBLISHING,
        WorkspaceAction.ADD_PAPER: WorkspaceState.REPORTED,
        WorkspaceAction.REMOVE_PAPER: WorkspaceState.REPORTED,
    },
    WorkspaceState.PUBLISHING: {
        WorkspaceAction.RETRY: WorkspaceState.REPORTED,
    },
    WorkspaceState.COMPLETED: {
        WorkspaceAction.ADD_PAPER: WorkspaceState.REPORTED,
        WorkspaceAction.REMOVE_PAPER: WorkspaceState.REPORTED,
    },
    WorkspaceState.ERROR: {
        WorkspaceAction.RETRY: WorkspaceState.CREATED,
    },
}


def allowed_actions(state: WorkspaceState) -> list[WorkspaceAction]:
    """
    Return the list of actions that are legal from the given state.

    Parameters
    ----------
    state : WorkspaceState
        Current workspace state.

    Returns
    -------
    list[WorkspaceAction]
        Legal actions, in alphabetical order.
    """
    return sorted(TRANSITIONS.get(state, {}).keys(), key=lambda a: a.value)


def next_state(
    current: WorkspaceState,
    action: WorkspaceAction,
) -> WorkspaceState:
    """
    Compute the next state for a given action.

    Parameters
    ----------
    current : WorkspaceState
        Current workspace state.

    action : WorkspaceAction
        Action being requested.

    Returns
    -------
    WorkspaceState
        The new state after the action.

    Raises
    ------
    IllegalWorkspaceActionError
        If the action is not legal from the current state.
    """
    from app.core.exceptions import IllegalWorkspaceActionError

    transitions = TRANSITIONS.get(current, {})
    if action not in transitions:
        raise IllegalWorkspaceActionError(
            current_state=current.value,
            action=action.value,
            allowed=[a.value for a in allowed_actions(current)],
        )
    return transitions[action]
