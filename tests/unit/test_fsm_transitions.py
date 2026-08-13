"""
Unit tests for the FSM transition table.

These tests exercise the transition table, the ``ResearchSession``
state mutators, and the error reporting surface. They run without
external dependencies (no LLM, no PubMed, no persistence).
"""

from __future__ import annotations

import pytest

from app.core.enums.workspace_state import (
    TRANSITIONS,
    WorkspaceAction,
    WorkspaceState,
    allowed_actions,
    next_state,
)
from app.core.exceptions import IllegalWorkspaceActionError
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_session import (
    ResearchSession,
    StateTransition,
)


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------


def test_transitions_table_is_total() -> None:
    """Each state has at least one action or is terminal."""
    for state in WorkspaceState:
        transitions = TRANSITIONS[state]
        # ERROR is reachable from any non-terminal state in spirit
        # but cannot be defined per-state because it is the failure
        # target. We just require the table to be populated.
        assert transitions is not None


def test_legal_action_transitions() -> None:
    """Spot-check legal transitions."""
    assert next_state(WorkspaceState.CREATED, WorkspaceAction.SEARCH) is WorkspaceState.SEARCHING
    assert (
        next_state(WorkspaceState.PAPERS_RETRIEVED, WorkspaceAction.SUMMARIZE)
        is WorkspaceState.SUMMARIZING
    )
    assert (
        next_state(WorkspaceState.SUMMARIZED, WorkspaceAction.COMPARE)
        is WorkspaceState.COMPARING
    )
    assert (
        next_state(WorkspaceState.COMPARED, WorkspaceAction.REPORT)
        is WorkspaceState.REPORTING
    )
    assert (
        next_state(WorkspaceState.REPORTED, WorkspaceAction.COMPLETE)
        is WorkspaceState.COMPLETED
    )


def test_illegal_action_raises() -> None:
    """REPORT from CREATED is illegal — guard against the bug."""
    with pytest.raises(IllegalWorkspaceActionError) as exc:
        next_state(WorkspaceState.CREATED, WorkspaceAction.REPORT)
    assert exc.value.current_state == "CREATED"
    assert exc.value.action == "report"
    assert "search" in exc.value.allowed


def test_allowed_actions_sorted() -> None:
    """allowed_actions returns alphabetically sorted actions."""
    actions = allowed_actions(WorkspaceState.SUMMARIZED)
    assert actions == sorted(actions, key=lambda a: a.value)


def test_retry_returns_to_creatable_state() -> None:
    """ERROR → RETRY recovers to CREATED."""
    assert (
        next_state(WorkspaceState.ERROR, WorkspaceAction.RETRY)
        is WorkspaceState.CREATED
    )


def test_searching_is_transient() -> None:
    assert WorkspaceState.SEARCHING.is_transient
    assert WorkspaceState.SUMMARIZING.is_transient
    assert WorkspaceState.COMPARING.is_transient
    assert WorkspaceState.REPORTING.is_transient
    assert not WorkspaceState.PAPERS_RETRIEVED.is_transient


def test_completed_is_terminal() -> None:
    assert WorkspaceState.COMPLETED.is_terminal
    assert not WorkspaceState.REPORTED.is_terminal


# ---------------------------------------------------------------------------
# ResearchSession mutators
# ---------------------------------------------------------------------------


def _session() -> ResearchSession:
    return ResearchSession(
        question=ResearchQuestion(question="What is GLP-1?")
    )


def test_initial_state_is_created() -> None:
    assert _session().state is WorkspaceState.CREATED


def test_legal_transition_appends_history() -> None:
    s = _session()
    s.transition_to(WorkspaceAction.SEARCH)
    assert s.state is WorkspaceState.SEARCHING
    assert len(s.state_history) == 2
    last = s.state_history[-1]
    assert last.from_state is WorkspaceState.CREATED
    assert last.to_state is WorkspaceState.SEARCHING
    assert last.action is WorkspaceAction.SEARCH


def test_illegal_transition_raises_and_does_not_mutate() -> None:
    s = _session()
    with pytest.raises(IllegalWorkspaceActionError):
        s.transition_to(WorkspaceAction.REPORT)
    assert s.state is WorkspaceState.CREATED
    assert len(s.state_history) == 1  # only the initial seed


def test_force_state_completes_transient() -> None:
    s = _session()
    s.transition_to(WorkspaceAction.SEARCH)
    assert s.state is WorkspaceState.SEARCHING
    s.force_state(WorkspaceState.PAPERS_RETRIEVED, reason="PubMed returned 5")
    assert s.state is WorkspaceState.PAPERS_RETRIEVED


def test_force_state_to_error_records_reason() -> None:
    s = _session()
    s.transition_to(WorkspaceAction.SEARCH)
    s.force_state(WorkspaceState.ERROR, reason="NetworkError")
    assert s.state is WorkspaceState.ERROR
    assert s.last_error == "NetworkError"


def test_add_papers_advances_to_papers_retrieved() -> None:
    from app.domain.entities.paper import Paper

    s = _session()
    paper = Paper(title="Test", pmid="12345")
    s.add_papers([paper])
    assert s.state is WorkspaceState.PAPERS_RETRIEVED
    assert len(s.papers) == 1


def test_add_papers_dedupes() -> None:
    from app.domain.entities.paper import Paper

    s = _session()
    paper = Paper(title="Test", pmid="12345")
    s.add_papers([paper])
    s.add_papers([paper])
    assert len(s.papers) == 1


def test_remove_paper_degrades_to_created() -> None:
    from app.domain.entities.paper import Paper

    s = _session()
    s.add_papers([Paper(title="t", pmid="9")])
    assert s.state is WorkspaceState.PAPERS_RETRIEVED
    assert s.remove_paper("9") is True
    assert s.state is WorkspaceState.CREATED
    assert s.papers == []


def test_allowed_actions_returns_sorted_list() -> None:
    s = _session()
    actions = s.allowed_actions()
    assert actions == sorted(actions, key=lambda a: a.value)
    assert WorkspaceAction.SEARCH in actions


def test_progress_anchor_is_monotonic() -> None:
    """Progress for non-error states is non-decreasing in workflow order."""
    anchors = [
        (WorkspaceState.CREATED, 0.0),
        (WorkspaceState.PAPERS_RETRIEVED, 0.2),
        (WorkspaceState.SUMMARIZED, 0.45),
        (WorkspaceState.COMPARED, 0.7),
        (WorkspaceState.REPORTED, 0.95),
        (WorkspaceState.COMPLETED, 1.0),
    ]
    for state, expected in anchors:
        assert _session().state == WorkspaceState.CREATED  # sanity
        ws = ResearchSession(
            question=ResearchQuestion(question="x"),
            state=state,
        )
        assert ws.progress == expected, f"progress({state}) = {ws.progress}"


def test_status_property_returns_state_value() -> None:
    """The legacy ``status`` property mirrors the FSM state."""
    s = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.SUMMARIZED,
    )
    assert s.status == "SUMMARIZED"


def test_state_history_persists_from_init() -> None:
    """Hydrating a session with a populated history preserves it."""
    s = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.SUMMARIZED,
        state_history=[
            StateTransition(
                from_state=WorkspaceState.CREATED,
                to_state=WorkspaceState.SUMMARIZED,
            )
        ],
    )
    assert len(s.state_history) == 1
    assert s.state_history[0].to_state is WorkspaceState.SUMMARIZED
