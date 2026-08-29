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


@router.get(
    "/health/title-fallback",
    summary="H1 title-fallback telemetry",
)
def title_fallback_stats() -> dict:
    """
    Snapshot the H1 title-fallback telemetry.

    The title-fallback module (in
    ``app.infrastructure.llm.title_fallback``) injects an
    H1 heading into the synthesis body whenever the LLM
    omits one. The endpoint exposes the rolling-window
    rate of fallback injections so operators can monitor
    whether the synthesis LLM is consistently skipping
    the H1 directive (a degraded user prompt would
    show up here as a high ``rate``).

    Response keys:

    - ``total_calls``: number of invocations recorded in
      the rolling window.
    - ``total_fallbacks``: subset that actually injected
      a fallback.
    - ``rate``: fraction of calls that injected a
      fallback (0.0 to 1.0).
    - ``window_size``: current size of the rolling window
      (capped at ``_FALLBACK_RATE_WINDOW``).
    - ``current_window``: list of 0/1 entries showing the
      trailing calls. 1 = fallback injected, 0 = LLM
      already had an H1. Useful for spot-checking recent
      behaviour.

    The endpoint is read-only -- it doesn't reset the
    counters (use ``reset_fallback_stats`` in a Python
    REPL for that, or restart the process).

    Use case: pair with a Prometheus scrape or a simple
    log-based alert. The module also emits a WARNING log
    line when ``rate >= _FALLBACK_RATE_THRESHOLD`` over a
    meaningful sample size, so the same data is available
    via log scraping.
    """
    from app.infrastructure.llm.title_fallback import (
        get_fallback_stats,
    )

    return get_fallback_stats()
