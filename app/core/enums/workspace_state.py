"""
workspace_state.py

Enumeration of the finite set of states a Research Workspace can be in.

Purpose
-------
A Research Workspace follows a deterministic lifecycle. The state
machine is the single source of truth for "what can happen next" in
the BioResearch AI platform. By centralising the states in one enum
we make transitions explicit, testable, and impossible to bypass
by accident.

States are organised around the three pages of the application:

    INITIAL         (Home — landing page)
        │  search
        ▼
    INTERMEDIATE    (Workspace — lab bench where the user curates papers)
        │  generate
        ▼
    FINAL           (Report — finished PDF / LaTeX / executive summary)

ERROR is reachable from any of the three action-driven states and can
be returned to the previous state on retry. ERROR is reserved for
**truly unrecoverable** failures — programmatic bugs, malformed
inputs that bypass the schema, etc. Transient LLM failures (timeouts,
rate limits, 429s, transient token-exhaustion) are NOT routed to
ERROR: the orchestrator retries them silently up to a bound. Only
when the bound is exceeded AND there is no path forward does the
FSM enter ERROR.

Note
----
This is the third iteration of the workspace FSM (the original
2024 release used eleven states with a separate PUBLISHING
transient and a `COMPARING`/`COMPARED` cross-paper evidence
comparison intermediate; the 2026-08-30 refactor dropped the
comparison subsystem for nine states). This 2026-08-31 refactor
collapses the remaining nine states to four — three pages plus
an ERROR — and moves "transient in-flight" semantics to the UI
layer (loading spinners, disabled buttons). The orchestrator
remains the authoritative driver; the FSM is just the
authoritative description of the user-visible workflow. See
ADR-017 for the design rationale.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations
from collections.abc import Callable
from enum import Enum
from typing import Any


class WorkspaceState(str, Enum):
    """
    Discrete states of a Research Workspace.

    The string values are the canonical serialised form used in the
    SQLite database and the REST API. They are deliberately stable so
    that external clients can rely on them.

    Members
    -------
    INITIAL
        The user is on the Home (landing) page. They have entered a
        research question and can click Search. The workspace
        aggregate exists but typically has zero papers.

    INTERMEDIATE
        The user is on the Workspace page. Search has returned at
        least one paper. They can add more papers (manual upload,
        DOI resolve, title search), remove papers, click into a
        paper's DOI / PMID URL, or click Generate Report.

    FINAL
        The user is on the Report page. The report has been
        generated (text + PDF + LaTeX) and is available for
        download. From this page the user can also navigate back to
        INTERMEDIATE (back_to_workspace) to refine the corpus and
        re-generate.

    ERROR
        A truly unrecoverable failure occurred during an FSM action.
        The runtime records the reason on the session and the user
        can recover to the previous state on retry. The UI surfaces
        an Error page with logs and a contact email; transient LLM
        errors are NOT routed here — those are retried silently by
        the orchestrator up to a configurable bound.
    """

    INITIAL = "INITIAL"
    INTERMEDIATE = "INTERMEDIATE"
    FINAL = "FINAL"
    ERROR = "ERROR"

    @property
    def is_terminal(self) -> bool:
        """
        Whether the state is a terminal success state.

        Returns
        -------
        bool
            True if the state is a terminal success state.
        """
        return self is WorkspaceState.FINAL

    @property
    def page(self) -> str:
        """
        The frontend route that corresponds to this state.

        This is the canonical mapping used by the SPA's
        ``<Navigate>`` to route the user to the right page. The
        reverse mapping (``INITIAL → "/"``, ``INTERMEDIATE → "/ws/:id"``,
        ``FINAL → "/report/:id"``, ``ERROR → "/error/:id"``) is what
        the workspaceStore uses to render the right component.

        Returns
        -------
        str
            A short token (one of ``"home"``, ``"workspace"``,
            ``"report"``, ``"error"``) identifying the page. The
            frontend maps these to concrete routes.
        """
        return _PAGE_BY_STATE[self]


_PAGE_BY_STATE: dict[WorkspaceState, str] = {
    WorkspaceState.INITIAL: "home",
    WorkspaceState.INTERMEDIATE: "workspace",
    WorkspaceState.FINAL: "report",
    WorkspaceState.ERROR: "error",
}


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
        Submit the workspace's research question to the literature
        searchers and advance from ``INITIAL`` to ``INTERMEDIATE``.
        The orchestrator creates the workspace if it doesn't exist.

    GENERATE
        Run the summarisation + report generation pipeline and
        advance from ``INTERMEDIATE`` to ``FINAL``. The pipeline
        includes:
          1. Summarise the workspace's papers into a Summary.
          2. Generate the structured ResearchReport.
          3. Render the PDF (reportlab) and the LaTeX source.
          4. Persist all three on the session.
        PDF / LaTeX download is a side-effect available on the
        FINAL page.

    RETRY
        Recover from ``ERROR`` by returning to the previous state.
        The orchestrator remembers the state the workspace was in
        before the error (``INITIAL`` or ``INTERMEDIATE``) and
        restores it. See :class:`WorkspaceSession` for the storage.

    BACK_TO_WORKSPACE
        Navigate the user back from ``FINAL`` to ``INTERMEDIATE``
        so they can refine the corpus and re-generate. Optional —
        iterative refinement is a power-user feature.

    BACK_TO_HOME
        Navigate the user back from ``INTERMEDIATE`` to ``INITIAL``
        so they can start a new search from the Workspace page.
        Optional — the Home page's "new search" button covers most
        use cases.

    ADD_PAPER
        Add a paper directly (e.g. manual curation, DOI resolve,
        title search). Does not change the FSM state. Legal only
        in ``INTERMEDIATE``.

    REMOVE_PAPER
        Remove a paper from the workspace. Does not change the FSM
        state. Legal in any state where the workspace has papers
        (``INTERMEDIATE`` and ``FINAL``; also ``INITIAL`` for the
        rare case of a workspace that was seeded by the
        curator before the user arrived).
    """

    SEARCH = "search"
    GENERATE = "generate"
    RETRY = "retry"
    BACK_TO_WORKSPACE = "back_to_workspace"
    BACK_TO_HOME = "back_to_home"
    ADD_PAPER = "add_paper"
    REMOVE_PAPER = "remove_paper"


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------
#
# Keys are the current state, values are ``{action: target}``. The target
# is either:
#
# 1. A ``WorkspaceState`` constant — the new state is the same regardless
#    of session context. Used for actions whose outcome is purely a
#    function of the current state (search, generate, back_to_*,
#    add_paper, remove_paper, complete).
#
# 2. A ``Callable[[ResearchSession], WorkspaceState]`` — the new state
#    depends on session context (papers, summary, etc.). Used when the
#    FSM's decision needs more than the current state to make. The only
#    caller today is ``RETRY`` from ``ERROR``, which lands on
#    ``INTERMEDIATE`` if the workspace has papers (the user was
#    mid-generation) and ``INITIAL`` otherwise (the user was trying to
#    start a fresh search).
#
# The callable form is the **first-class way** to express
# context-sensitive transitions. We previously used a static
# ``INITIAL`` entry + ``force_state`` override in the orchestrator,
# but that left the audit trail with two transitions
# (``ERROR → INITIAL`` from the table, then ``INITIAL → INTERMEDIATE``
# from the override) instead of one and required a
# documented-as-private ``force_state`` API to escape the FSM.
#
# Actions absent from a state's mapping are illegal. The transition
# table is the authoritative FSM specification and is consumed by
# both the ResearchSession (pure domain) and the WorkspaceOrchestrator
# (application). Keeping it in one module makes the FSM auditable.
# ---------------------------------------------------------------------------

#: A transition target is either a fixed state or a resolver callable
#: that takes the session and returns the new state. The resolver
#: receives the full ResearchSession (not just the FSM state) so it
#: can inspect papers, summary, report, etc. when deciding the
#: destination. Resolvers MUST be pure functions of the session —
#: they MUST NOT mutate it or call repository operations.
TransitionTarget = (
    "WorkspaceState "
    "| Callable[[ResearchSession], WorkspaceState]"
)

def _retry_target(session: Any) -> WorkspaceState:
    """Session-aware resolver for the ``ERROR + RETRY`` transition.

    Picks the destination state based on the session's
    ``last_known_state`` (set by :meth:`ResearchSession.fail` /
    the orchestrator's ``_fail()`` helper). Falls back to a
    papers-based heuristic when ``last_known_state`` is missing
    (e.g. for pre-v8 upgraded rows where the column was NULL).

    The resolver is a pure function of the session — it MUST NOT
    mutate the session or call repository operations. The orchestrator
    persists the new state via ``_repository.update()`` after this
    returns.

    Parameters
    ----------
    session : ResearchSession
        The session being transitioned. The function only reads
        ``last_known_state`` and ``papers``; it never writes.

    Returns
    -------
    WorkspaceState
        The destination state. ``INTERMEDIATE`` if the workspace
        had papers before the error (user was mid-generation);
        ``INITIAL`` otherwise.
    """
    last_known = getattr(session, "last_known_state", None)
    if last_known is not None:
        return last_known
    # Corrupted / pre-v8 row -- fall back to the papers heuristic.
    # ``session.papers`` may be ``None`` (test fixtures seed it
    # explicitly) so we tolerate that.
    has_papers = bool(getattr(session, "papers", None))
    return WorkspaceState.INTERMEDIATE if has_papers else WorkspaceState.INITIAL

TRANSITIONS: dict[
    WorkspaceState,
    dict[WorkspaceAction, "WorkspaceState | Callable[[ResearchSession], WorkspaceState]"],
] = {
    # Home page: only "search" advances the workflow.
    WorkspaceState.INITIAL: {
        WorkspaceAction.SEARCH: WorkspaceState.INTERMEDIATE,
        # add_paper and remove_paper are legal in INITIAL so a
        # curator can pre-seed a workspace. The orchestrator
        # treats these as no-op FSM-wise.
        WorkspaceAction.ADD_PAPER: WorkspaceState.INITIAL,
        WorkspaceAction.REMOVE_PAPER: WorkspaceState.INITIAL,
    },
    # Workspace page: most actions live here.
    WorkspaceState.INTERMEDIATE: {
        WorkspaceAction.GENERATE: WorkspaceState.FINAL,
        WorkspaceAction.ADD_PAPER: WorkspaceState.INTERMEDIATE,
        WorkspaceAction.REMOVE_PAPER: WorkspaceState.INTERMEDIATE,
        WorkspaceAction.BACK_TO_HOME: WorkspaceState.INITIAL,
    },
    # Report page: read-mostly. PDF download is a side-effect of
    # generate (no FSM action).
    WorkspaceState.FINAL: {
        WorkspaceAction.BACK_TO_WORKSPACE: WorkspaceState.INTERMEDIATE,
        # Paper list is still mutable — the user might want to
        # fix a typo in a paper's title before exporting.
        WorkspaceAction.ADD_PAPER: WorkspaceState.FINAL,
        WorkspaceAction.REMOVE_PAPER: WorkspaceState.FINAL,
    },
    # Error page: only "retry" (back to where we were) makes sense.
    WorkspaceState.ERROR: {
        # ERROR → retry is **session-aware**: the destination
        # depends on where the workspace was before the error
        # was entered. The ``_retry_target`` resolver reads
        # ``ResearchSession.last_known_state`` (set by the
        # orchestrator's ``_fail()`` helper when ERROR is
        # entered) and falls back to a heuristic based on
        # whether the workspace has any papers:
        #
        #   last_known_state == INTERMEDIATE → INTERMEDIATE
        #     (the user was mid-generation; we keep their
        #     corpus and let them try again).
        #
        #   last_known_state == INITIAL      → INITIAL
        #     (the user was trying to start a fresh search;
        #     nothing to preserve).
        #
        #   last_known_state is None (corrupted or
        #     pre-v8 row) → heuristic: INTERMEDIATE if the
        #     workspace has papers, INITIAL otherwise. This
        #     is the same fallback the orchestrator's
        #     ``retry()`` used to do before the FSM became
        #     context-aware; preserved here so the FSM table
        #     continues to encode the user-visible behaviour
        #     rather than overriding it after the fact.
        WorkspaceAction.RETRY: _retry_target,
        WorkspaceAction.ADD_PAPER: WorkspaceState.ERROR,
        WorkspaceAction.REMOVE_PAPER: WorkspaceState.ERROR,
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
    *,
    session: Any | None = None,
) -> WorkspaceState:
    """
    Compute the next state for a given action.

    Parameters
    ----------
    current : WorkspaceState
        Current workspace state.

    action : WorkspaceAction
        Action being requested.

    session : Any | None
        The :class:`ResearchSession` (or any object exposing the
        fields the resolver needs). Required when the table entry
        is a callable resolver (currently only ``RETRY`` from
        ``ERROR``); ignored for fixed-target entries. Kept as
        ``Any`` to avoid an import cycle (this module is imported
        by the entity layer, which can't import this module back).

        The orchestrator always passes the session; the entity's
        :meth:`ResearchSession.transition_to` passes ``self``. The
        test layer may omit it when exercising fixed-target
        entries.

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
    target = transitions[action]
    if callable(target):
        # ``target`` is a session-aware resolver. The session
        # argument is mandatory for callable targets; if the
        # caller forgot to pass it, that's a programmer error,
        # not a runtime FSM ambiguity.
        if session is None:
            raise TypeError(
                f"FSM transition {current.value} + {action.value} "
                f"is session-aware (resolver={getattr(target, '__name__', target)!r}); "
                "next_state() requires the session argument."
            )
        return target(session)
    return target
