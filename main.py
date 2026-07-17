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

                 React Frontend
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
             ResearchAssistant Facade
                       |
        --------------------------------
        |              |               |
 Literature       Summaries        Reports
 Search UC        Use Case         Generator
        |
        |
    PubMed Provider


Running
-------

Development:

    uvicorn main:app --reload


Production:

    uvicorn main:app --host 0.0.0.0 --port 8000


Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations


from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from app.api.routes import papers
from app.api.routes import report
from app.api.routes import search
from app.api.routes import workspace
from app.api.routes import health



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
            "http://localhost:5173",
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
        "/",
        tags=["System"],
        summary="API status",
    )
    async def root() -> dict[str, str]:
        """
        Return basic API information.

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


    return application



app = create_application()