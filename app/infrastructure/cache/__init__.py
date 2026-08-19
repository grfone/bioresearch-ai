"""Cache backend abstraction for the abstract-enricher LRU.

Why this exists
---------------
The original AbstractEnricher held its LRU cache as a
module-level OrderedDict inside the singleton
``_identifier_resolver``. When uvicorn runs with --workers N,
each worker process gets its own fresh module-level state --
so each worker has its own LRU cache, and the same DOI fetched
N times can result in up to N CrossRef/OpenAlex/HTML fetches AND
up to N MiniMax/LLM API calls.

See ``docs/multi-worker-cache-investigation.md`` for the full
reproduction with log evidence.

This package introduces a small protocol so the abstract-enricher
can use either:

  - InMemoryLRUCache (default; same behavior as before -- one
    cache per process). Useful for single-worker deployments
    and tests.

  - RedisCache (new; shared across workers). When
    ``CACHE_BACKEND=redis`` is set, all workers hit the same
    Redis instance, so the "popular DOI fetched N times" problem
    collapses to a single fetch system-wide.

The choice is made at startup in ``get_identifier_resolver``
based on the ``CACHE_BACKEND`` env var. The default is ``memory``
so the project keeps working without any external dependency.
"""

from __future__ import annotations

from .cache_protocol import (
    HIT,
    HIT_NONE,
    MISS,
    NO_ABSTRACT_SENTINEL,
    CacheProtocol,
    CacheStats,
)
from .in_memory_cache import InMemoryLRUCache
from .redis_cache import RedisCache


def make_cache(
    backend: str,
    *,
    capacity: int = 256,
    redis_url: str | None = None,
    redis_key_prefix: str = "bioresearch:abstract:",
) -> CacheProtocol:
    """Factory: build the right cache backend from a string name.

    Parameters
    ----------
    backend : str
        One of ``"memory"`` or ``"redis"``. Case-insensitive.
    capacity : int
        Maximum number of entries the cache will hold.
        ``0`` means the cache is disabled. Defaults to 256.
    redis_url : str | None
        Required when ``backend="redis"``. The connection URL
        (``redis://host:port/db``). Ignored otherwise.
    redis_key_prefix : str
        Used by ``RedisCache`` to namespace keys. Defaults to
        ``"bioresearch:abstract:"``. Ignored by the memory backend.

    Returns
    -------
    CacheProtocol
        Either an ``InMemoryLRUCache`` or a ``RedisCache``
        instance, depending on the value of ``backend``.

    Raises
    ------
    ValueError
        If ``backend`` is not a recognized name, or if
        ``backend="redis"`` but no ``redis_url`` was given.

    Notes
    -----
    This factory is the single place that translates an env-var
    string into a cache instance. The container module calls
    this in ``get_identifier_resolver`` so the rest of the
    application sees only the protocol.
    """
    backend_normalized = backend.strip().lower()
    if backend_normalized in ("memory", "in_memory", "in-memory"):
        return InMemoryLRUCache(capacity=capacity)
    if backend_normalized in ("redis", "redis_cache"):
        if not redis_url:
            raise ValueError(
                "CACHE_BACKEND=redis requires REDIS_URL. Set it to a "
                "redis://host:port/db URL (e.g. redis://localhost:6379/0)."
            )
        return RedisCache(
            redis_url=redis_url,
            capacity=capacity,
            key_prefix=redis_key_prefix,
        )
    raise ValueError(
        f"Unknown CACHE_BACKEND {backend!r}. Use 'memory' or 'redis'."
    )


__all__ = [
    "HIT",
    "HIT_NONE",
    "MISS",
    "NO_ABSTRACT_SENTINEL",
    "CacheProtocol",
    "CacheStats",
    "InMemoryLRUCache",
    "RedisCache",
    "make_cache",
]
