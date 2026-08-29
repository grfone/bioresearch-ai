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


@router.get(
    "/metrics",
    summary="Prometheus metrics exposition",
)
def prometheus_metrics():
    """
    Prometheus exposition-format metrics endpoint.

    Returns a plain-text body compatible with the
    Prometheus exposition format
    (https://prometheus.io/docs/instrumenting/exposition_formats/).
    A scraper (Prometheus server, Grafana Agent, etc.) can
    hit this endpoint on a regular interval to ingest
    the metrics.

    Metrics exposed
    ---------------
    Citation sanitizer (commit ``8cf20a3``):

    - ``citation_sanitizer_calls_total`` (counter):
      cumulative calls to
      ``sanitize_citation_markers`` since process start.
    - ``citation_sanitizer_dropped_total`` (counter):
      cumulative hallucinated citation markers dropped.
    - ``citation_sanitizer_calls_with_drops_total``
      (counter): calls where at least one marker was
      dropped.

    H1 title-fallback (this commit):

    - ``title_fallback_calls_total`` (counter):
      cumulative calls to ``inject_h1_fallback``.
    - ``title_fallback_injections_total`` (counter):
      cumulative fallback injections.
    - ``title_fallback_rate`` (gauge): current fallback
      injection rate over the trailing window
      (0.0 to 1.0).
    - ``title_fallback_window_size`` (gauge): current
      size of the trailing window (capped at
      ``_FALLBACK_RATE_WINDOW``).

    Use case
    --------
    Pair this endpoint with an alertmanager rule on
    ``title_fallback_rate >= 0.5`` to convert the
    in-process counter into a real PagerDuty / Slack
    alert. The current implementation emits a WARNING
    log line at the same threshold; this endpoint makes
    the same data available to external monitoring
    tools without log scraping.

    Example alertmanager rule::

        - alert: H1FallbackRateHigh
          expr: title_fallback_rate > 0.5
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: H1 title-fallback rate above 50%

    No DB, no LLM, no external API -- the counters are
    maintained in process memory by the telemetry
    modules themselves, so this endpoint is safe to
    call from healthcheck probes and load balancers.

    Returns
    -------
    PlainTextResponse
        Prometheus exposition-format text body.
        ``Content-Type: text/plain; version=0.0.4`` (the
        standard Prometheus content type).
    """
    from fastapi.responses import PlainTextResponse

    from app.infrastructure.llm.citation_sanitizer import (
        get_stats as get_sanitizer_stats,
    )
    from app.infrastructure.llm.title_fallback import (
        get_fallback_stats,
    )
    from app.infrastructure.observability.prometheus_exposition import (
        format_counter,
        format_gauge,
        render_metrics,
    )

    sanitizer_stats = get_sanitizer_stats()
    fallback_stats = get_fallback_stats()

    blocks = [
        # Citation sanitizer (counters, monotonically
        # increasing since process start).
        format_counter(
            "citation_sanitizer_calls_total",
            "Total calls to sanitize_citation_markers.",
            sanitizer_stats.get("total_calls", 0),
        ),
        format_counter(
            "citation_sanitizer_dropped_total",
            "Total hallucinated citation markers dropped.",
            sanitizer_stats.get("total_dropped", 0),
        ),
        format_counter(
            "citation_sanitizer_calls_with_drops_total",
            "Calls that dropped at least one marker.",
            sanitizer_stats.get("calls_with_drops", 0),
        ),
        # H1 title-fallback (counters + gauges).
        format_counter(
            "title_fallback_calls_total",
            "Total calls to inject_h1_fallback.",
            fallback_stats.get("total_calls", 0),
        ),
        format_counter(
            "title_fallback_injections_total",
            "Total fallback injections (LLM omitted the H1).",
            fallback_stats.get("total_fallbacks", 0),
        ),
        format_gauge(
            "title_fallback_rate",
            "Current fallback injection rate over the trailing window (0.0 to 1.0).",
            fallback_stats.get("rate", 0.0),
        ),
        format_gauge(
            "title_fallback_window_size",
            "Current size of the trailing window.",
            fallback_stats.get("window_size", 0),
        ),
    ]

    return PlainTextResponse(
        content=render_metrics(blocks),
        media_type="text/plain; version=0.0.4",
    )
