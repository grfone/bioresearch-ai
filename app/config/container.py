"""
container.py

Application composition root for BioResearch AI.

Purpose
-------
This module assembles the complete dependency graph of the
BioResearch AI application.

Following Clean Architecture principles, this module is the only
location where concrete infrastructure implementations are created.

All application services and use cases receive their dependencies
through constructor injection.

Responsibilities
----------------
- Configure infrastructure dependencies.
- Configure repositories.
- Configure LLM providers.
- Configure domain adapters.
- Instantiate application use cases.
- Compose application services.
- Build the WorkspaceOrchestrator and ResearchAssistant facade.

Architecture
------------

                    ResearchAssistant
                             |
        -----------------------------
        |                           |
Literature Capabilities   WorkspaceOrchestrator
        |                           |
Use Cases (search, etc.)   Use Cases (compare, etc.)
        |                           |
PubMed / LLM / Storage      Persistence
                                 |
                          WorkspaceRepository

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from functools import lru_cache

from app.application.services.research_assistant import (
    ResearchAssistant,
)
from app.application.services.workspace_orchestrator import (
    WorkspaceOrchestrator,
)
from app.application.services.workspace_service import (
    WorkspaceService,
)

from app.application.use_cases.compare_evidence import (
    CompareEvidenceUseCase,
)
from app.application.use_cases.create_workspace import (
    CreateWorkspaceUseCase,
)
from app.application.use_cases.generate_report import (
    GenerateReportUseCase,
)
from app.application.use_cases.get_workspace import (
    GetWorkspaceUseCase,
)
from app.application.use_cases.search_literature import (
    SearchLiteratureUseCase,
)
from app.application.use_cases.summarize_papers import (
    SummarizePapersUseCase,
)
from app.application.use_cases.update_workspace import (
    UpdateWorkspaceUseCase,
)

from app.infrastructure.llm.comparison_generator import (
    LLMComparisonGenerator,
)
from app.infrastructure.llm.comparison_mapper import (
    EvidenceComparisonMapper,
)
from app.infrastructure.llm.llm_factory import (
    LLMFactory,
)
from app.infrastructure.llm.report_generator import (
    LLMReportGenerator,
)
from app.infrastructure.llm.report_mapper import (
    ReportMapper,
)
from app.infrastructure.pubmed.client import PubMedClient
from app.infrastructure.pubmed.identifier_resolver import (
    IdentifierResolver,
)
from app.infrastructure.pubmed.provider import PubMedProvider
from app.infrastructure.storage.sqlite_workspace_repository import (
    SqliteWorkspaceRepository,
)

from app.config.settings import settings

# Resolve the DATABASE_URL setting to a real on-disk path. The
# settings object exposes the URL as ``sqlite:///relative/path`` or
# ``sqlite:////absolute/path``. We convert that to a path string
# the SqliteWorkspaceRepository can open.
def _sqlite_path_from_settings() -> str:
    """Resolve the ``DATABASE_URL`` to an on-disk file path.

    The settings object exposes the URL as ``sqlite:///relative/path``
    (three slashes, relative) or ``sqlite:////absolute/path`` (four
    slashes, absolute — SQLAlchemy's convention). We strip the
    prefix to recover the file path that ``sqlite3.connect()`` can
    open.
    """
    url = settings.database.url
    # Absolute path: ``sqlite:////absolute/path`` — drop the
    # ``sqlite://`` prefix (9 chars) and keep the leading slash.
    if url.startswith("sqlite:////"):
        return url[len("sqlite://"):]
    # Relative path: ``sqlite:///relative/path`` — drop the host
    # part (the empty segment between ``://`` and the third slash).
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    # Plain ``sqlite://path`` (no host/relative marker) — drop
    # the prefix.
    if url.startswith("sqlite://"):
        return url[len("sqlite://"):]
    return url
from app.core.enums.llm_provider import LLMProviderEnum


class Container:
    """
    Composition root for BioResearch AI.

    The container constructs the application's dependency graph.

    All concrete infrastructure implementations are created here and
    injected into application-level components.

    The container uses a singleton pattern for the workspace
    repository to ensure all use cases share the same persistent
    storage instance.

    Attributes
    ----------
    _workspace_repository : SqliteWorkspaceRepository | None
        Cached singleton instance of the workspace repository.
    """

    _workspace_repository: SqliteWorkspaceRepository | None = None

    @classmethod
    def get_workspace_repository(cls) -> SqliteWorkspaceRepository:
        if cls._workspace_repository is None:
            cls._workspace_repository = SqliteWorkspaceRepository(
                db_path=_sqlite_path_from_settings(),
            )
        assert cls._workspace_repository is not None
        return cls._workspace_repository

    @classmethod
    def build_orchestrator(cls) -> WorkspaceOrchestrator:
        """Build the WorkspaceOrchestrator with full dependencies."""
        pubmed_client = PubMedClient(
            email=settings.pubmed.email,
            api_key=settings.pubmed.api_key,
        )
        literature_searcher = PubMedProvider(client=pubmed_client)

        llm_provider = LLMFactory.create(
            LLMProviderEnum(settings.llm.provider)
        )

        report_mapper = ReportMapper()
        report_generator = LLMReportGenerator(
            llm_provider=llm_provider,
            report_mapper=report_mapper,
        )

        comparison_mapper = EvidenceComparisonMapper()
        comparison_generator = LLMComparisonGenerator(
            llm_provider=llm_provider,
            comparison_mapper=comparison_mapper,
        )

        workspace_repository = cls.get_workspace_repository()

        return WorkspaceOrchestrator(
            workspace_repository=workspace_repository,
            literature_searcher=literature_searcher,
            llm_provider=llm_provider,
            report_generator=report_generator,
            comparison_generator=comparison_generator,
        )

    @classmethod
    def build(cls) -> ResearchAssistant:
        """
        Build and configure the BioResearch AI application.

        Maintained for backwards compatibility. New clients should
        prefer :meth:`build_orchestrator` which exposes the FSM
        actions.

        Returns
        -------
        ResearchAssistant
            Fully configured application facade.
        """
        pubmed_client = PubMedClient(
            email=settings.pubmed.email,
            api_key=settings.pubmed.api_key,
        )
        literature_searcher = PubMedProvider(client=pubmed_client)

        llm_provider = LLMFactory.create(
            LLMProviderEnum(settings.llm.provider)
        )

        report_mapper = ReportMapper()
        report_generator = LLMReportGenerator(
            llm_provider=llm_provider,
            report_mapper=report_mapper,
        )

        workspace_repository = cls.get_workspace_repository()

        search_use_case = SearchLiteratureUseCase(
            literature_searcher=literature_searcher,
        )
        summarize_use_case = SummarizePapersUseCase(
            llm_provider=llm_provider,
        )
        generate_report_use_case = GenerateReportUseCase(
            report_generator=report_generator,
        )

        create_workspace_use_case = CreateWorkspaceUseCase(
            workspace_repository=workspace_repository,
        )
        get_workspace_use_case = GetWorkspaceUseCase(
            workspace_repository=workspace_repository,
        )
        update_workspace_use_case = UpdateWorkspaceUseCase(
            workspace_repository=workspace_repository,
        )

        workspace_service = WorkspaceService(
            create_workspace_use_case=create_workspace_use_case,
            get_workspace_use_case=get_workspace_use_case,
            update_workspace_use_case=update_workspace_use_case,
        )

        return ResearchAssistant(
            search_use_case=search_use_case,
            summarize_use_case=summarize_use_case,
            report_use_case=generate_report_use_case,
            workspace_service=workspace_service,
        )


# ----------------------------------------------------------------------
# FastAPI Dependency Providers
# ----------------------------------------------------------------------

_orchestrator: WorkspaceOrchestrator | None = None
_assistant: ResearchAssistant | None = None


def get_workspace_orchestrator() -> WorkspaceOrchestrator:
    """
    Provide the configured WorkspaceOrchestrator.

    The instance is created lazily on the first request and
    reused for subsequent requests. This is the preferred
    dependency for new endpoints that drive the FSM.
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Container.build_orchestrator()
    assert _orchestrator is not None
    return _orchestrator


_identifier_resolver: IdentifierResolver | None = None


def get_identifier_resolver() -> IdentifierResolver:
    """Provide the configured :class:`IdentifierResolver`.

    The resolver is the only component that talks to CrossRef and
    to the low-level PubMedClient. It is independent of the
    orchestrator because the resolve endpoint is read-only — it
    does not advance the FSM, just returns metadata that the
    frontend will then POST to /papers.
    """
    global _identifier_resolver
    if _identifier_resolver is None:
        pubmed_client = PubMedClient(
            email=settings.pubmed.email,
            api_key=settings.pubmed.api_key,
        )
        provider = PubMedProvider(client=pubmed_client)
        _identifier_resolver = IdentifierResolver(
            pubmed_provider=provider,
        )
    assert _identifier_resolver is not None
    return _identifier_resolver


def get_research_assistant() -> ResearchAssistant:
    """
    Provide the configured ResearchAssistant application facade.

    Maintained for backwards compatibility with the legacy routes
    (``/search``, ``/reports/generate``). New routes should depend
    on :func:`get_workspace_orchestrator` instead.
    """
    global _assistant
    if _assistant is None:
        _assistant = Container.build()
    assert _assistant is not None
    return _assistant
