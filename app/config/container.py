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
Use Cases (search, summarise, etc.)
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

from app.infrastructure.llm.llm_factory import (
    LLMFactory,
)
from app.infrastructure.llm.report_generator import (
    LLMReportGenerator,
)
from app.infrastructure.llm.report_mapper import (
    ReportMapper,
)
from app.infrastructure.pdf.reportlab_generator import (
    ReportLabPDFGenerator,
)
from app.infrastructure.pubmed.client import PubMedClient
from app.infrastructure.pubmed.abstract_enricher import (
    AbstractEnricher,
)
from app.infrastructure.pubmed.llm_extractor import (
    LLMExtractor,
)
from app.infrastructure.pubmed.identifier_resolver import (
    IdentifierResolver,
)
from app.infrastructure.literature.biorxiv_client import (
    BiorxivSearcher,
)
from app.infrastructure.literature.europe_pmc_client import (
    EuropePMCSearcher,
)
from app.infrastructure.literature.multi_source import (
    MultiSourceSearcher,
)
from app.infrastructure.cache import make_cache
from app.infrastructure.literature.openalex_client import (
    OpenAlexSearcher,
)
from app.infrastructure.pubmed.provider import PubMedProvider
from app.infrastructure.storage.sqlite_workspace_repository import (
    SqliteWorkspaceRepository,
)

from app.config.settings import settings

from app.core.enums.search_source import SearchSource, default_sources

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
def _build_literature_searchers() -> dict[
    SearchSource, "LiteratureSearcher"
]:
    """Construct the per-source ``LiteratureSearcher`` instances.

    Sources are enabled/disabled via the
    ``LiteratureSettings`` block — disabled sources are
    simply omitted from the returned dict, so the
    ``MultiSourceSearcher`` fan-out ignores them.

    PubMed is always enabled (it's the canonical medical
    source and the only one with the ``get_by_id``
    contract for PMID/DOI). OpenAlex is on by default
    (broadest coverage). Europe PMC is on by default.
    bioRxiv is opt-in because it overlaps heavily with
    PubMed and OpenAlex but adds no real keyword search
    capability.
    """
    from app.domain.interfaces.literature_searcher import (
        LiteratureSearcher,
    )

    timeout = float(settings.pubmed.timeout)
    pubmed_client = PubMedClient(
        email=settings.pubmed.email,
        api_key=settings.pubmed.api_key,
    )
    searchers: dict[SearchSource, LiteratureSearcher] = {
        SearchSource.PUBMED: PubMedProvider(client=pubmed_client),
    }
    if settings.literature.openalex_enabled:
        searchers[SearchSource.OPENALEX] = OpenAlexSearcher(
            mailto=settings.literature.openalex_mailto
            or settings.pubmed.email,
            timeout_seconds=timeout,
        )
    if settings.literature.europe_pmc_enabled:
        searchers[SearchSource.EUROPE_PMC] = EuropePMCSearcher(
            timeout_seconds=timeout,
        )
    if settings.literature.biorxiv_enabled:
        searchers[SearchSource.BIORXIV] = BiorxivSearcher(
            server=settings.literature.biorxiv_server,
            timeout_seconds=timeout,
        )
    return searchers


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
        # Multi-source fan-out: PubMed + OpenAlex + (optionally)
        # Europe PMC / bioRxiv. The orchestrator exposes the
        # full ``search_with_filters`` entry point on the
        # ``MultiSourceSearcher``, so the Advanced Search
        # modal in the UI can pick which sources to use.
        searchers = _build_literature_searchers()
        literature_searcher = MultiSourceSearcher(searchers)

        llm_provider = LLMFactory.create(
            LLMProviderEnum(settings.llm.provider)
        )

        report_mapper = ReportMapper()
        report_generator = LLMReportGenerator(
            llm_provider=llm_provider,
            report_mapper=report_mapper,
        )

        # PDF generator for the PUBLISH action. Uses
        # reportlab with embedded DejaVu Sans for full
        # Unicode coverage (Greek letters, diacritics,
        # em-dashes) and clickable internal link
        # annotations for citation references. A
        # 20-paper report renders in tens of milliseconds
        # (no LLM, no network).
        pdf_generator = ReportLabPDFGenerator()

        workspace_repository = cls.get_workspace_repository()

        return WorkspaceOrchestrator(
            workspace_repository=workspace_repository,
            literature_searcher=literature_searcher,
            llm_provider=llm_provider,
            report_generator=report_generator,
            pdf_generator=pdf_generator,
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
        # Multi-source fan-out — same composition as the
        # orchestrator. The ResearchAssistant exposes the
        # same search entry point but at the use-case layer.
        searchers = _build_literature_searchers()
        literature_searcher = MultiSourceSearcher(searchers)

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
        # The HTML-fallback enricher is opt-in because it
        # adds ~1-2s latency per DOI lookup. Researchers
        # who care about maximal abstract coverage can
        # set ABSTRACT_ENRICHER_ENABLED=true in .env.
        enricher = None
        if settings.literature.abstract_enricher_enabled:
            # Optionally wire the LLM extractor as a
            # fallback. The LLM is opt-in because every
            # call costs tokens; the deterministic regex
            # path is free.
            llm_extractor = None
            if settings.literature.llm_abstract_extraction_enabled:
                llm_provider = LLMFactory.create(
                    LLMProviderEnum(settings.llm.provider)
                )
                llm_extractor = LLMExtractor(llm_provider=llm_provider)
            # Construct the cache backend. ``CACHE_BACKEND``
            # defaults to ``memory`` (in-process LRU, one
            # cache per worker -- the historical behavior).
            # Set ``CACHE_BACKEND=redis`` to share a single
            # cache across all uvicorn workers via Redis.
            # See ``docs/multi-worker-cache-investigation.md``
            # for the multi-worker cost analysis.
            #
            # On a misconfigured Redis (e.g. wrong host,
            # unreachable server), ``make_cache`` succeeds
            # at construction but the FIRST ``get`` call
            # raises ``redis.exceptions.ConnectionError``.
            # That's the right behavior -- silent fallback
            # to the in-memory impl would re-introduce the
            # fragmentation bug. Operators see the error in
            # the logs and fix the Redis config.
            cache = make_cache(
                settings.literature.cache_backend,
                capacity=settings.literature.cache_size,
                redis_url=settings.literature.redis_url,
                redis_key_prefix=settings.literature.redis_key_prefix,
            )
            enricher = AbstractEnricher(
                llm_extractor=llm_extractor,
                cache=cache,
            )
        _identifier_resolver = IdentifierResolver(
            pubmed_provider=provider,
            abstract_enricher=enricher,
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
