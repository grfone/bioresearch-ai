"""
test_workspace_graph.py

Tests for the LangGraph implementation of the Research Workspace FSM.

These tests pin the two things the migration had to guarantee:

1. **Behaviour preservation.** The graph must accept exactly the
   actions the old imperative dispatcher accepted, reject exactly the
   ones it rejected (with an identical error payload), and produce
   the same audit trail. The behavioural snapshot
   (``scripts/fsm_behaviour_snapshot.py``) covers the end-to-end
   surface; these tests cover the graph's own contract.

2. **The graph is derived from the FSM table.** If the transition
   table changes, the graph must change with it — there must be no
   second, hand-maintained copy of the topology that can drift.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import pytest

from app.application.workflows.workspace_graph import (
    TRANSITIONING_ACTIONS,
    WORKSPACE_GRAPH,
    build_workspace_graph,
    run_transition,
)
from app.core.enums.workspace_state import (
    TRANSITIONS,
    WorkspaceAction,
    WorkspaceState,
    allowed_actions,
    next_state,
)
from app.core.exceptions import IllegalWorkspaceActionError
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_session import ResearchSession


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _paper(pmid: str = "1") -> Paper:
    return Paper(
        title=f"Paper {pmid}",
        pmid=pmid,
        authors=[],
        journal=None,
        year=2024,
        abstract="",
        doi=None,
        keywords=[],
        url=None,
    )


def _session(
    state: WorkspaceState = WorkspaceState.INITIAL,
    *,
    papers: list[Paper] | None = None,
    last_known_state: WorkspaceState | None = None,
) -> ResearchSession:
    """Build a session in a given state, with an optional corpus."""
    session = ResearchSession(
        question=ResearchQuestion(question="What is GLP-1?"),
        state=state,
        last_known_state=last_known_state,
    )
    if papers:
        session.add_papers(papers)
    return session


# ---------------------------------------------------------------------------
# The graph exists and is executable
# ---------------------------------------------------------------------------


def test_graph_is_compiled() -> None:
    """The workspace FSM is a real, compiled LangGraph."""
    assert WORKSPACE_GRAPH is not None
    assert hasattr(WORKSPACE_GRAPH, "invoke")
    assert hasattr(WORKSPACE_GRAPH, "get_graph")


def test_graph_can_be_rebuilt() -> None:
    """Building the graph twice yields two working graphs.

    The graph is built at import time from the transition table. A
    second build proves the construction is a pure function of the
    table and not of some import-time state.
    """
    other = build_workspace_graph()
    session = _session()
    assert run_transition(session, WorkspaceAction.SEARCH) is (
        WorkspaceState.INTERMEDIATE
    )

    second = _session()
    other.invoke({"session": second, "action": WorkspaceAction.SEARCH})
    assert second.state is WorkspaceState.INTERMEDIATE


def test_graph_renders_as_a_labelled_fsm() -> None:
    """The rendered graph labels its edges with the action names.

    The diagram is the FSM: each edge is labelled with the action
    that causes it and points at the state that action leads to.
    """
    diagram = WORKSPACE_GRAPH.get_graph().draw_mermaid()
    assert "search" in diagram
    assert "generate" in diagram
    assert "back_to_home" in diagram
    assert "back_to_workspace" in diagram
    assert "retry" in diagram


# ---------------------------------------------------------------------------
# The graph is derived from the transition table
# ---------------------------------------------------------------------------


def test_every_state_has_a_source_node() -> None:
    """Each workspace state can be the state the graph starts from."""
    diagram = WORKSPACE_GRAPH.get_graph().draw_mermaid()
    for state in WorkspaceState:
        assert f"state_{state.value.lower()}" in diagram


def test_transitioning_actions_cover_the_table() -> None:
    """Every action that moves the workspace is routed through the graph.

    ``add_paper`` and ``remove_paper`` are legal in the FSM table but
    do not move the workspace — the orchestrator records them
    without a transition. Everything else must be a graph edge.
    """
    table_actions = {
        action
        for actions in TRANSITIONS.values()
        for action in actions
    }
    non_transitioning = table_actions - TRANSITIONING_ACTIONS
    assert non_transitioning == {
        WorkspaceAction.ADD_PAPER,
        WorkspaceAction.REMOVE_PAPER,
    }
    assert TRANSITIONING_ACTIONS == {
        WorkspaceAction.SEARCH,
        WorkspaceAction.GENERATE,
        WorkspaceAction.RETRY,
        WorkspaceAction.BACK_TO_WORKSPACE,
        WorkspaceAction.BACK_TO_HOME,
    }


def test_graph_edges_match_the_transition_table() -> None:
    """The graph's topology is exactly the transition table's.

    This is the anti-drift test. It walks the table, computes where
    each action should lead, drives the graph there, and asserts the
    graph agrees. If someone edits ``TRANSITIONS`` without the graph
    following, this fails.
    """
    for state, actions in TRANSITIONS.items():
        for action, target in actions.items():
            if action not in TRANSITIONING_ACTIONS:
                continue

            session = _session(state)
            expected = next_state(state, action, session=session)

            actual = run_transition(session, action)
            assert actual is expected, (
                f"{state.value} + {action.value} -> {actual.value}, "
                f"expected {expected.value}"
            )


def test_graph_rejects_actions_the_table_rejects() -> None:
    """An action the table does not list is rejected by the graph."""
    for state in WorkspaceState:
        for action in WorkspaceAction:
            if action in TRANSITIONS[state]:
                continue
            session = _session(state)
            with pytest.raises(IllegalWorkspaceActionError):
                run_transition(session, action)


def test_error_payload_matches_the_imperative_dispatcher() -> None:
    """The 409 payload is byte-for-byte what the old dispatcher produced.

    The API layer turns ``IllegalWorkspaceActionError`` into a 409
    Conflict. The wire format must not change during the migration.
    """
    for state in WorkspaceState:
        for action in WorkspaceAction:
            if action in TRANSITIONS[state]:
                continue

            session = _session(state)

            # What the old dispatcher raised.
            with pytest.raises(IllegalWorkspaceActionError) as expected:
                next_state(state, action, session=session)

            # What the graph raises.
            with pytest.raises(IllegalWorkspaceActionError) as actual:
                run_transition(session, action)

            assert actual.value.current_state == expected.value.current_state
            assert actual.value.action == expected.value.action
            assert actual.value.allowed == expected.value.allowed


# ---------------------------------------------------------------------------
# Transitions behave exactly as the old dispatcher did
# ---------------------------------------------------------------------------


def test_search_moves_initial_to_intermediate() -> None:
    """SEARCH: INITIAL -> INTERMEDIATE."""
    session = _session()
    assert run_transition(session, WorkspaceAction.SEARCH) is (
        WorkspaceState.INTERMEDIATE
    )
    assert session.state is WorkspaceState.INTERMEDIATE


def test_generate_moves_intermediate_to_final() -> None:
    """GENERATE: INTERMEDIATE -> FINAL."""
    session = _session(WorkspaceState.INTERMEDIATE)
    assert run_transition(session, WorkspaceAction.GENERATE) is (
        WorkspaceState.FINAL
    )
    assert session.state is WorkspaceState.FINAL


def test_back_to_home_moves_intermediate_to_initial() -> None:
    """BACK_TO_HOME: INTERMEDIATE -> INITIAL."""
    session = _session(WorkspaceState.INTERMEDIATE)
    assert run_transition(session, WorkspaceAction.BACK_TO_HOME) is (
        WorkspaceState.INITIAL
    )


def test_back_to_workspace_moves_final_to_intermediate() -> None:
    """BACK_TO_WORKSPACE: FINAL -> INTERMEDIATE."""
    session = _session(WorkspaceState.FINAL)
    assert run_transition(session, WorkspaceAction.BACK_TO_WORKSPACE) is (
        WorkspaceState.INTERMEDIATE
    )


def test_transition_is_recorded_in_the_audit_trail() -> None:
    """The graph records exactly one audit-trail entry per transition."""
    session = _session()
    history_before = len(session.state_history)

    run_transition(session, WorkspaceAction.SEARCH)

    appended = session.state_history[history_before:]
    assert len(appended) == 1
    entry = appended[0]
    assert entry.from_state is WorkspaceState.INITIAL
    assert entry.to_state is WorkspaceState.INTERMEDIATE
    assert entry.action is WorkspaceAction.SEARCH


def test_rejected_action_does_not_mutate_the_session() -> None:
    """An illegal action leaves the session exactly as it was.

    This is the property that makes it safe to run the legality check
    inside the graph: the aggregate must not be touched when the
    action is refused.
    """
    session = _session()
    history_before = list(session.state_history)

    with pytest.raises(IllegalWorkspaceActionError):
        run_transition(session, WorkspaceAction.GENERATE)

    assert session.state is WorkspaceState.INITIAL
    assert session.state_history == history_before
    assert session.last_error is None


def test_successful_transition_clears_last_error() -> None:
    """A successful transition clears a stale error."""
    session = _session(
        WorkspaceState.ERROR,
        last_known_state=WorkspaceState.INITIAL,
    )
    session.last_error = "RuntimeError: llm down"
    session.last_error_at = session.updated_at

    run_transition(session, WorkspaceAction.RETRY)

    assert session.last_error is None
    assert session.last_error_at is None


# ---------------------------------------------------------------------------
# The session-aware RETRY transition
# ---------------------------------------------------------------------------


def test_retry_returns_to_last_known_state() -> None:
    """RETRY restores the state the workspace was in before the error."""
    session = _session(
        WorkspaceState.ERROR,
        papers=[_paper()],
        last_known_state=WorkspaceState.INTERMEDIATE,
    )
    assert run_transition(session, WorkspaceAction.RETRY) is (
        WorkspaceState.INTERMEDIATE
    )


def test_retry_falls_back_to_the_papers_heuristic() -> None:
    """With no ``last_known_state``, RETRY uses the papers heuristic."""
    without_papers = _session(WorkspaceState.ERROR, last_known_state=None)
    assert run_transition(without_papers, WorkspaceAction.RETRY) is (
        WorkspaceState.INITIAL
    )

    with_papers = _session(
        WorkspaceState.ERROR,
        papers=[_paper()],
        last_known_state=None,
    )
    assert run_transition(with_papers, WorkspaceAction.RETRY) is (
        WorkspaceState.INTERMEDIATE
    )


def test_retry_records_a_single_transition() -> None:
    """RETRY produces one audit-trail entry, not two.

    ADR-018 replaced the old ``transition_to`` + ``force_state``
    override pair with a single session-aware transition. The graph
    must not reintroduce the double entry.
    """
    session = _session(
        WorkspaceState.ERROR,
        papers=[_paper()],
        last_known_state=WorkspaceState.INTERMEDIATE,
    )
    history_before = len(session.state_history)

    run_transition(session, WorkspaceAction.RETRY)

    appended = session.state_history[history_before:]
    assert len(appended) == 1
    assert appended[0].from_state is WorkspaceState.ERROR
    assert appended[0].to_state is WorkspaceState.INTERMEDIATE
    assert appended[0].action is WorkspaceAction.RETRY


def test_retry_is_the_only_legal_action_from_error() -> None:
    """ERROR's legal actions are unchanged by the migration."""
    assert allowed_actions(WorkspaceState.ERROR) == [
        WorkspaceAction.ADD_PAPER,
        WorkspaceAction.REMOVE_PAPER,
        WorkspaceAction.RETRY,
    ]


# ---------------------------------------------------------------------------
# Layering: the domain must stay framework-free
# ---------------------------------------------------------------------------


def test_domain_layer_does_not_import_langgraph() -> None:
    """No module under ``app/domain`` may import LangGraph.

    ``docs/architecture.md`` §5 requires the domain layer to contain
    no framework-specific code. The graph lives in the application
    layer precisely so this holds.
    """
    from pathlib import Path

    domain_root = Path(__file__).resolve().parents[2] / "app" / "domain"
    offenders = [
        path.name
        for path in domain_root.rglob("*.py")
        if "langgraph" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"framework import leaked into the domain layer: {offenders}"
    )


def test_core_layer_does_not_import_langgraph() -> None:
    """No module under ``app/core`` may import LangGraph either."""
    from pathlib import Path

    core_root = Path(__file__).resolve().parents[2] / "app" / "core"
    offenders = [
        path.name
        for path in core_root.rglob("*.py")
        if "langgraph" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"framework import leaked into the core layer: {offenders}"
    )


def test_graph_lives_in_the_application_layer() -> None:
    """The graph is in the application layer, not the domain."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / (
        "app/application/workflows/workspace_graph.py"
    )
    assert path.exists()
