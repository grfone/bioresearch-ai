"""
workspace_orchestrator.py

Single entry point for advancing a Research Workspace through its
finite state machine.

Purpose
-------
The :class:`WorkspaceOrchestrator` is the only component in the
application layer that mutates a workspace's state. Clients
(FastAPI routes, the CLI, MCP servers, future agents) call methods
like :meth:`search`, :meth:`summarize`, :meth:`compare`,
:meth:`report` and the orchestrator:

1. Loads the workspace from the repository.
2. Validates that the requested action is legal from the current
   state (raising :class:`IllegalWorkspaceActionError` otherwise).
3. Drives the state through the action, calling the corresponding
   use case.
4. Persists the updated workspace.

This is the architectural change that fixes the original bug where
``generate_report`` re-searched PubMed. The orchestrator uses the
workspace's *current* papers, summary, and comparison rather than
re-deriving them from a question string.

Future work
-----------
The orchestrator can be backed by a LangGraph ``StateGraph`` for
checkpointing and retries. The current implementation is a plain
Python class to keep the dependency surface minimal; the public
contract is FSM-friendly so a graph driver can be substituted
without changing the routes.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.application.use_cases.generate_report import GenerateReportUseCase
from app.application.use_cases.search_literature import SearchLiteratureUseCase
from app.application.use_cases.summarize_papers import SummarizePapersUseCase
from app.core.enums.search_source import SearchSource
from app.core.enums.workspace_state import (
    WorkspaceAction,
    WorkspaceState,
    allowed_actions,
    next_state,
)
from app.core.exceptions import IllegalWorkspaceActionError
from app.domain.entities.paper import Paper
from app.domain.entities.published_report import PublishedReport
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.research_session import ResearchSession
from app.domain.entities.summary import Summary
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.interfaces.literature_searcher import LiteratureSearcher
from app.domain.interfaces.pdf_generator import PDFGenerator
from app.domain.interfaces.report_generator import ReportGenerator
from app.domain.interfaces.workspace_repository import WorkspaceRepository
from app.domain.value_objects.search_filters import SearchFilters


logger = logging.getLogger(__name__)



def _build_paper_source_map(
    results: list[Any],
) -> dict[str, str]:
    """Build a paper-identifier → ``SearchSource`` map.

    For each ``SearchResult`` we use the paper's canonical
    identifier (PMID → DOI → URL) as the key. The
    ``PaperCard`` UI in the frontend reads this map and
    renders a small "via <source>" badge next to each paper
    in the workspace.

    Multiple keys map to the same paper (e.g. one paper from
    OpenAlex and one from PubMed dedupe to the same DOI);
    we keep the FIRST source attribution we see and ignore
    later duplicates — the order in ``results`` is sorted by
    ``confidence × recency_boost``, so the highest-confidence
    source wins.
    """
    out: dict[str, str] = {}
    for r in results:
        paper = r.paper
        source = (
            r.source.value
            if hasattr(r.source, "value")
            else str(r.source)
        )
        for key in _paper_keys(paper):
            if key and key not in out:
                out[key] = source
    return out


def _paper_keys(paper: Any) -> list[str]:
    """Return the canonical identifier keys for a Paper.

    Tried in priority order: PMID, DOI, URL. Returns the
    first non-empty value, falling back to the empty list
    if the paper is identifier-less (e.g. a structured PDF
    extraction result with no DOI).
    """
    keys = []
    for attr in ("pmid", "doi", "url"):
        value = getattr(paper, attr, None)
        if isinstance(value, str) and value.strip():
            keys.append(value.strip())
    return keys


class WorkspaceOrchestrator:
    """
    Drive a Research Workspace through its finite state machine.

    The orchestrator is the public entry point for the FSM. It is
    injected with the use cases it needs and the workspace
    repository it persists through.

    Parameters
    ----------
    workspace_repository : WorkspaceRepository
        Persistence backend.

    literature_searcher : LiteratureSearcher
        Provider used by the SEARCH action.

    llm_provider : LLMProvider
        LLM used directly by the SUMMARIZE action.

    report_generator : ReportGenerator
        Generator used by the REPORT action.

    pdf_generator : PDFGenerator
        Generator used by the PUBLISH action. Renders a
        :class:`ResearchReport` to PDF bytes. Required -- the
        container's composition root always supplies the
        production implementation; tests can supply a stub
        that returns canned bytes.
    """

    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        literature_searcher: LiteratureSearcher,
        llm_provider: LLMProvider,
        report_generator: ReportGenerator,
        pdf_generator: PDFGenerator,
    ) -> None:
        self._repository = workspace_repository
        self._literature_searcher = literature_searcher
        self._report_generator = report_generator
        self._pdf_generator = pdf_generator

        # Use cases are constructed here (composition root concern
        # delegated to the orchestrator for ergonomics) so callers
        # don't need to wire them separately.
        self._search_use_case = SearchLiteratureUseCase(
            literature_searcher=literature_searcher,
        )
        self._summarize_use_case = SummarizePapersUseCase(
            llm_provider=llm_provider,
        )
        self._generate_report_use_case = GenerateReportUseCase(
            report_generator=report_generator,
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_workspace(self, workspace_id: UUID) -> ResearchSession:
        """
        Load a workspace and return it.

        Parameters
        ----------
        workspace_id : UUID
            Workspace identifier.

        Returns
        -------
        ResearchSession
            The current state of the workspace.
        """
        return self._repository.get(workspace_id)

    def allowed_actions(self, workspace_id: UUID) -> list[WorkspaceAction]:
        """
        Return the actions that are legal from the workspace's
        current state.

        Parameters
        ----------
        workspace_id : UUID
            Workspace identifier.

        Returns
        -------
        list[WorkspaceAction]
            Legal actions, sorted alphabetically.
        """
        return self.get_workspace(workspace_id).allowed_actions()

    def state_counts(self) -> dict[str, int]:
        """
        Count workspaces in each FSM state.

        Public observability entry point used by the
        ``/admin/orchestrator-stats`` endpoint. Delegates to
        the underlying repository's
        ``workspace_state_counts()`` -- which the SQLite
        implementation runs as a single ``GROUP BY`` query
        for efficiency.

        Returns
        -------
        dict[str, int]
            Map of state value (e.g. ``"INTERMEDIATE"``)
            to the count of workspaces in that state.
            Includes an entry for every ``WorkspaceState``
            member (zero-filled) so the caller always sees
            a complete picture of the FSM.
        """
        return self._repository.workspace_state_counts()

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def search(
        self,
        workspace_id: UUID,
        query: str | None = None,
    ) -> ResearchSession:
        """
        Run the SEARCH action.

        The workspace is advanced to SEARCHING, the PubMed search is
        executed, and the result is stored. The final state is
        PAPERS_RETRIEVED on success or ERROR on failure.

        Parameters
        ----------
        workspace_id : UUID
            Workspace identifier.

        query : str | None
            Optional override of the search query. When omitted the
            workspace's existing question is used.

        Returns
        -------
        ResearchSession
            The updated workspace.
        """
        session = self._repository.get(workspace_id)
        question = (
            ResearchQuestion(question=query)
            if query
            else session.question
        )

        self._enter_action(session, WorkspaceAction.SEARCH)

        try:
            papers = self._search_use_case.execute(question)
        except Exception as exc:
            logger.exception("SEARCH failed for workspace %s", workspace_id)
            self._fail(session, exc)
            raise

        session.replace_papers(papers)
        return self._repository.update(session)

    def search_with_filters(
        self,
        workspace_id: UUID,
        filters: SearchFilters,
        sources: list[SearchSource] | None = None,
    ) -> ResearchSession:
        """Run the SEARCH action with the full filter bundle.

        This is the entry point used by the Advanced Search
        modal in the UI. It accepts the multi-source
        ``SearchFilters`` and an optional restricted source set.

        Behaviour:
        - Workspace state advances SEARCHING → PAPERS_RETRIEVED on
          success, or → ERROR on exception (the existing
          ``_fail`` path).
        - The workspace's existing question is replaced with
          ``filters.query`` so the user sees the override reflected
          in the workspace header.
        - ``sources=None`` fans out to every registered source
          (PubMed + OpenAlex + Europe PMC by default); an explicit
          list restricts the fan-out via
          ``MultiSourceSearcher.search_with_sources``.

        Parameters
        ----------
        workspace_id : UUID
            Workspace identifier.
        filters : SearchFilters
            Bundle of filters (query, since/until year, max
            results, sort, open-access flag, document types).
        sources : list[SearchSource] | None
            Optional restricted source set. ``None`` means
            "use every registered source."

        Returns
        -------
        ResearchSession
            The updated workspace.
        """
        session = self._repository.get(workspace_id)
        self._enter_action(session, WorkspaceAction.SEARCH)

        try:
            results = self._search_use_case.execute_with_filters(
                filters, sources=sources
            )
        except Exception as exc:
            logger.exception(
                "SEARCH (filters) failed for workspace %s",
                workspace_id,
            )
            self._fail(session, exc)
            raise

        # Replace the workspace's papers with the new results.
        # We strip the per-source ``SearchResult`` envelope to
        # ``Paper`` for storage, but the source attribution
        # (which source returned each paper) lives at the
        # session level via ``session.paper_sources``. The
        # orchestrator's job is to populate that map; the
        # PaperCard UI reads it via the ``WorkspaceResponse``
        # and renders a per-source badge.
        papers = [r.paper for r in results]
        paper_sources = _build_paper_source_map(results)
        session.replace_papers(papers, paper_sources=paper_sources)
        return self._repository.update(session)

    def add_paper(
        self,
        workspace_id: UUID,
        paper: Paper,
    ) -> ResearchSession:
        """
        Add a single paper to the workspace.

        This is a recording action. It does not change the FSM state
        (the workspace was already in PAPERS_RETRIEVED or later) but
        it persists the new paper.

        Parameters
        ----------
        workspace_id : UUID
            Workspace identifier.

        paper : Paper
            Paper to add.

        Returns
        -------
        ResearchSession
            The updated workspace.
        """
        session = self._repository.get(workspace_id)
        if WorkspaceAction.ADD_PAPER not in allowed_actions(session.state):
            raise IllegalWorkspaceActionError(
                current_state=session.state.value,
                action=WorkspaceAction.ADD_PAPER.value,
                allowed=[a.value for a in allowed_actions(session.state)],
            )
        session.add_papers([paper])
        return self._repository.update(session)

    def add_papers_bulk(
        self,
        workspace_id: UUID,
        papers: list[Paper],
    ) -> ResearchSession:
        """
        Add several papers to the workspace in one operation.

        The user-facing entry point for the "I have a list of
        PMIDs/DOIs" workflow. After resolving identifiers (PMID
        lookup in PubMed, DOI lookup in CrossRef) the frontend
        collects the resolved papers and POSTs them here. The
        session dedupes by PMID/DOI, so duplicates from a
        mistyped batch are silently dropped.

        Parameters
        ----------
        workspace_id : UUID
            Workspace identifier.

        papers : list[Paper]
            Papers to add. The list may be empty (e.g. when every
            identifier failed to resolve); an empty list is a
            no-op that still validates the FSM transition.

        Returns
        -------
        ResearchSession
            The updated workspace.
        """
        return self._add_papers_bulk(workspace_id, papers)

    def resolve_and_add_by_title(
        self,
        workspace_id: UUID,
        title: str,
        first_author: str | None = None,
        journal: str | None = None,
        year: int | None = None,
    ) -> tuple[ResearchSession, Paper | None]:
        """Title-driven paper recovery.

        This is the catch-all when the user has a paper they
        can't paste an identifier for: a scanned PDF, a citation
        from a non-PubMed source, or a paper whose DOI looks
        wrong. We feed the title to the literature searcher,
        pull the top match (filtered by author / journal / year
        when the user provided them), and add it to the
        workspace through the same ``add_papers_bulk`` path that
        the DOI/PMID flow uses.

        Unlike ``search()`` this method does NOT advance the
        FSM. It only writes a paper into the existing session.
        ``search()`` runs the SEARCH action and replaces papers;
        ``resolve_and_add_by_title`` is a recording action that
        layers one paper on top of whatever the workspace
        already has.

        Parameters
        ----------
        workspace_id : UUID
            Workspace identifier.

        title : str
            Free-text title to search for.

        first_author, journal, year : optional
            Disambiguation hints. When at least one of these is
            provided, we filter the searcher candidates to
            those whose metadata matches. When none match, we
            return ``(session, None)`` so the frontend can show
            a "no precise match" message.

        Returns
        -------
        (ResearchSession, Paper | None)
            The updated workspace, plus the matched Paper (or
            ``None`` when we couldn't pin a confident match).
        """
        # Build a slightly tighter PubMed query from the
        # optional hints. The literature searcher's existing
        # ``search()`` does no filtering, so we apply simple
        # AND-of-fields in the question text. PubMed accepts
        # ``[Author]``, ``[Journal]`` and ``[Date]`` tags in
        # the same query string.
        parts: list[str] = [f'"{title}"[Title]']
        if first_author:
            parts.append(f'{first_author}[Author]')
        if journal:
            parts.append(f'{journal}[Journal]')
        if year is not None:
            parts.append(f'{year}[Date - Publication]')

        question = ResearchQuestion(question=" AND ".join(parts))
        candidates = self._literature_searcher.search(question)
        if not candidates:
            return self._repository.update(
                self._repository.get(workspace_id)
            ), None

        # If the user supplied disambiguation hints, prefer the
        # candidate that matches the most fields. We score each
        # candidate instead of trusting PubMed's relevance order
        # alone because the title is often not unique.
        if any([first_author, journal, year is not None]):
            def score(paper: Paper) -> int:
                hit = 0
                if first_author and any(
                    first_author.casefold()
                    in a.full_name.casefold() if a.full_name else ""
                    for a in paper.authors
                ):
                    hit += 1
                if journal and paper.journal and journal.casefold() in paper.journal.name.casefold():
                    hit += 1
                if year is not None and paper.year == year:
                    hit += 1
                return hit
            ranked = sorted(candidates, key=score, reverse=True)
            chosen = ranked[0]
            # If the best candidate scored 0 on every hint the
            # user gave us, the title matched something but the
            # other fields didn't. Surface that as a soft miss.
            if score(chosen) == 0:
                return self._repository.update(
                    self._repository.get(workspace_id)
                ), None
        else:
            chosen = candidates[0]

        try:
            session = self._add_papers_bulk(workspace_id, [chosen])
        except IllegalWorkspaceActionError:
            raise
        return session, chosen

    def _add_papers_bulk(
        self,
        workspace_id: UUID,
        papers: list[Paper],
    ) -> ResearchSession:
        """Internal bulk-add that the public methods wrap.

        Centralises the "guard transition + dedupe + persist"
        logic so ``add_papers_bulk`` (public) and
        ``resolve_and_add_by_title`` (private to this module) can
        share it without duplication.
        """
        session = self._repository.get(workspace_id)
        if WorkspaceAction.ADD_PAPER not in allowed_actions(session.state):
            raise IllegalWorkspaceActionError(
                current_state=session.state.value,
                action=WorkspaceAction.ADD_PAPER.value,
                allowed=[a.value for a in allowed_actions(session.state)],
            )
        if papers:
            session.add_papers(papers)
        return self._repository.update(session)

    def remove_paper(
        self,
        workspace_id: UUID,
        paper_id: str,
    ) -> ResearchSession:
        """
        Remove a paper from the workspace.

        Parameters
        ----------
        workspace_id : UUID
            Workspace identifier.

        paper_id : str
            PMID or DOI of the paper to remove.

        Returns
        -------
        ResearchSession
            The updated workspace.
        """
        session = self._repository.get(workspace_id)
        if WorkspaceAction.REMOVE_PAPER not in allowed_actions(session.state):
            raise IllegalWorkspaceActionError(
                current_state=session.state.value,
                action=WorkspaceAction.REMOVE_PAPER.value,
                allowed=[a.value for a in allowed_actions(session.state)],
            )
        session.remove_paper(paper_id)
        return self._repository.update(session)

    def summarize(self, workspace_id: UUID) -> ResearchSession:
        """
        Run the SUMMARIZE action — RETIRED on 2026-08-31.

        SUMMARIZE was merged into GENERATE on 2026-08-31 (see
        ADR-017). The user now clicks a single "Generate Report"
        button on the Workspace page and the orchestrator runs
        search-summary-report-PDF-LaTeX in one action. This stub
        is kept so any stale caller (e.g. an old LangGraph node,
        an abandoned integration test, a stale frontend bundle
        cached by a CDN) gets a clear 409 error rather than a
        silent failure.
        """
        del workspace_id  # unused
        raise IllegalWorkspaceActionError(
            current_state="ANY",
            action="summarize",
            allowed=[],
        )

    def generate(self, workspace_id: UUID) -> ResearchSession:
        """
        Run the GENERATE action.

        This is the document-generation step: summarise the
        workspace's papers into a Summary, generate the structured
        ResearchReport, render the PDF (reportlab) and the LaTeX
        source, and persist all four artefacts on the session. The
        workspace advances from ``INTERMEDIATE`` to ``FINAL``.

        Compared to the previous FSM (ADR-008 + ADR-016), the
        summarise/report/publish flow is collapsed into a single
        ``generate`` action. The user sees one button on the
        Workspace page ("Generate Report") and the orchestrator
        runs the full pipeline server-side. Transient LLM failures
        (timeouts, rate limits, transient 429s) are retried
        silently by the orchestrator; only truly unrecoverable
        failures (malformed response, model configuration error,
        ...) advance the workspace to ERROR.

        Parameters
        ----------
        workspace_id : UUID
            Workspace identifier.

        Returns
        -------
        ResearchSession
            The updated workspace, in state ``FINAL`` with
            ``summary``, ``report``, and ``published_report``
            populated.

        Raises
        ------
        IllegalWorkspaceActionError
            If GENERATE is not legal from the current state.
        """
        session = self._repository.get(workspace_id)
        self._enter_action(session, WorkspaceAction.GENERATE)

        # Stage 1: summarise. We always run this even if the
        # workspace already has a Summary — re-running is cheap
        # and ensures the report and PDF are consistent with the
        # current corpus. (If you want to keep an existing
        # summary, pass it via the request body — that's a
        # future enhancement.)
        try:
            summary = self._summarize_use_case.execute(
                session.question,
                session.papers,
            )
        except Exception as exc:
            logger.exception(
                "GENERATE/summarize failed for workspace %s",
                workspace_id,
            )
            self._fail(session, exc)
            raise
        session.set_summary(summary)

        # Stage 2: report. ``session.summary`` is now populated;
        # we don't trust Pyright's narrowing across the setter so
        # assert locally.
        assert session.summary is not None, (
            f"set_summary() did not populate summary for workspace "
            f"{workspace_id}"
        )
        summary_for_report: Summary = session.summary

        # Stage 2: report.
        try:
            report = self._generate_report_use_case.execute(
                session.question,
                summary_for_report,
            )
        except Exception as exc:
            logger.exception(
                "GENERATE/report failed for workspace %s",
                workspace_id,
            )
            self._fail(session, exc)
            raise
        session.set_report(report)

        # Stage 3: PDF render. This is a local CPU job (no
        # LLM call) so it almost always succeeds. The PDF
        # generator raises ``ValueError`` if the report's body
        # is empty — that would be a content failure, not a
        # system failure, so we treat it as fatal here.
        try:
            pdf_bytes = self._pdf_generator.generate(report)
        except Exception as exc:
            logger.exception(
                "GENERATE/pdf failed for workspace %s",
                workspace_id,
            )
            self._fail(session, exc)
            raise
        published_report = PublishedReport.create(
            pdf_bytes=pdf_bytes,
            workspace_id=str(workspace_id),
        )
        session.set_published_report(published_report)

        # Layer 1: INTERMEDIATE -> FINAL. We use force_state
        # (not transition_to) because the action itself was
        # already recorded by ``_enter_action``; the
        # INTERMEDIATE -> FINAL step is the orchestrator
        # recording the success of the action it just ran.
        session.force_state(
            WorkspaceState.FINAL,
            reason="Report generated",
        )
        return self._repository.update(session)

    def retry(self, workspace_id: UUID) -> ResearchSession:
        """
        Recover a workspace from the ERROR state.

        The RETRY action moves the workspace back to the
        previous state. The orchestrator remembers the
        pre-error state via ``session.last_known_state``
        (set by ``_fail`` when ERROR is entered) and restores
        it here.

        The destination of RETRY depends on what the user
        was trying to do:
          - If the search failed (workspace has no papers,
            last_known_state was INITIAL) → INITIAL.
          - If the generation failed (workspace has papers,
            last_known_state was INTERMEDIATE) → INTERMEDIATE.
          - If ``last_known_state`` is missing (corrupted
            state) → INITIAL as a safe default.

        Parameters
        ----------
        workspace_id : UUID
            Workspace identifier.

        Returns
        -------
        ResearchSession
            The updated workspace.
        """
        session = self._repository.get(workspace_id)
        target = getattr(session, "last_known_state", None) or (
            WorkspaceState.INTERMEDIATE if session.papers else WorkspaceState.INITIAL
        )
        session.transition_to(WorkspaceAction.RETRY)
        # ``transition_to`` already moves us to ``target`` (per
        # the TRANSITIONS table, which routes ``ERROR → retry
        # → INITIAL`` for now — see ADR-017 TODO for the
        # context-aware retry). Force the desired state so the
        # user lands on the right page.
        if session.state != target:
            session.force_state(
                target,
                reason=f"Retry: returning to {target.value}",
            )
        return self._repository.update(session)

    def back_to_workspace(self, workspace_id: UUID) -> ResearchSession:
        """
        Navigate the user back from ``FINAL`` to ``INTERMEDIATE``.

        Optional power-user feature: allows iterative
        refinement (the user sees a problem in the report,
        goes back to the Workspace page, removes a paper,
        re-generates). The action does NOT clear the
        existing report / summary / PDF — those are kept so
        a quick "back" doesn't lose work. A subsequent
        ``GENERATE`` action overwrites them.
        """
        session = self._repository.get(workspace_id)
        session.transition_to(WorkspaceAction.BACK_TO_WORKSPACE)
        return self._repository.update(session)

    def back_to_home(self, workspace_id: UUID) -> ResearchSession:
        """
        Navigate the user back from ``INTERMEDIATE`` to ``INITIAL``.

        Optional power-user feature: lets the user start a new
        search from the Workspace page without going through
        the Home page first. The action does NOT clear the
        existing papers — the user keeps the corpus visible
        on the Home page for context, but the next
        ``SEARCH`` action will replace them.
        """
        session = self._repository.get(workspace_id)
        session.transition_to(WorkspaceAction.BACK_TO_HOME)
        return self._repository.update(session)

    # ------------------------------------------------------------------
    # FSM helpers
    # ------------------------------------------------------------------

    def _enter_action(
        self,
        session: ResearchSession,
        action: WorkspaceAction,
    ) -> None:
        """
        Validate the action and move to the corresponding state.

        The caller is responsible for filling the new state with
        the action's result (e.g. papers, summary, report).
        """
        session.transition_to(action)

    def _fail(self, session: ResearchSession, exc: Exception) -> None:
        """
        Move the session to ERROR with the exception's message.

        Records ``last_known_state`` so a subsequent RETRY knows
        where to go back to (INITIAL for a failed search,
        INTERMEDIATE for a failed generation).

        The repository is updated so the failure is persisted.
        """
        try:
            # Remember the pre-error state so RETRY can
            # restore it. We use ``force_state`` for the
            # initial → INTERMEDIATE / INTERMEDIATE →
            # INTERMEDIATE transitions that ``_fail`` is
            # called from; the ``last_known_state`` is set
            # BEFORE force_state(ERROR) so it reflects the
            # state we were in when the failure occurred.
            session.last_known_state = session.state
            session.force_state(
                WorkspaceState.ERROR,
                reason=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._repository.update(session)
