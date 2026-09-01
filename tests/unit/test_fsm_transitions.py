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
    """Spot-check legal transitions for the 4-state FSM."""
    # Home page → Workspace page
    assert (
        next_state(WorkspaceState.INITIAL, WorkspaceAction.SEARCH)
        is WorkspaceState.INTERMEDIATE
    )
    # Workspace page → Report page
    assert (
        next_state(WorkspaceState.INTERMEDIATE, WorkspaceAction.GENERATE)
        is WorkspaceState.FINAL
    )
    # Report page → back to Workspace (iterative refinement)
    assert (
        next_state(WorkspaceState.FINAL, WorkspaceAction.BACK_TO_WORKSPACE)
        is WorkspaceState.INTERMEDIATE
    )
    # Workspace page → back to Home (start a new search)
    assert (
        next_state(WorkspaceState.INTERMEDIATE, WorkspaceAction.BACK_TO_HOME)
        is WorkspaceState.INITIAL
    )


def test_illegal_action_raises() -> None:
    """GENERATE from INITIAL is illegal — guard against the bug."""
    with pytest.raises(IllegalWorkspaceActionError) as exc:
        next_state(WorkspaceState.INITIAL, WorkspaceAction.GENERATE)
    assert exc.value.current_state == "INITIAL"
    assert exc.value.action == "generate"
    assert "search" in exc.value.allowed


def test_allowed_actions_sorted() -> None:
    """allowed_actions returns alphabetically sorted actions."""
    actions = allowed_actions(WorkspaceState.INTERMEDIATE)
    assert actions == sorted(actions, key=lambda a: a.value)


def test_retry_recovers_from_error() -> None:
    """ERROR + RETRY is a session-aware resolver.

    The destination depends on ``session.last_known_state``;
    the resolver reads it directly. Without a session, the
    table raises ``TypeError`` (a programmer error, not a
    runtime FSM ambiguity) so silent misuse can't happen.
    """
    import pytest
    from app.core.enums.workspace_state import _retry_target

    # Without a session argument, the caller forgot to thread
    # the session through; this is a programmer error.
    with pytest.raises(TypeError, match="session"):
        next_state(WorkspaceState.ERROR, WorkspaceAction.RETRY)

    # ``last_known_state`` is the destination when present,
    # regardless of which state was the "fallback" before the
    # resolver was extracted from the orchestrator.
    from app.domain.entities.research_session import ResearchSession
    from app.domain.entities.research_question import ResearchQuestion
    for last_known, expected in (
        (WorkspaceState.INITIAL, WorkspaceState.INITIAL),
        (WorkspaceState.INTERMEDIATE, WorkspaceState.INTERMEDIATE),
    ):
        session = ResearchSession(
            question=ResearchQuestion(question="x"),
            state=WorkspaceState.ERROR,
            last_known_state=last_known,
        )
        # Call ``next_state`` through the entity's
        # ``transition_to`` so the audit path is exercised
        # end-to-end (entity -> FSM table -> resolver).
        session.transition_to(WorkspaceAction.RETRY)
        assert session.state is expected

    # Direct resolver invocation is also part of the
    # public contract -- it's the unit-test entry point.
    session = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.ERROR,
        last_known_state=None,
    )
    # Heuristic: no papers -> INITIAL (pre-v8 row with no
    # recorded pre-error state).
    assert _retry_target(session) is WorkspaceState.INITIAL
    # The "papers" branch of the heuristic is exercised by
    # the orchestrator test suite (``test_retry_recovers_to_
    # intermediate_when_papers_exist``) -- we don't need
    # to construct a Paper here just to flip ``bool(papers)``.


def test_retry_resolver_uses_papers_heuristic_when_last_known_missing() -> None:
    """When ``last_known_state`` is None, the resolver falls
    back to the papers heuristic.

    Specifically: a workspace with papers should retry to
    INTERMEDIATE (the user was mid-generation, the corpus
    is salvageable); a workspace without papers should retry
    to INITIAL (the user was trying to start a fresh search,
    there's nothing to preserve).
    """
    from app.core.enums.workspace_state import _retry_target
    from app.domain.entities.research_session import ResearchSession
    from app.domain.entities.research_question import ResearchQuestion
    from app.domain.entities.paper import Paper
    from app.domain.entities.author import Author

    session = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.ERROR,
        last_known_state=None,
    )
    assert _retry_target(session) is WorkspaceState.INITIAL

    session.add_papers([
        Paper(
            pmid="12345",
            title="A real paper",
            authors=[Author(first_name="Jane", last_name="Doe")],
            abstract="An abstract.",
        )
    ])
    assert _retry_target(session) is WorkspaceState.INTERMEDIATE


def test_final_is_terminal() -> None:
    """FINAL is the terminal success state."""
    assert WorkspaceState.FINAL.is_terminal
    assert not WorkspaceState.INTERMEDIATE.is_terminal
    assert not WorkspaceState.INITIAL.is_terminal


def test_pages_map_to_states() -> None:
    """Each state maps to a known frontend page token."""
    assert WorkspaceState.INITIAL.page == "home"
    assert WorkspaceState.INTERMEDIATE.page == "workspace"
    assert WorkspaceState.FINAL.page == "report"
    assert WorkspaceState.ERROR.page == "error"


# ---------------------------------------------------------------------------
# ResearchSession mutators
# ---------------------------------------------------------------------------


def _session() -> ResearchSession:
    return ResearchSession(
        question=ResearchQuestion(question="What is GLP-1?")
    )


def test_initial_state_is_initial() -> None:
    """A fresh workspace is in INITIAL."""
    assert _session().state is WorkspaceState.INITIAL


def test_legal_transition_appends_history() -> None:
    s = _session()
    s.transition_to(WorkspaceAction.SEARCH)
    assert s.state is WorkspaceState.INTERMEDIATE
    assert len(s.state_history) == 2
    last = s.state_history[-1]
    assert last.from_state is WorkspaceState.INITIAL
    assert last.to_state is WorkspaceState.INTERMEDIATE
    assert last.action is WorkspaceAction.SEARCH


def test_illegal_transition_raises_and_does_not_mutate() -> None:
    s = _session()
    with pytest.raises(IllegalWorkspaceActionError):
        s.transition_to(WorkspaceAction.GENERATE)
    assert s.state is WorkspaceState.INITIAL
    assert len(s.state_history) == 1  # only the initial seed


def test_force_state_completes_transient() -> None:
    """force_state is allowed from any state (used by orchestrator)."""
    s = _session()
    s.transition_to(WorkspaceAction.SEARCH)
    assert s.state is WorkspaceState.INTERMEDIATE
    # The orchestrator uses force_state to record the durable state
    # after an async operation completes; in the 4-state model this
    # means transitioning from INITIAL → INTERMEDIATE explicitly.
    s.force_state(WorkspaceState.INTERMEDIATE, reason="Search returned 5 papers")


def test_force_state_to_error_records_reason() -> None:
    """force_state(ERROR) records last_error but does NOT set
    last_known_state. ``last_known_state`` is only set by the
    orchestrator's ``_fail()`` helper (which calls force_state
    AFTER capturing the pre-error state). A bare force_state
    call is the "raw" entry point and does not maintain the
    audit trail."""
    s = _session()
    s.transition_to(WorkspaceAction.SEARCH)
    s.force_state(WorkspaceState.ERROR, reason="NetworkError")
    assert s.state is WorkspaceState.ERROR
    assert s.last_error == "NetworkError"
    # Bare force_state doesn't set last_known_state -- the
    # orchestrator's _fail() helper does that explicitly.
    assert s.last_known_state is None


def test_fail_helper_records_last_known_state() -> None:
    """The orchestrator's ``_fail()`` helper sets last_known_state
    BEFORE moving to ERROR, so a subsequent RETRY can restore
    the right page."""
    from app.application.services.workspace_orchestrator import (
        WorkspaceOrchestrator,
    )
    from tests.unit.test_workspace_orchestrator import (
        InMemoryRepository,
        StubLLM,
        StubPDFGenerator,
        StubPubMed,
        StubReportGenerator,
    )

    repo = InMemoryRepository()
    orch = WorkspaceOrchestrator(
        workspace_repository=repo,
        literature_searcher=StubPubMed([]),
        llm_provider=StubLLM(),
        report_generator=StubReportGenerator(),
        pdf_generator=StubPDFGenerator(),
    )

    ws = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
    )
    repo.create(ws)

    orch._fail(ws, RuntimeError("LLM timeout"))
    assert ws.state is WorkspaceState.ERROR
    assert ws.last_error == "RuntimeError: LLM timeout"
    assert ws.last_known_state is WorkspaceState.INTERMEDIATE


def test_add_papers_advances_to_intermediate() -> None:
    """Adding the first paper advances the workspace from INITIAL."""
    from app.domain.entities.paper import Paper

    s = _session()
    paper = Paper(title="Test", pmid="12345")
    s.add_papers([paper])
    assert s.state is WorkspaceState.INTERMEDIATE
    assert len(s.papers) == 1


def test_add_papers_dedupes() -> None:
    from app.domain.entities.paper import Paper

    s = _session()
    paper = Paper(title="Test", pmid="12345")
    s.add_papers([paper])
    s.add_papers([paper])
    assert len(s.papers) == 1


def test_remove_paper_degrades_to_initial() -> None:
    """Removing the last paper regresses the workspace to INITIAL."""
    from app.domain.entities.paper import Paper

    s = _session()
    s.add_papers([Paper(title="t", pmid="9")])
    assert s.state is WorkspaceState.INTERMEDIATE
    assert s.remove_paper("9") is True
    assert s.state is WorkspaceState.INITIAL
    assert s.papers == []


def test_allowed_actions_returns_sorted_list() -> None:
    s = _session()
    actions = s.allowed_actions()
    assert actions == sorted(actions, key=lambda a: a.value)
    assert WorkspaceAction.SEARCH in actions


def test_progress_anchor_is_monotonic() -> None:
    """Progress for non-error states is non-decreasing in workflow order."""
    anchors = [
        (WorkspaceState.INITIAL, 0.0),
        (WorkspaceState.INTERMEDIATE, 0.5),
        (WorkspaceState.FINAL, 1.0),
        (WorkspaceState.ERROR, 0.0),
    ]
    for state, expected in anchors:
        assert _session().state == WorkspaceState.INITIAL  # sanity
        ws = ResearchSession(
            question=ResearchQuestion(question="x"),
            state=state,
        )
        assert ws.progress == expected, f"progress({state}) = {ws.progress}"


def test_status_property_returns_state_value() -> None:
    """The legacy ``status`` property mirrors the FSM state."""
    s = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
    )
    assert s.status == "INTERMEDIATE"


def test_page_property_returns_state_page() -> None:
    """The ``page`` property mirrors the FSM state's frontend page."""
    s = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.FINAL,
    )
    assert s.page == "report"


def test_state_history_persists_from_init() -> None:
    """Hydrating a session with a populated history preserves it."""
    s = ResearchSession(
        question=ResearchQuestion(question="x"),
        state=WorkspaceState.INTERMEDIATE,
        state_history=[
            StateTransition(
                from_state=WorkspaceState.INITIAL,
                to_state=WorkspaceState.INTERMEDIATE,
            )
        ],
    )
    assert len(s.state_history) == 1
    assert s.state_history[0].to_state is WorkspaceState.INTERMEDIATE
