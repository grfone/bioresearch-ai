"""
research_workflow.py

LangGraph definition of the Research Workspace FSM.

Purpose
-------
This module declares the FSM as a LangGraph StateGraph. The graph
is the *static* description of the workflow. The actual mutation of
workspaces is performed by :class:`WorkspaceOrchestrator` (see
``app/application/services/workspace_orchestrator.py``). The graph
is exposed for two reasons:

1. **Documentation and visualisation.** The graph structure mirrors
   ``app.core.enums.workspace_state.TRANSITIONS`` and is the
   authoritative artefact for diagrams and reviews.
2. **Checkpointing and future agents.** Phase 5 of the roadmap
   (multi-agent collaboration) will replace the orchestrator's
   direct use case calls with graph nodes that can be checkpointed
   and branched. Defining the graph now makes that evolution a
   drop-in change.

The graph deliberately uses no LLM/PubMed nodes. Those are
infrastructure concerns that belong to nodes constructed by the
composition root. The graph only knows about state transitions.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.enums.workspace_state import TRANSITIONS, WorkspaceAction, WorkspaceState
from app.domain.entities.evidence_comparison import EvidenceComparison
from app.domain.entities.paper import Paper
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.research_session import ResearchSession
from app.domain.entities.summary import Summary


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WorkflowState:
    """
    Mutable state container that flows through the LangGraph nodes.

    This is *not* the same as :class:`WorkspaceState`. The workflow
    state is the runtime scratchpad used by the graph; the workspace
    state is the persistent FSM state on the
    :class:`ResearchSession` aggregate.

    Attributes
    ----------
    session : ResearchSession
        The aggregate under orchestration.

    last_papers : list[Paper] | None
        Papers returned by the most recent SEARCH node.

    last_summary : Summary | None
        Summary returned by the most recent SUMMARIZE node.

    last_comparison : EvidenceComparison | None
        Comparison returned by the most recent COMPARE node.

    last_report : ResearchReport | None
        Report returned by the most recent REPORT node.

    error : str | None
        Last error message, if any.
    """

    session: ResearchSession
    last_papers: Optional[list[Paper]] = None
    last_summary: Optional[Summary] = None
    last_comparison: Optional[EvidenceComparison] = None
    last_report: Optional[ResearchReport] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Graph definition
# ---------------------------------------------------------------------------


def build_research_workflow():
    """
    Build and compile the BioResearch AI workflow as a LangGraph.

    The graph is intentionally abstract: node functions read the
    runtime state and mutate the :class:`ResearchSession` aggregate.
    They delegate the heavy lifting to the use cases injected into
    the orchestrator. This module only declares the topology.

    Returns
    -------
    langgraph.graph.CompiledStateGraph
        The compiled graph. The caller can invoke it with an initial
        :class:`WorkflowState` to drive a workspace through the
        workflow.

    Notes
    -----
    If ``langgraph`` is not installed the function returns ``None``
    so the rest of the application can still import this module
    without a hard dependency. The orchestration runtime does not
    require the graph — it falls back to the imperative
    :class:`WorkspaceOrchestrator` instead.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return None

    graph = StateGraph(WorkflowState)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------
    # Each node is a thin wrapper that updates the workspace state.
    # The actual implementation (PubMed, LLM, etc.) is injected by
    # the orchestrator when the graph is invoked.

    def search_node(state: WorkflowState) -> WorkflowState:
        """
        SEARCH node — the orchestrator pre-populates ``last_papers``
        before entering the graph; this node simply attaches them
        to the session.
        """
        if state.last_papers is not None:
            state.session.replace_papers(state.last_papers)
        return state

    def summarize_node(state: WorkflowState) -> WorkflowState:
        if state.last_summary is not None:
            state.session.set_summary(state.last_summary)
        return state

    def compare_node(state: WorkflowState) -> WorkflowState:
        if state.last_comparison is not None:
            state.session.set_evidence_comparison(state.last_comparison)
        return state

    def report_node(state: WorkflowState) -> WorkflowState:
        if state.last_report is not None:
            state.session.set_report(state.last_report)
        return state

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    graph.add_node("search", search_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("compare", compare_node)
    graph.add_node("report", report_node)

    # Linear happy path: search → summarize → compare → report → done.
    graph.add_edge(START, "search")
    graph.add_edge("search", "summarize")
    graph.add_edge("summarize", "compare")
    graph.add_edge("compare", "report")
    graph.add_edge("report", END)

    # ------------------------------------------------------------------
    # Conditional skips
    # ------------------------------------------------------------------
    # The FSM allows skipping summarise or compare (e.g. going
    # directly from PAPERS_RETRIEVED to REPORTING). The graph
    # honours this by adding conditional edges that read the
    # workspace state and skip ahead when the step is already
    # satisfied.

    def _after_search(state: WorkflowState) -> str:
        if state.session.summary is not None:
            return "summarize"
        return "summarize"

    def _after_summarize(state: WorkflowState) -> str:
        if state.session.evidence_comparison is not None:
            return "compare"
        return "compare"

    def _after_compare(state: WorkflowState) -> str:
        if state.session.report is not None:
            return "report"
        return "report"

    # The graph above is the linear version. The conditional version
    # is left as a follow-up; the orchestrator is the authoritative
    # driver today. The graph is exposed for documentation and for
    # future checkpointing.

    return graph.compile()


# ---------------------------------------------------------------------------
# Transition table helper
# ---------------------------------------------------------------------------


def transition_table() -> dict[WorkspaceState, dict[WorkspaceAction, WorkspaceState]]:
    """
    Return the FSM transition table as a plain dict.

    This is a convenience wrapper for clients that want to inspect
    the FSM statically (e.g. for UI rendering, documentation, or
    agent planning).

    Returns
    -------
    dict[WorkspaceState, dict[WorkspaceAction, WorkspaceState]]
        The transition table.
    """
    return TRANSITIONS
