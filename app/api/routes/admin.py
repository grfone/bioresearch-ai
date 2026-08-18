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

The endpoints are deliberately cheap: no DB calls, no
LLM calls, no network. They read in-memory counters and
return them as JSON.

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
