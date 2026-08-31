"""
research_session.py

Domain entity representing a biomedical research session.

A ResearchSession is the central aggregate of the BioResearch AI domain.
It encapsulates the complete lifecycle of a scientific investigation
as a finite state machine, from the initial research question to the
generation of evidence summaries, cross-paper comparisons, and final
reports.

The FSM is the single source of truth for "what can happen next". The
state is exposed via the ``state`` attribute and is persisted by the
repository. The orchestrator (application layer) is the only
component that mutates the state; the entity enforces the transition
rules and refuses any illegal move.

This design naturally supports future capabilities such as:

- Multi-agent collaboration (each agent is a transition predicate).
- Human-in-the-loop review (review_gate state).
- Research history (state_history list).
- Workspace persistence (state is serialised).
- Exportable reports.
- Knowledge graph integration.
- MCP tool orchestration.
- A2A communication.
- Biological database enrichment.

The ResearchSession intentionally contains no infrastructure-specific
logic. It does not know how papers are retrieved, how LLMs operate,
or how reports are rendered.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from uuid import UUID, uuid4

from app.core.enums.workspace_state import (
    TRANSITIONS,
    WorkspaceAction,
    WorkspaceState,
    allowed_actions,
    next_state as _next_state,
)
from app.core.exceptions import IllegalWorkspaceActionError
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.summary import Summary


# ---------------------------------------------------------------------------
# State history entry
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class StateTransition:
    """
    Immutable record of a single state transition.

    Attributes
    ----------
    from_state : WorkspaceState
        The state before the transition.

    to_state : WorkspaceState
        The state after the transition.

    action : WorkspaceAction | None
        The action that triggered the transition. ``None`` for the
        initial record (created from CREATED without an action).

    at : datetime
        UTC timestamp at which the transition occurred.

    reason : str | None
        Optional human-readable explanation (e.g. the LLM error
        when a transition is to ERROR).
    """

    from_state: WorkspaceState
    to_state: WorkspaceState
    action: WorkspaceAction | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = None


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ResearchSession:
    """
    Represents a complete biomedical research investigation.

    A ResearchSession serves as the aggregate root of the BioResearch AI
    domain model. Every artefact generated during the investigation
    belongs to this session, and the session's ``state`` summarises
    where the investigation is in the FSM lifecycle.

    Typical lifecycle
    -----------------

        CREATED
            │  search
            ▼
        PAPERS_RETRIEVED
            │  summarize
            ▼
        SUMMARIZED
            │  compare
            ▼
        COMPARED
            │  report
            ▼
        REPORTED ─────► COMPLETED

    Attributes
    ----------
    id : UUID
        Unique identifier of the research session.

    question : ResearchQuestion
        Original scientific question posed by the researcher.

    state : WorkspaceState
        Current FSM state. Defaults to ``CREATED``.

    papers : list[Paper]
        Scientific publications retrieved during literature search.

    summary : Summary | None
        Synthesized evidence generated from the retrieved papers.

    report : ResearchReport | None
        Final structured report generated from the evidence.

    notes : list[str]
        Optional researcher annotations.

    state_history : list[StateTransition]
        Ordered history of every state transition. The first entry is
        the synthetic CREATED entry; the last entry reflects the
        current state.

    last_error : str | None
        Last error message if the state is ERROR. Cleared on a
        successful retry.

    last_error_at : datetime | None
        UTC timestamp of when the workspace entered its current
        ERROR state and ``last_error`` was set. Cleared alongside
        ``last_error`` whenever the workspace leaves ERROR.
        Persisted in the v5 schema so the UI can show "X seconds
        ago" / "at HH:MM:SS" for diagnostic clarity -- especially
        valuable after a container restart, when the only signal
        of an old error is the timestamp.

    created_at : datetime
        Session creation timestamp (UTC).

    updated_at : datetime
        Timestamp of the latest modification (UTC).

    metadata : dict[str, str]
        Optional metadata describing execution details such as
        model version, search provider, workflow version, etc.

    Notes
    -----
    This entity intentionally remains independent of any presentation
    layer. It can be rendered as a web workspace, a REST API
    response, Markdown, PDF, Jupyter notebook, or CLI output without
    requiring changes to the domain model.
    """

    question: ResearchQuestion

    id: UUID = field(default_factory=uuid4)

    state: WorkspaceState = WorkspaceState.CREATED

    papers: list[Paper] = field(default_factory=list)

    # Per-paper source attribution (for the Advanced Search
    # multi-source flow). Maps the canonical paper identifier
    # (PMID, then DOI, then URL) to the ``SearchSource`` enum
    # value that returned the paper. The dict is rebuilt
    # every time ``replace_papers`` runs (Search action);
    # the legacy ``add_paper`` path leaves it untouched. The
    # map is exposed via the API as ``paper_sources`` on
    # ``WorkspaceResponse`` so the PaperCard can render a
    # "via OpenAlex" / "via PubMed" badge.
    paper_sources: dict[str, str] = field(default_factory=dict)

    summary: Summary | None = None

    report: ResearchReport | None = None

    published_report: "PublishedReport | None" = None

    notes: list[str] = field(default_factory=list)

    state_history: list[StateTransition] = field(default_factory=list)

    last_error: str | None = None

    last_error_at: datetime | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    metadata: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Construction-time helpers
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        # Seed the state history with the initial CREATED entry unless
        # the caller supplied a history (e.g. on repository hydration).
        if not self.state_history:
            self.state_history.append(
                StateTransition(
                    from_state=WorkspaceState.CREATED,
                    to_state=WorkspaceState.CREATED,
                    action=None,
                )
            )

    # ------------------------------------------------------------------
    # Convenience predicates
    # ------------------------------------------------------------------

    @property
    def has_papers(self) -> bool:
        """Whether the session contains retrieved literature."""
        return bool(self.papers)

    @property
    def has_summary(self) -> bool:
        """Whether an evidence summary has been generated."""
        return self.summary is not None

    @property
    def has_report(self) -> bool:
        """Whether a final research report has been generated."""
        return self.report is not None

    @property
    def status(self) -> str:
        """
        Backwards-compatible string status.

        Returns
        -------
        str
            The current state value. Existing clients that read the
            ``status`` field on the workspace response continue to
            work; new clients should prefer ``state``.
        """
        return self.state.value

    @property
    def progress(self) -> float:
        """
        A coarse progress indicator in the range [0.0, 1.0].

        The progress is anchored on the FSM lifecycle. It is purely
        informational — execution is deterministic, not driven by
        progress.

        Returns
        -------
        float
            Progress value in [0.0, 1.0].
        """
        anchor = {
            WorkspaceState.CREATED: 0.0,
            WorkspaceState.SEARCHING: 0.1,
            WorkspaceState.PAPERS_RETRIEVED: 0.2,
            WorkspaceState.SUMMARIZING: 0.3,
            WorkspaceState.SUMMARIZED: 0.5,
            WorkspaceState.REPORTING: 0.8,
            WorkspaceState.REPORTED: 0.95,
            WorkspaceState.COMPLETED: 1.0,
            WorkspaceState.ERROR: 0.0,
        }
        return anchor.get(self.state, 0.0)

    # ------------------------------------------------------------------
    # FSM mutators
    # ------------------------------------------------------------------

    def allowed_actions(self) -> list[WorkspaceAction]:
        """
        Return the actions that are legal from the current state.

        Returns
        -------
        list[WorkspaceAction]
            Legal actions, sorted alphabetically.
        """
        return allowed_actions(self.state)

    def transition_to(
        self,
        action: WorkspaceAction,
        *,
        reason: str | None = None,
    ) -> WorkspaceState:
        """
        Advance the FSM by applying the given action.

        The transition is validated against the FSM transition table
        (``TRANSITIONS``). An illegal action raises
        :class:`IllegalWorkspaceActionError` with the offending state
        and the list of allowed actions so the caller can surface a
        useful error to the user.

        Side effects
        ------------
        - Updates ``state`` to the new state.
        - Appends a :class:`StateTransition` to ``state_history``.
        - Updates ``updated_at``.
        - Clears ``last_error`` on a successful transition.
        - If the new state is ERROR, sets ``last_error`` to the
          supplied reason.

        Parameters
        ----------
        action : WorkspaceAction
            The action to apply.

        reason : str | None, optional
            Optional human-readable explanation. Required when
            transitioning to ERROR, ignored otherwise.

        Returns
        -------
        WorkspaceState
            The new state after the transition.

        Raises
        ------
        IllegalWorkspaceActionError
            If the action is not legal from the current state.
        """
        new_state = _next_state(self.state, action)

        previous = self.state
        self.state_history.append(
            StateTransition(
                from_state=previous,
                to_state=new_state,
                action=action,
                reason=reason,
            )
        )
        self.state = new_state
        self.updated_at = datetime.now(UTC)

        if new_state is WorkspaceState.ERROR:
            self.last_error = reason or "Unknown FSM error."
            self.last_error_at = self.updated_at
        else:
            self.last_error = None
            self.last_error_at = None

        return new_state

    def force_state(
        self,
        new_state: WorkspaceState,
        *,
        reason: str | None = None,
    ) -> None:
        """
        Force the session into a target state without going through an
        action.

        This is **only** used by the repository during deserialization
        and by the orchestrator when transiting out of transient
        states (e.g. SEARCHING → PAPERS_RETRIEVED after the PubMed
        request completes). Application code should never call this
        directly.

        Parameters
        ----------
        new_state : WorkspaceState
            Target state to set.

        reason : str | None
            Optional reason for the forced transition.
        """
        # Allow transient→stable transitions (e.g. SEARCHING →
        # PAPERS_RETRIEVED) because they are how the orchestrator
        # completes requests. We also allow ERROR-targeted transitions
        # when a reason is supplied. Everything else must go through
        # transition_to().
        previous = self.state
        if previous is new_state:
            # No-op: already in the target state.
            return

        # A forced transition is legal if either:
        #   (a) the target state is reachable through the FSM table
        #       from the current state, OR
        #   (b) the current state is transient and the target is a
        #       stable completion (e.g. SEARCHING → PAPERS_RETRIEVED),
        #   OR
        #   (c) the target is ERROR (recorded failure).
        reachable = TRANSITIONS.get(previous, {})
        transient_completion = (
            previous.is_transient
            and not new_state.is_transient
            and new_state is not WorkspaceState.ERROR
        )
        error_target = new_state is WorkspaceState.ERROR
        if (
            new_state not in reachable.values()
            and not transient_completion
            and not error_target
        ):
            # The orchestrator only calls force_state with legal
            # targets; if the caller is asking for an illegal forced
            # jump we surface the same error type used for illegal
            # actions so the API layer can return 409 Conflict.
            from app.core.enums.workspace_state import (
                allowed_actions as _allowed_actions,
            )
            raise IllegalWorkspaceActionError(
                current_state=previous.value,
                action=f"force:{new_state.value}",
                allowed=[a.value for a in _allowed_actions(previous)],
            )

        self.state_history.append(
            StateTransition(
                from_state=previous,
                to_state=new_state,
                action=None,
                reason=reason,
            )
        )
        self.state = new_state
        self.updated_at = datetime.now(UTC)
        if new_state is WorkspaceState.ERROR:
            self.last_error = reason
            self.last_error_at = self.updated_at
        else:
            self.last_error = None
            self.last_error_at = None

    def touch(self) -> None:
        """Update the session modification timestamp."""
        self.updated_at = datetime.now(UTC)

    # ------------------------------------------------------------------
    # Domain mutators
    # ------------------------------------------------------------------

    def add_papers(self, papers: list[Paper]) -> None:
        """
        Add retrieved scientific publications to the session.

        Papers are deduplicated by PMID (or DOI/URL as fallback). If
        the deduped result adds at least one new paper, the state is
        advanced to PAPERS_RETRIEVED if it was CREATED.

        Parameters
        ----------
        papers : list[Paper]
            Publications retrieved during literature search.
        """
        if not papers:
            return
        existing_ids = {
            self._paper_identity(p) for p in self.papers
        }
        new_papers = [
            p for p in papers if self._paper_identity(p) not in existing_ids
        ]
        if not new_papers:
            return
        self.papers.extend(new_papers)
        self.touch()
        if self.state is WorkspaceState.CREATED:
            self.force_state(
                WorkspaceState.PAPERS_RETRIEVED,
                reason="Papers added",
            )

    def replace_papers(
        self,
        papers: list[Paper],
        paper_sources: dict[str, str] | None = None,
    ) -> None:
        """
        Replace the session's paper collection (used by the
        orchestrator's SEARCH action). The state is forced to
        PAPERS_RETRIEVED if the new collection is non-empty; otherwise
        the state is forced back to CREATED.

        Parameters
        ----------
        papers : list[Paper]
            New paper collection.
        paper_sources : dict[str, str] | None
            Optional per-paper source attribution. Keys are
            paper identifiers (PMID → DOI → URL), values
            are ``SearchSource`` enum strings
            (``"pubmed"`` / ``"openalex"`` / ``"europe_pmc"``
            / ``"biorxiv"``). When supplied, replaces the
            existing ``paper_sources`` map; when ``None``,
            the map is cleared (the legacy single-source
            PubMed path passes ``None`` so the session
            reports no source attribution).
        """
        self.papers = list(papers)
        self.paper_sources = dict(paper_sources or {})
        self.touch()
        if papers:
            self.force_state(
                WorkspaceState.PAPERS_RETRIEVED,
                reason="Papers replaced",
            )
        else:
            self._force_state_regressive(
                WorkspaceState.CREATED,
                reason="No papers remaining",
            )

    def _force_state_regressive(
        self,
        new_state: WorkspaceState,
        *,
        reason: str | None = None,
    ) -> None:
        """
        Force a regressive state transition that the FSM does not
        model as an action.

        This private helper is used for "go back" operations that
        are not user-driven actions: removing the last paper
        regresses the workspace to CREATED, and replacing papers
        with an empty collection has the same effect. These are
        not modelled as formal FSM transitions because the user
        did not invoke an action — they mutated the workspace's
        paper collection directly.

        Allowed regressive targets are :class:`WorkspaceState.CREATED`
        and :class:`WorkspaceState.PAPERS_RETRIEVED`. Any other
        target is rejected with :class:`IllegalWorkspaceActionError`.

        Parameters
        ----------
        new_state : WorkspaceState
            Target regressive state.

        reason : str | None
            Optional reason for the regression.
        """
        allowed_regressive = (
            WorkspaceState.CREATED,
            WorkspaceState.PAPERS_RETRIEVED,
        )
        if new_state not in allowed_regressive:
            raise IllegalWorkspaceActionError(
                current_state=self.state.value,
                action=f"force_regressive:{new_state.value}",
                allowed=[s.value for s in allowed_regressive],
            )
        if self.state is new_state:
            return
        self.state_history.append(
            StateTransition(
                from_state=self.state,
                to_state=new_state,
                action=None,
                reason=reason,
            )
        )
        self.state = new_state
        self.updated_at = datetime.now(UTC)
        self.last_error = None
        self.last_error_at = None

    def remove_paper(self, paper_id: str) -> bool:
        """
        Remove a paper from the workspace by PMID or DOI.

        Parameters
        ----------
        paper_id : str
            PMID or DOI of the paper to remove.

        Returns
        -------
        bool
            True if a paper was removed, False otherwise.
        """
        target = paper_id.strip()
        if not target:
            return False
        before = len(self.papers)
        self.papers = [
            p for p in self.papers
            if p.pmid != target and p.doi != target
        ]
        removed = len(self.papers) < before
        if removed:
            self.touch()
            if not self.papers:
                # Removing the last paper regresses the workspace to
                # CREATED. This is a legitimate degradation that the
                # FSM does not model as a transition (papers can be
                # removed directly without an action), so we use
                # _force_state_regressive to bypass the strict
                # forward-only guard.
                self._force_state_regressive(
                    WorkspaceState.CREATED,
                    reason="Last paper removed",
                )
        return removed

    def set_summary(self, summary: Summary) -> None:
        """
        Store the synthesized evidence for this session.

        Parameters
        ----------
        summary : Summary
            AI-generated synthesis of the retrieved literature.
        """
        self.summary = summary
        self.touch()

    def set_report(self, report: ResearchReport) -> None:
        """
        Store the final research report.

        Parameters
        ----------
        report : ResearchReport
            Structured biomedical research report.
        """
        self.report = report
        self.touch()

    def set_published_report(self, published_report: "PublishedReport") -> None:
        """
        Store the rendered PDF for this workspace.

        Called by the orchestrator's ``publish_report()`` after the
        PDF has been generated. Replacing an existing publication
        is allowed -- a re-publish overwrites the previous artefact.

        Parameters
        ----------
        published_report : PublishedReport
            The PDF bytes plus the metadata needed to serve them.
        """
        self.published_report = published_report
        self.touch()

    def add_note(self, note: str) -> None:
        """
        Append a researcher annotation to the session.

        Parameters
        ----------
        note : str
            Free-text note recorded during the investigation.
        """
        if note.strip():
            self.notes.append(note)
            self.touch()

    @staticmethod
    def _paper_identity(paper: Paper) -> str:
        """
        Return a stable identity for a paper.

        PMID is preferred; DOI is the fallback; title is the last
        resort. The returned string is used for deduplication.
        """
        if paper.pmid:
            return f"pmid:{paper.pmid}"
        if paper.doi:
            return f"doi:{paper.doi}"
        return f"title:{paper.title.strip().lower()}"
