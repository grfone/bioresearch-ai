"""
research_assistant.py

High-level application facade for BioResearch AI.

Purpose
-------
This module defines the :class:`ResearchAssistant`, the primary public
interface of the BioResearch AI application.

The assistant implements the Facade pattern by exposing a stable,
application-level API while hiding internal use case organization.

All external clients should communicate through this class instead of
depending directly on individual application services or use cases.

Typical clients include:

- REST APIs
- Command-line interfaces
- Streamlit applications
- Jupyter notebooks
- MCP servers
- Agent-to-Agent systems
- LangGraph workflows
- Autonomous research agents

Current Responsibilities
------------------------

The assistant coordinates:

Research capabilities:

- Literature search.
- Evidence summarization.
- Report generation.

Workspace capabilities:

- Research session creation.
- Workspace retrieval.
- Workspace persistence.

Future capabilities may include:

- Multi-agent orchestration.
- Experiment recommendation.
- Literature comparison.
- Knowledge graphs.
- Biological database integration.
- Autonomous research planning.

Architecture
------------

                    Client
                      │
                      ▼
             ResearchAssistant
          ┌───────────┴───────────┐
          ▼                       ▼
 Literature Services       WorkspaceService
          │                       │
          ▼                       ▼
    Research Use Cases     Workspace Use Cases

The public interface of this class should remain stable while internal
implementation details evolve.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.application.services.workspace_service import WorkspaceService

from app.application.use_cases.generate_report import GenerateReportUseCase
from app.application.use_cases.search_literature import SearchLiteratureUseCase
from app.application.use_cases.summarize_papers import SummarizePapersUseCase

from app.domain.entities.paper import Paper
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.research_session import ResearchSession
from app.domain.entities.summary import Summary


class ResearchAssistant:
    """
    Public application facade for BioResearch AI.

    This class provides the main entry point for all application clients.

    It coordinates research workflows and delegates workspace lifecycle
    management to :class:`WorkspaceService`.

    Parameters
    ----------
    search_use_case
        Retrieves scientific literature.

    summarize_use_case
        Synthesizes evidence from scientific publications.

    report_use_case
        Generates structured biomedical reports.

    workspace_service
        Coordinates research workspace lifecycle operations.
    """

    def __init__(
        self,
        search_use_case: SearchLiteratureUseCase,
        summarize_use_case: SummarizePapersUseCase,
        report_use_case: GenerateReportUseCase,
        workspace_service: WorkspaceService,
    ) -> None:
        """
        Initialize the ResearchAssistant.

        Parameters
        ----------
        search_use_case
            Configured literature search use case.

        summarize_use_case
            Configured summarization use case.

        report_use_case
            Configured report generation use case.

        workspace_service
            Configured workspace management service.
        """

        self._search_use_case = search_use_case
        self._summarize_use_case = summarize_use_case
        self._report_use_case = report_use_case
        self._workspace_service = workspace_service

    # ------------------------------------------------------------------
    # Workspace capabilities
    # ------------------------------------------------------------------

    def create_workspace(
        self,
        question: str,
    ) -> ResearchSession:
        """
        Create a new research workspace.

        Parameters
        ----------
        question
            Initial biomedical research question.

        Returns
        -------
        ResearchSession
            Newly created research session.
        """

        return self._workspace_service.create_workspace(
            question
        )

    def get_workspace(
        self,
        workspace_id,
    ) -> ResearchSession:
        """
        Retrieve an existing research workspace.

        Parameters
        ----------
        workspace_id
            UUID identifying the research session.

        Returns
        -------
        ResearchSession
            Retrieved research session.
        """

        return self._workspace_service.get_workspace(
            workspace_id
        )

    def update_workspace(
        self,
        workspace: ResearchSession,
    ) -> ResearchSession:
        """
        Persist modifications made to a research workspace.

        Parameters
        ----------
        workspace
            Updated research session.

        Returns
        -------
        ResearchSession
            Persisted research session.
        """

        return self._workspace_service.update_workspace(
            workspace
        )

    # ------------------------------------------------------------------
    # Literature capabilities
    # ------------------------------------------------------------------

    def search_papers(
        self,
        question: str,
    ) -> list[Paper]:
        """
        Search biomedical literature.
        """

        research_question = self._build_question(question)

        return self._search_use_case.execute(
            research_question
        )

    def summarize(
        self,
        question: str,
    ) -> Summary:
        """
        Generate an evidence summary.
        """

        research_question = self._build_question(question)

        papers = self.search_papers(question)

        return self._summarize_use_case.execute(
            research_question,
            papers,
        )

    def generate_report(
        self,
        question: str,
    ) -> ResearchReport:
        """
        Generate a structured biomedical research report.
        """

        research_question = self._build_question(question)

        summary = self.summarize(question)

        return self._report_use_case.execute(
            research_question,
            summary,
        )

    def research(
        self,
        question: str,
    ) -> ResearchReport:
        """
        Execute the complete research workflow.

        Workflow:

        1. Retrieve literature.
        2. Synthesize evidence.
        3. Generate final report.

        Parameters
        ----------
        question
            Biomedical research question.

        Returns
        -------
        ResearchReport
            Generated research report.
        """

        return self.generate_report(
            question
        )

    @staticmethod
    def _build_question(
        question: str,
    ):
        """
        Validate and create a ResearchQuestion entity.

        Parameters
        ----------
        question
            User supplied research question.

        Returns
        -------
        ResearchQuestion
            Validated research question.
        """

        from app.domain.entities.research_question import ResearchQuestion

        question = question.strip()

        if not question:
            raise ValueError(
                "Research question cannot be empty."
            )

        return ResearchQuestion(
            question=question
        )