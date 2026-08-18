"""
main.py

Application entry point for BioResearch AI.

Purpose
-------
This module initializes the FastAPI application that exposes the
BioResearch AI platform through a REST API.

The module is intentionally limited to application bootstrapping.

Responsibilities
-----------------

- Create the FastAPI application instance.
- Configure middleware.
- Register API routers.
- Expose the application object for ASGI servers.
- Serve the prebuilt React frontend from ``frontend/dist`` when
  available (production / Docker image). In development the SPA
  is served by Vite on ``http://localhost:5173`` and the backend
  exposes only the API.

This module contains no:

- scientific logic;
- literature retrieval;
- LLM orchestration;
- domain rules;
- persistence logic.

Those responsibilities belong to the appropriate layers following
Clean Architecture principles.

Architecture
------------

                 React Frontend (Vite or built bundle)
                       |
                       |
                    HTTP API
                       |
                       |
                 FastAPI Application
                       |
                       |
                Presentation Layer
                       |
                       |
             WorkspaceOrchestrator
                       |
        --------------------------------
        |              |              |
 Literature       Summaries       Reports
 Provider         Use Case        Generator
        |
        |
    PubMed / Ollama


Running
-------

Development (two servers):

    uvicorn main:app --reload
    cd frontend && npm run dev

Production (single image, SPA served by FastAPI):

    uvicorn main:app --host 0.0.0.0 --port 8000


Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations


import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


from app.api.routes import admin
from app.api.routes import papers
from app.api.routes import report
from app.api.routes import search
from app.api.routes import workspace
from app.api.routes import workspace_actions
from app.api.routes import health


# ---------------------------------------------------------------------------
# Path to the prebuilt frontend bundle.
#
# In the Docker image this directory is populated by ``npm run build``
# during the Dockerfile build stage. In development it is usually
# absent (the SPA is served by Vite on port 5173). When the
# directory exists we mount it on "/" so the same FastAPI app
# serves both the API and the static frontend.
# ---------------------------------------------------------------------------

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(
    application: FastAPI,
):
    """
    Manage application lifecycle events.

    This function is the central place for future initialization
    and cleanup operations.

    Future examples:

    - database connections;
    - vector database clients;
    - MCP connections;
    - telemetry initialization;
    - model warm-up.

    Parameters
    ----------
    application
        FastAPI application instance.

    Yields
    ------
    None
    """

    # Configure the application's logging subsystem so that
    # the LOG_LEVEL env var is honoured (and DEBUG logs are
    # emitted when researchers enable them for cache HIT /
    # MISS visibility etc.).
    from app.core.logger import configure_logging
    configure_logging()

    logger = logging.getLogger(__name__)

    # Log the abstract-enricher pipeline configuration so
    # operators can see at boot time which fallbacks are
    # wired. This is the operator's only window into the
    # wiring -- once the app is running, the only way to
    # inspect this is via /admin/cache-stats (TODO).
    #
    # The line is structured as a single space-separated
    # record so log scrapers can grep for ``enricher=``
    # and ``llm_extractor=`` substrings.
    try:
        from app.config.container import get_identifier_resolver
        from app.config.settings import settings as _settings
        resolver = get_identifier_resolver()
        enricher = resolver._abstract_enricher
        if enricher is None:
            logger.info(
                "AbstractEnricher | "
                "html_enricher=disabled llm_extractor=disabled "
                "(ABSTRACT_ENRICHER_ENABLED is false)"
            )
        else:
            llm_extractor = (
                enricher._llm_extractor
            )
            llm_state = (
                f"enabled provider={_settings.llm.provider} "
                f"model={_settings.llm.model}"
                if llm_extractor is not None
                else "disabled "
                "(LLM_ABSTRACT_EXTRACTION_ENABLED is false)"
            )
            logger.info(
                "AbstractEnricher | "
                "html_enricher=enabled "
                f"cache_size={enricher._cache_size} "
                f"llm_extractor={llm_state}"
            )
    except Exception as exc:  # noqa: BLE001
        # Never let a startup-time diagnostic crash the
        # app -- the enricher config is informational.
        logger.info(
            "AbstractEnricher | config diagnostic failed: %s",
            exc,
        )

    print("BioResearch AI API starting...")

    yield

    print("BioResearch AI API shutting down...")



def create_application() -> FastAPI:
    """
    Create and configure the BioResearch AI FastAPI application.

    Returns
    -------
    FastAPI
        Fully configured FastAPI application instance.
    """

    application = FastAPI(
        title="BioResearch AI",
        description=(
            "AI-powered biomedical literature research assistant."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )


    # --------------------------------------------------------------
    # Middleware configuration
    # --------------------------------------------------------------

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            # Vite development server.
            "http://localhost:5173",
            # Same-origin requests when the SPA is served by FastAPI.
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=[
            "*",
        ],
        allow_headers=[
            "*",
        ],
    )


    # --------------------------------------------------------------
    # Root endpoint
    # --------------------------------------------------------------

    @application.get(
        "/api",
        tags=["System"],
        summary="API status",
    )
    async def root() -> dict[str, str]:
        """
        Return basic API information.

        Note the path is ``/api`` (not ``/``) so the SPA's index.html
        can be served from ``/`` when the frontend bundle is mounted.

        Returns
        -------
        dict[str, str]
            API status information.
        """

        return {
            "application": "BioResearch AI",
            "status": "running",
            "version": "1.0.0",
        }


    # --------------------------------------------------------------
    # API Routes
    # --------------------------------------------------------------

    application.include_router(
        health.router,
    )

    application.include_router(
        papers.router,
    )

    application.include_router(
        report.router,
    )

    application.include_router(
        search.router,
    )

    application.include_router(
        workspace.router,
    )

    application.include_router(
        workspace_actions.router,
    )

    application.include_router(
        admin.router,
    )

    # --------------------------------------------------------------
    # Static frontend (production-only)
    # --------------------------------------------------------------
    # When the SPA bundle is present we mount it at "/" so the same
    # port serves both the API and the static assets. Vite's dev
    # server (5173) is unchanged when the bundle is absent.

    if FRONTEND_DIST.is_dir():
        application.mount(
            "/",
            StaticFiles(directory=str(FRONTEND_DIST), html=True),
            name="frontend",
        )

    return application



app = create_application()
