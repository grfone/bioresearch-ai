"""
health.py

Application health monitoring endpoints.

Purpose
-------
Provides lightweight endpoints used to verify that the BioResearch AI
API is running correctly.

These endpoints intentionally avoid database, LLM, and external API
dependencies.

Author
------
Guillermo Ramajo Fernández
"""

from fastapi import APIRouter


router = APIRouter(
    tags=["System"],
)


@router.get(
    "/health",
    summary="Health check",
)
def health_check() -> dict[str, str]:
    """
    Verify API availability.

    Returns
    -------
    dict[str, str]
        Health status.
    """

    return {
        "status": "healthy",
    }


@router.get(
    "/health/sanitizer",
    summary="Citation sanitizer telemetry",
)
def sanitizer_stats() -> dict[str, int]:
    """
    Snapshot the in-process telemetry counters from
    ``citation_sanitizer``.

    The endpoint exposes:

      - ``total_calls``: every call to
        ``sanitize_citation_markers`` since process start.
      - ``total_dropped``: sum of hallucinated citation
        markers dropped across all calls.
      - ``calls_with_drops``: count of calls where at
        least one marker was dropped (the WARNING-firing
        path).

    Use case: an operator can poll this endpoint to see
    whether the LLM is currently hallucinating citation
    indices out of the bibliography range. A non-zero
    ``total_dropped`` is the data-quality signal the
    sanitizer was designed to surface.

    No DB, no LLM, no external API -- the counters are
    maintained in process memory by the sanitizer module
    itself, so this endpoint is safe to call from
    healthcheck probes and load balancers.

    Returns
    -------
    dict[str, int]
        A copy of the live ``_stats`` dict from
        ``app.infrastructure.llm.citation_sanitizer``.
    """
    from app.infrastructure.llm.citation_sanitizer import (
        get_stats,
    )

    return get_stats()
