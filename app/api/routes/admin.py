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
    - Confirming the singleton pattern is holding across
      uvicorn worker processes (one process = one cache).
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
    - Spotting stuck transient states (a workspace in
      SEARCHING/SUMMARIZING/COMPARING/REPORTING for more
      than a few seconds usually means a request crashed).
    - Counting the work queue (how many workspaces are
      waiting for the next FSM step).
    - Tracking terminal completion rate (COMPLETED count
      over time).

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
