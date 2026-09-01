"""
admin.py

Operator-facing diagnostics endpoints. These are read-only
introspection endpoints that expose the runtime state of
internals that are otherwise invisible once the app is
running:

- ``GET /admin/enricher-stats`` -- hit/miss counters, size,
  and capacity for the AbstractEnricher LRU cache. Lets
  operators confirm the singleton is actually being
  reused across requests (vs the docker-exec process-
  isolation pattern that confused the live verification
  in an earlier session).
- ``GET /admin/orchestrator-stats`` -- count of workspaces
  in each FSM state, including zero-filled entries for
  unused states. Useful for spotting stuck transient
  states, counting the work queue, and tracking
  completion rate.

The endpoints are deliberately cheap: no LLM calls, no
network. The enricher endpoint is purely in-memory; the
orchestrator endpoint is a single SQL ``GROUP BY`` query
on the workspaces table.

We don't expose:
- The cache contents (privacy / size)
- Configuration secrets
- The singleton itself (only its stats)

Future endpoints can be added here as new diagnostics
are needed (e.g. /admin/orchestrator-stats for the FSM
state counts).
"""

from fastapi import APIRouter

from app.config.container import get_identifier_resolver


router = APIRouter(
    tags=["Admin"],
    prefix="/admin",
)


@router.get(
    "/enricher-stats",
    summary="AbstractEnricher LRU cache statistics",
)
def enricher_stats() -> dict:
    """Return hit/miss counters, current size, and capacity
    for the AbstractEnricher LRU cache.

    Useful for:
    - Verifying the cache hit rate in production.
    - Debugging "why is the second DOI lookup still slow?"
      -- if hits is 0 after many requests, the cache isn't
      actually being reused.

    Returns
    -------
    dict
        ``{"hits": int, "misses": int, "size": int,
           "capacity": int}`` if the enricher is wired.

        ``{"status": "disabled"}`` if
        ``ABSTRACT_ENRICHER_ENABLED=false`` in .env (the
        enricher isn't constructed at all).

    Multi-worker behavior
    --------------------
    The cache backend is selected at startup by the
    ``CACHE_BACKEND`` env var. With ``CACHE_BACKEND=memory``
    (the default), each uvicorn worker has its own in-process
    LRU, so the counters returned here are PER WORKER -- the
    worker that handles this admin call may show different
    numbers than other workers. This is the historical
    behavior and is fine for single-worker deployments.

    With ``CACHE_BACKEND=redis``, all workers share a single
    cache backed by a Redis instance. The counters are
    system-wide (atomic INCR on Redis), so this endpoint
    reports the real totals regardless of which worker
    handles the call. See
    ``docs/multi-worker-cache-investigation.md`` for the full
    cost analysis that motivates this dual-backend design.

    The endpoint never raises -- the singleton is
    optional, and a missing enricher is a valid
    configuration, not an error.
    """
    resolver = get_identifier_resolver()
    enricher = resolver._abstract_enricher
    if enricher is None:
        return {
            "status": "disabled",
            "message": (
                "AbstractEnricher is not wired. "
                "Set ABSTRACT_ENRICHER_ENABLED=true in .env "
                "to enable HTML meta-tag fallback."
            ),
        }
    return enricher.cache_stats()


@router.get(
    "/orchestrator-stats",
    summary="WorkspaceOrchestrator FSM state counts",
)
def orchestrator_stats() -> dict:
    """Return the count of workspaces in each FSM state.

    Useful for:
    - Spotting unrecoverable workspaces in ``ERROR`` (a
      stuck workspace usually means a request crashed or
      the LLM gave up).
    - Counting the work queue (how many workspaces are
      waiting for the next FSM step -- ``INITIAL``
      workspaces are the head of the funnel, ``FINAL``
      workspaces are the tail).
    - Tracking completion rate (``FINAL`` count over time).

    Returns
    -------
    dict
        Map of state value (the enum string value) to the
        count of workspaces in that state. Includes an
        entry for every ``WorkspaceState`` member, even
        when the count is zero -- operators get a complete
        picture of the FSM rather than a sparse dict that
        silently drops unused states.

        ``{"total": N}`` is also included for convenience
        (the sum of all state counts).

    The endpoint delegates to ``WorkspaceOrchestrator
    .state_counts()`` which is the public observability
    entry point. The SQLite implementation runs as a
    single ``GROUP BY`` query for efficiency. Cheap
    enough to call from a monitoring dashboard on every
    refresh.
    """
    from app.config.container import get_workspace_orchestrator

    orchestrator = get_workspace_orchestrator()
    counts = orchestrator.state_counts()

    # Belt-and-braces: ensure every WorkspaceState is
    # represented in the response, even with count 0.
    # The repository already zero-fills, but the contract
    # here is "if a state exists in the enum, the response
    # has a key for it" -- guarding against any future repo
    # implementation that forgets.
    from app.core.enums.workspace_state import WorkspaceState
    for state in WorkspaceState:
        counts.setdefault(state.value, 0)

    # Add the total for convenience. (We exclude any
    # pre-existing "total" key from the underlying dict
    # in case the repository decides to add one later.)
    counts["total"] = sum(
        v for k, v in counts.items() if k != "total"
    )
    return counts


from urllib.parse import unquote


@router.post(
    "/papers/refresh/{doi:path}",
    summary="Invalidate a single cache entry and re-fetch the abstract",
    responses={
        200: {"description": "Cache entry was found and refreshed."},
        404: {"description": "No cache entry existed for this DOI."},
    },
)
def force_refresh_paper(doi: str) -> dict:
    """
    Invalidate the LRU cache entry for a DOI and re-fetch
    its abstract from the publisher.

    Useful when:
    - The publisher updated the abstract (e.g. they fixed
      a typo or added version 2 of the abstract).
    - The cached value is suspicious and an operator
      wants to verify the live fetch works.
    - A researcher manually fixed a typo in their DOI
      and wants to retry the lookup (cached ``None``
      entries would otherwise block re-lookup).

    Multi-worker behavior
    --------------------
    With ``CACHE_BACKEND=memory`` (the default), this only
    invalidates the cache of the worker that handles the
    request. The other workers' caches for this DOI are
    untouched, so a follow-up request that lands on a
    different worker may return the stale value. Set
    ``CACHE_BACKEND=redis`` to get system-wide invalidation
    -- every worker sees the miss on its next read.

    Returns
    -------
    dict
        ``{"doi": str, "invalidate_returned": bool,
           "abstract_length": int | None,
           "abstract_preview": str | None}``

        ``invalidate_returned`` is True if a cache entry
        was actually removed (the endpoint also re-fetches
        either way). If the re-fetch succeeds, the new
        value's length and preview are returned. If the
        re-fetch fails (publisher unreachable, DOI
        invalid), ``abstract_length`` and
        ``abstract_preview`` are null.

    The DOI in the URL may be percent-encoded; we unquote
    it before passing to the cache. The path uses
    ``{doi:path}`` so DOIs with slashes (the standard
    ``10.PREFIX/SUFFIX`` form) are accepted without
    percent-encoding. URL form:
    ``/admin/papers/refresh/<doi>``.
    """
    doi = unquote(doi)

    from app.config.container import get_identifier_resolver

    resolver = get_identifier_resolver()
    enricher = resolver._abstract_enricher
    if enricher is None:
        return {
            "status": "disabled",
            "message": (
                "AbstractEnricher is not wired. "
                "Set ABSTRACT_ENRICHER_ENABLED=true in .env "
                "to enable the abstract enricher."
            ),
        }

    was_cached = enricher.invalidate(doi)
    # Re-fetch from scratch. fetch() puts the result back
    # in the cache (including the None sentinel for
    # "this DOI doesn't have an abstract").
    result = enricher.fetch(doi)
    if result is None:
        return {
            "doi": doi,
            "invalidate_returned": was_cached,
            "abstract_length": None,
            "abstract_preview": None,
        }
    abstract_text = result.abstract
    return {
        "doi": doi,
        "invalidate_returned": was_cached,
        "abstract_length": len(abstract_text),
        "abstract_preview": abstract_text[:120],
    }


@router.delete(
    "/enricher-cache",
    summary="Drop the entire AbstractEnricher LRU cache",
)
def clear_enricher_cache() -> dict:
    """
    Drop every cached abstract-enrichment entry.

    Useful when:
    - An operator wants to fully reset cache state
      (e.g. after a policy change). Equivalent to
      flushall in a cache like Redis.
    - Cache hit rate is suspiciously low; clearing and
      letting it refill is faster than waiting for the
      LRU to expire.

    Multi-worker behavior
    --------------------
    With ``CACHE_BACKEND=memory`` (the default), this only
    clears the cache of the worker that handles the request.
    Set ``CACHE_BACKEND=redis`` to get a system-wide clear
    (DEL on every key in the Redis namespace). With
    multi-worker deployments, the ``memory`` mode can be
    surprising -- operators expect ``flushall`` to mean
    flush all, but with per-worker caches it really means
    "flush this one worker".

    Returns
    -------
    dict
        ``{"cleared": bool, "stats_after": dict}``.
        ``cleared`` is True if the enricher was wired
        and the cache was cleared. ``stats_after`` is
        the result of ``cache_stats()`` after clearing
        -- should show ``hits=0, misses=0, size=0,
        capacity=<unchanged>``.

    If the enricher is not wired (e.g.
    ``ABSTRACT_ENRICHER_ENABLED=false``), returns 200
    with ``{"status": "disabled", ...}``.
    """
    from app.config.container import get_identifier_resolver

    resolver = get_identifier_resolver()
    enricher = resolver._abstract_enricher
    if enricher is None:
        return {
            "status": "disabled",
            "message": (
                "AbstractEnricher is not wired. "
                "Set ABSTRACT_ENRICHER_ENABLED=true in .env "
                "to enable the abstract enricher."
            ),
        }
    enricher.clear_cache()
    return {
        "cleared": True,
        "stats_after": enricher.cache_stats(),
    }
