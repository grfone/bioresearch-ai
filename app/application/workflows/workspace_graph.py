"""
workspace_graph.py

LangGraph definition of the Research Workspace FSM.

Purpose
-------
This module is the **executable** form of the workspace finite
state machine. The state machine has two parts, and this module
replaces the second one:

1. The **specification** — which actions are legal from which
   states, and where each one leads — lives in
   ``app/core/enums/workspace_state.py`` as the ``TRANSITIONS``
   table. It is pure data with no framework dependency, because the
   domain aggregate (``ResearchSession``) needs it to enforce its own
   invariants, and the domain layer must stay framework-free (see
   ``docs/architecture.md`` §5).

2. The **runtime** — the thing that decides, at request time, which
   transition an action performs and whether it is legal at all —
   used to be a hand-written ``if``/``elif`` chain inside
   ``WorkspaceOrchestrator._enter_action``. It is now this graph.

The graph is *derived from* the specification rather than written
alongside it, so the two cannot drift apart. The previous
``app/application/workflows/research_workflow.py`` was a hand-written
mirror of the FSM that had already drifted (it modelled a
``search → summarise → report`` pipeline that no longer exists after
ADR-017, and it was never executed by anything). It has been removed.

Design
------
The graph is a **state machine**: each node is a workspace state and
each conditional edge is an action taken from that state.

    INITIAL     ── search ──────────▶ INTERMEDIATE
    INTERMEDIATE── generate ────────▶ FINAL
    INTERMEDIATE── back_to_home ───▶ INITIAL
    FINAL       ── back_to_workspace ▶ INTERMEDIATE
    ERROR       ── retry ───────────▶ INITIAL | INTERMEDIATE

The edge labels are the action names, so ``WORKSPACE_GRAPH`` renders
as a labelled diagram of the FSM:

.. code-block:: python

    from app.application.workflows.workspace_graph import WORKSPACE_GRAPH
    print(WORKSPACE_GRAPH.get_graph().draw_mermaid())

Routing
-------
Routing is delegated to ``next_state()`` — the same pure function
the domain aggregate uses — so the graph and the aggregate can never
disagree about what is legal. The router raises
:class:`IllegalWorkspaceActionError` with the same
``current_state`` / ``action`` / ``allowed`` payload the previous
imperative dispatcher produced, so the API layer's 409 Conflict
response is byte-for-byte unchanged.

The session-aware ``ERROR + retry`` transition is resolved here too:
``next_state(..., session=session)`` reads ``last_known_state`` and
falls back to the papers heuristic, which keeps the single-transition
audit trail ADR-018 introduced (one ``ERROR → <destination>`` entry,
not two).

Layering
--------
This module lives in the **application** layer, which
``ARCHITECTURE.md` §2 lists as the home of "LangGraph workflows".
``app/domain`` deliberately contains no framework-specific code, so
the domain aggregate continues to use the pure ``TRANSITIONS`` table
directly and knows nothing about this graph.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.enums.workspace_state import (
    TRANSITIONS,
    WorkspaceAction,
    WorkspaceState,
    next_state,
)
from app.core.exceptions import IllegalWorkspaceActionError
from app.domain.entities.research_session import ResearchSession


#: The actions that actually move the workspace between states.
#:
#: ``add_paper`` and ``remove_paper`` are legal actions in the FSM
#: table but they are *recording* actions: they mutate the paper
#: collection without changing the FSM state, and the orchestrator
#: deliberately does not record a transition for them. They are
#: therefore not routed through this graph.
TRANSITIONING_ACTIONS: frozenset[WorkspaceAction] = frozenset(
    {
        WorkspaceAction.SEARCH,
        WorkspaceAction.GENERATE,
        WorkspaceAction.RETRY,
        WorkspaceAction.BACK_TO_WORKSPACE,
        WorkspaceAction.BACK_TO_HOME,
    }
)


class WorkspaceGraphState(TypedDict, total=False):
    """
    The state that flows through the workspace FSM graph.

    Attributes
    ----------
    session : ResearchSession
        The aggregate under orchestration. It is mutated in place
        by the transition node, so the object identity is stable
        across the graph run.
    action : WorkspaceAction
        The action being applied.
    to_state : WorkspaceState
        The state the workspace ends up in. Written by the
        transition node and read by the caller.
    """

    session: ResearchSession
    action: WorkspaceAction
    to_state: WorkspaceState


def _source_node_name(state: WorkspaceState) -> str:
    """Return the graph node name for a workspace state as a source."""
    return f"state_{state.value.lower()}"


def _destination_node_name(state: WorkspaceState) -> str:
    """Return the graph node name for a workspace state as a destination."""
    return f"land_{state.value.lower()}"


def _edge_key(action: WorkspaceAction, target: WorkspaceState) -> str:
    """
    Return the conditional-edge key for an action and its target.

    The key carries both the action and the destination because a
    single action can have more than one destination: ``retry`` from
    ``ERROR`` lands on ``INITIAL`` or ``INTERMEDIATE`` depending on
    the session. Labelling the edge with the action name is what
    makes the rendered diagram a readable FSM.
    """
    return f"{action.value}:{target.value.lower()}"


def _probe_resolver_destinations(resolver: Any) -> set[WorkspaceState]:
    """
    Determine every state a session-aware resolver can return.

    A resolver is a plain callable over the session, so the set of
    destinations it can produce is discovered by *calling* it with
    probe sessions rather than by hard-coding it. The probes cover
    each ``last_known_state`` value (including ``None``) crossed with
    both an empty and a populated paper list, which is exactly the
    context ``_retry_target`` consults.

    This keeps the graph honest if a future resolver gains a third
    outcome: the destination node and the path-map entry are created
    from the resolver's real behaviour, not from an assumption.

    Parameters
    ----------
    resolver : Any
        The callable transition target.

    Returns
    -------
    set[WorkspaceState]
        Every distinct state the resolver returned across the probes.
    """
    destinations: set[WorkspaceState] = set()
    last_known_values: list[WorkspaceState | None] = [
        None,
        *list(WorkspaceState),
    ]
    paper_lists: list[list[Any]] = [[], [SimpleNamespace(pmid="1")]]
    for last_known in last_known_values:
        for papers in paper_lists:
            probe = SimpleNamespace(
                last_known_state=last_known,
                papers=papers,
                state=WorkspaceState.ERROR,
                summary=None,
                report=None,
                published_report=None,
            )
            destinations.add(resolver(probe))
    return destinations


def _resolve_destinations(target: Any) -> set[WorkspaceState]:
    """
    Return every state a transition target can lead to.

    Fixed targets lead to exactly one state. Session-aware resolvers
    are probed — see :func:`_probe_resolver_destinations`.
    """
    if callable(target):
        return _probe_resolver_destinations(target)
    return {target}


def _reachable_destinations() -> set[WorkspaceState]:
    """
    Return every state that a legal action can lead to.

    ``ERROR`` is deliberately absent: it is entered only by
    ``ResearchSession.force_state`` when an action fails, never by a
    legal action. The failure path is the orchestrator's job; the
    FSM graph models the action-driven lifecycle.

    Deriving this from the transition table (rather than listing the
    states) means a future transition to ``ERROR`` would simply
    produce the matching destination node.
    """
    destinations: set[WorkspaceState] = set()
    for actions in TRANSITIONS.values():
        for action, target in actions.items():
            if action not in TRANSITIONING_ACTIONS:
                continue
            destinations |= _resolve_destinations(target)
    return destinations


def _build_path_map(state: WorkspaceState) -> dict[str, str]:
    """
    Build the conditional-edge path map for a source state.

    Only the transitioning actions get an edge. ``add_paper`` and
    ``remove_paper`` are legal from every state but do not move the
    workspace, and the orchestrator never records a transition for
    them — see :data:`TRANSITIONING_ACTIONS`.
    """
    path_map: dict[str, str] = {}
    for action, target in TRANSITIONS[state].items():
        if action not in TRANSITIONING_ACTIONS:
            continue
        for candidate in _resolve_destinations(target):
            path_map[_edge_key(action, candidate)] = _destination_node_name(candidate)
    return path_map


def _missing_context_error() -> IllegalWorkspaceActionError:
    """Build the error raised when the graph is invoked without context."""
    return IllegalWorkspaceActionError(
        current_state="UNKNOWN",
        action="unknown",
        allowed=[],
    )


def _build_transition_router() -> Any:
    """
    Build the conditional-edge router shared by every state node.

    The router is the heart of the migration. It replaces the
    imperative ``next_state()`` call the orchestrator used to make in
    each action method.

    The routing rule is *identical* to the old dispatcher:

    1. If the action is not legal from the current state, raise
       :class:`IllegalWorkspaceActionError` with the same
       ``current_state`` / ``action`` / ``allowed`` payload the
       former dispatcher produced — the API layer turns that into a
       409 Conflict, so the wire format must not change.
    2. Otherwise return the edge key for the destination state.

    The session-aware ``ERROR + retry`` transition is resolved
    through ``next_state(..., session=session)``, which reads
    ``last_known_state`` and falls back to the papers heuristic.
    That keeps the single-transition audit trail that ADR-018
    introduced: one ``ERROR → <destination>`` entry, not two.
    """

    def route(state: WorkspaceGraphState) -> str:
        session = state.get("session")
        action = state.get("action")
        if session is None or action is None:
            raise _missing_context_error()
        destination = next_state(session.state, action, session=session)
        return _edge_key(action, destination)

    return route


def build_workspace_graph() -> Any:
    """
    Build and compile the Research Workspace FSM as a LangGraph.

    The graph is derived from ``app.core.enums.workspace_state``'s
    ``TRANSITIONS`` table, so the executable topology and the
    declarative specification can never drift apart.

    Each workspace state appears twice: ``state_<name>`` is the
    state as a *source* (you are here, about to take an action) and
    ``land_<name>`` is the state as a *destination* (the action
    succeeded, the workspace is now here). A run is

        START -> state_<current> -[action]-> land_<target> -> END

    Splitting source from destination is what makes the graph
    terminate: LangGraph follows every outgoing edge of a node it
    lands on, so a single node per state would send the graph round
    the FSM forever.

    Returns
    -------
    langgraph.graph.CompiledStateGraph
        The compiled graph. Invoke it with a
        :class:`WorkspaceGraphState` carrying the session and the
        requested action; it returns the state after the transition
        has been applied.

    Raises
    ------
    IllegalWorkspaceActionError
        Propagated from the edge router when the requested action
        is not legal from the session's current state.
    """
    graph = StateGraph(WorkspaceGraphState)

    router = _build_transition_router()

    def entry_router(state: WorkspaceGraphState) -> str:
        """
        Route into the source node for the session's current state.

        The session's own state is authoritative — the graph keeps no
        separate copy of "where we are", so there is nothing to fall
        out of sync with the persisted aggregate.
        """
        session = state.get("session")
        if session is None:
            raise _missing_context_error()
        return _source_node_name(session.state)

    def source_node(state: WorkspaceGraphState) -> dict[str, Any]:
        """
        Mark "we are here, about to take an action".

        The node carries no decision of its own — the conditional
        edge leaving it does that. It re-emits the session so the
        run has a valid state update to merge.
        """
        session = state.get("session")
        if session is None:
            raise _missing_context_error()
        return {"session": session}

    def destination_node(state: WorkspaceGraphState) -> dict[str, Any]:
        """
        Apply the transition to the aggregate and record the result.

        ``ResearchSession.transition_to`` is the aggregate's own
        mutator: it re-validates the action against ``TRANSITIONS``
        (an aggregate must never trust its caller), appends the
        transition to the audit trail, and clears or sets
        ``last_error``. By the time this node runs, the router has
        already resolved the destination, so the re-validation
        cannot fail.
        """
        session = state.get("session")
        action = state.get("action")
        if session is None or action is None:
            raise _missing_context_error()
        session.transition_to(action)
        return {"to_state": session.state}

    for workspace_state in WorkspaceState:
        graph.add_node(_source_node_name(workspace_state), source_node)
    for workspace_state in _reachable_destinations():
        graph.add_node(_destination_node_name(workspace_state), destination_node)

    # START dispatches into the source node for the session's
    # current state.
    graph.add_conditional_edges(
        START,
        entry_router,
        {_source_node_name(s): _source_node_name(s) for s in WorkspaceState},
    )

    # From each source node, the action router decides the
    # destination. LangGraph validates the router's return value
    # against the path map, so a routing bug surfaces as a graph
    # error rather than a silent no-op.
    for workspace_state in WorkspaceState:
        graph.add_conditional_edges(
            _source_node_name(workspace_state),
            router,
            _build_path_map(workspace_state),
        )

    # The destination nodes are terminal: the transition has been
    # applied and the run is over. They deliberately have no outgoing
    # edges of their own.
    for workspace_state in _reachable_destinations():
        graph.add_edge(_destination_node_name(workspace_state), END)

    return graph.compile()


#: The compiled workspace FSM. Built once at import time — the
#: topology is static, only the session changes between runs.
WORKSPACE_GRAPH = build_workspace_graph()


def run_transition(
    session: ResearchSession,
    action: WorkspaceAction,
) -> WorkspaceState:
    """
    Apply an action to a session by running it through the graph.

    This is the replacement for the orchestrator's old
    ``session.transition_to(action)`` call. The legality check and
    the destination resolution now live in the graph's conditional
    edges rather than in a Python ``if`` chain.

    Parameters
    ----------
    session : ResearchSession
        The workspace to transition.
    action : WorkspaceAction
        The action to apply.

    Returns
    -------
    WorkspaceState
        The state the session ends up in.

    Raises
    ------
    IllegalWorkspaceActionError
        If the action is not legal from the session's current state.
        The payload (``current_state``, ``action``, ``allowed``) is
        byte-for-byte what the previous dispatcher produced, so the
        API layer's 409 response is unchanged.
    """
    result = WORKSPACE_GRAPH.invoke(
        {"session": session, "action": action},
    )
    return result["to_state"]
