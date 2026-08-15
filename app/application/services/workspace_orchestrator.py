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

from app.application.use_cases.compare_evidence import CompareEvidenceUseCase
from app.application.use_cases.generate_report import GenerateReportUseCase
from app.application.use_cases.search_literature import SearchLiteratureUseCase
from app.application.use_cases.summarize_papers import SummarizePapersUseCase
from app.core.enums.workspace_state import (
    WorkspaceAction,
    WorkspaceState,
    allowed_actions,
    next_state,
)
from app.core.exceptions import IllegalWorkspaceActionError
from app.domain.entities.evidence_comparison import EvidenceComparison
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.research_session import ResearchSession
from app.domain.entities.summary import Summary
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.interfaces.literature_searcher import LiteratureSearcher
from app.domain.interfaces.report_generator import ReportGenerator
from app.domain.interfaces.workspace_repository import WorkspaceRepository


logger = logging.getLogger(__name__)


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

    comparison_generator : ComparisonGenerator
        Generator used by the COMPARE action.
    """

    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        literature_searcher: LiteratureSearcher,
        llm_provider: LLMProvider,
        report_generator: ReportGenerator,
        comparison_generator: "ComparisonGenerator",
    ) -> None:
        self._repository = workspace_repository
        self._literature_searcher = literature_searcher
        self._report_generator = report_generator
        self._comparison_generator = comparison_generator

        # Use cases are constructed here (composition root concern
        # delegated to the orchestrator for ergonomics) so callers
        # don't need to wire them separately.
        self._search_use_case = SearchLiteratureUseCase(
            literature_searcher=literature_searcher,
        )
        self._summarize_use_case = SummarizePapersUseCase(
            llm_provider=llm_provider,
        )
        self._compare_use_case = CompareEvidenceUseCase(
            comparison_generator=comparison_generator,
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
        Run the SUMMARIZE action.

        The workspace is advanced to SUMMARIZING, the summarisation
        use case is executed against the workspace's current papers,
        and the result is stored. The final state is SUMMARIZED on
        success or ERROR on failure.

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
        self._enter_action(session, WorkspaceAction.SUMMARIZE)

        try:
            summary = self._summarize_use_case.execute(
                session.question,
                session.papers,
            )
        except Exception as exc:
            logger.exception(
                "SUMMARIZE failed for workspace %s", workspace_id
            )
            self._fail(session, exc)
            raise

        session.set_summary(summary)
        session.force_state(
            WorkspaceState.SUMMARIZED,
            reason="Summary generated",
        )
        return self._repository.update(session)

    def compare(self, workspace_id: UUID) -> ResearchSession:
        """
        Run the COMPARE action.

        The workspace is advanced to COMPARING, the cross-paper
        comparison use case is executed against the workspace's
        current papers, and the validated result is stored. The
        final state is COMPARED on success or ERROR on failure.

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
        self._enter_action(session, WorkspaceAction.COMPARE)

        try:
            comparison: EvidenceComparison = self._compare_use_case.execute(
                session.question,
                session.papers,
            )
        except Exception as exc:
            logger.exception("COMPARE failed for workspace %s", workspace_id)
            self._fail(session, exc)
            raise

        session.set_evidence_comparison(comparison)
        session.force_state(
            WorkspaceState.COMPARED,
            reason="Comparison validated",
        )
        return self._repository.update(session)

    def report(self, workspace_id: UUID) -> ResearchSession:
        """
        Run the REPORT action.

        The workspace is advanced to REPORTING, the report generation
        use case is executed using the workspace's papers and
        summary, and the result is stored. The final state is
        REPORTED on success or ERROR on failure.

        This is the action that fixes the original bug. The report
        is generated from the workspace's *current* papers, not
        from a fresh PubMed search.

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
        if session.summary is None:
            raise IllegalWorkspaceActionError(
                current_state=session.state.value,
                action=WorkspaceAction.REPORT.value,
                allowed=[a.value for a in allowed_actions(session.state)],
            )
        self._enter_action(session, WorkspaceAction.REPORT)

        try:
            report = self._generate_report_use_case.execute(
                session.question,
                session.summary,
            )
        except Exception as exc:
            logger.exception("REPORT failed for workspace %s", workspace_id)
            self._fail(session, exc)
            raise

        session.set_report(report)
        session.force_state(
            WorkspaceState.REPORTED,
            reason="Report generated",
        )
        return self._repository.update(session)

    def complete(self, workspace_id: UUID) -> ResearchSession:
        """
        Mark the workspace as COMPLETED.

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
        session.transition_to(WorkspaceAction.COMPLETE)
        return self._repository.update(session)

    def retry(self, workspace_id: UUID) -> ResearchSession:
        """
        Recover a workspace from the ERROR state.

        The RETRY action moves the workspace back to the previous
        state recorded in the state history.

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
        session.transition_to(WorkspaceAction.RETRY)
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
        the action's result (e.g. papers, summary, comparison).
        """
        session.transition_to(action)

    def _fail(self, session: ResearchSession, exc: Exception) -> None:
        """
        Move the session to ERROR with the exception's message.

        The repository is updated so the failure is persisted.
        """
        try:
            session.force_state(
                WorkspaceState.ERROR,
                reason=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._repository.update(session)
