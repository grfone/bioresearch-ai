"""
container.py

Application composition root for BioResearch AI.

Purpose
-------
This module assembles the complete dependency graph of the BioResearch AI
application.

Following Clean Architecture principles, this module is the only location
where concrete infrastructure implementations are created.

All application services and use cases receive their dependencies through
constructor injection.

Responsibilities
----------------
- Configure infrastructure dependencies.
- Configure repositories.
- Configure LLM providers.
- Configure domain adapters.
- Instantiate application use cases.
- Compose application services.
- Build the ResearchAssistant facade.

Architecture
------------

                         ResearchAssistant
                                  |
        ------------------------------------------------
        |                                              |
 Research Capabilities                         WorkspaceService
        |                                              |
 ------------------------------------------------      |
 |              |              |                        |
Search UC   Summary UC    Report UC             Workspace Use Cases
 |              |              |                        |
PubMed       LLM        ReportGenerator         WorkspaceRepository
Provider   Provider          |                        |
                              |                        |
                       LLMReportGenerator              |
                              |                        |
                -------------------------              |
                |                       |              |
          LLMProvider            ReportMapper         |
                |                       |              |
                v                       v              v
             LLM API             ResearchReport   Sqlite Storage


Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations


from app.application.services.research_assistant import (
    ResearchAssistant,
)

from app.application.services.workspace_service import (
    WorkspaceService,
)


from app.application.use_cases.search_literature import (
    SearchLiteratureUseCase,
)

from app.application.use_cases.summarize_papers import (
    SummarizePapersUseCase,
)

from app.application.use_cases.generate_report import (
    GenerateReportUseCase,
)


from app.application.use_cases.create_workspace import (
    CreateWorkspaceUseCase,
)

from app.application.use_cases.get_workspace import (
    GetWorkspaceUseCase,
)

from app.application.use_cases.update_workspace import (
    UpdateWorkspaceUseCase,
)


from app.infrastructure.storage.sqlite_workspace_repository import (
    SqliteWorkspaceRepository,
)


from app.infrastructure.pubmed.client import PubMedClient
from app.infrastructure.pubmed.provider import PubMedProvider


from app.infrastructure.llm.llm_factory import (
    LLMFactory,
)

from app.infrastructure.llm.report_generator import (
    LLMReportGenerator,
)


from app.infrastructure.llm.report_mapper import (
    ReportMapper,
)


from app.config.settings import settings
from app.core.enums.llm_provider import LLMProviderEnum



class Container:
    """
    Composition root for BioResearch AI.

    The container constructs the application's dependency graph.

    All concrete infrastructure implementations are created here and
    injected into application-level components.

    This keeps the application layer independent of:

    - databases;
    - external APIs;
    - LLM vendors;
    - storage engines.

    The container uses a singleton pattern for the workspace repository
    to ensure all use cases share the same persistent storage instance.

    Attributes
    ----------
    _workspace_repository : SqliteWorkspaceRepository | None
        Cached singleton instance of the workspace repository.
    """

    _workspace_repository: SqliteWorkspaceRepository | None = None

    @classmethod
    def get_workspace_repository(cls) -> SqliteWorkspaceRepository:
        """
        Return the singleton workspace repository instance.

        The repository is created lazily on the first call and reused
        for all subsequent calls, ensuring all use cases share the same
        persistent storage.

        Returns
        -------
        SqliteWorkspaceRepository
            The shared SQLite repository instance.
        """
        if cls._workspace_repository is None:
            cls._workspace_repository = SqliteWorkspaceRepository(
                db_path="bioresearch.db"
            )
        # Assure the type checker that we never return None
        assert cls._workspace_repository is not None
        return cls._workspace_repository

    @classmethod
    def build(cls) -> ResearchAssistant:
        """
        Build and configure the BioResearch AI application.

        Returns
        -------
        ResearchAssistant
            Fully configured application facade.
        """

        # ==============================================================
        # Infrastructure: Literature Search
        # ==============================================================

        pubmed_client = PubMedClient(
            email=settings.pubmed.email,
            api_key=settings.pubmed.api_key,
        )

        literature_searcher = PubMedProvider(
            client=pubmed_client,
        )

        # ==============================================================
        # Infrastructure: LLM
        # ==============================================================

        llm_provider = LLMFactory.create(
            LLMProviderEnum(
                settings.llm.provider
            )
        )

        # ==============================================================
        # Infrastructure: Report Generation
        # ==============================================================

        report_mapper = ReportMapper()

        report_generator = LLMReportGenerator(
            llm_provider=llm_provider,
            report_mapper=report_mapper,
        )

        # ==============================================================
        # Infrastructure: Workspace Persistence (Singleton)
        # ==============================================================

        workspace_repository = cls.get_workspace_repository()

        # ==============================================================
        # Application Use Cases: Research Workflow
        # ==============================================================

        search_use_case = SearchLiteratureUseCase(
            literature_searcher=literature_searcher,
        )

        summarize_use_case = SummarizePapersUseCase(
            llm_provider=llm_provider,
        )

        generate_report_use_case = GenerateReportUseCase(
            report_generator=report_generator,
        )

        # ==============================================================
        # Application Use Cases: Workspace Lifecycle
        # ==============================================================

        create_workspace_use_case = CreateWorkspaceUseCase(
            workspace_repository=workspace_repository,
        )

        get_workspace_use_case = GetWorkspaceUseCase(
            workspace_repository=workspace_repository,
        )

        update_workspace_use_case = UpdateWorkspaceUseCase(
            workspace_repository=workspace_repository,
        )

        # ==============================================================
        # Application Services
        # ==============================================================

        workspace_service = WorkspaceService(
            create_workspace_use_case=create_workspace_use_case,
            get_workspace_use_case=get_workspace_use_case,
            update_workspace_use_case=update_workspace_use_case,
        )

        # ==============================================================
        # Application Facade
        # ==============================================================

        return ResearchAssistant(
            search_use_case=search_use_case,
            summarize_use_case=summarize_use_case,
            report_use_case=generate_report_use_case,
            workspace_service=workspace_service,
        )


# ----------------------------------------------------------------------
# FastAPI Dependency Provider
# ----------------------------------------------------------------------

_assistant: ResearchAssistant | None = None


def get_research_assistant() -> ResearchAssistant:
    """
    Provide the configured ResearchAssistant application facade.

    This function is used by FastAPI dependency injection to expose the
    application facade to API routes.

    The instance is created lazily on the first request and reused for
    subsequent requests.

    Returns
    -------
    ResearchAssistant
        Fully configured application facade.
    """

    global _assistant

    if _assistant is None:
        _assistant = Container.build()

    assert _assistant is not None

    return _assistant