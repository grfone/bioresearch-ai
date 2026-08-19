"""Cache protocol + sentinel + stats dataclass.

See ``app/infrastructure/cache/__init__.py`` for the package-level
overview. This file defines ONLY the protocol interface and the
data classes the protocol uses; implementations live in
``in_memory_cache.py`` and ``redis_cache.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


# Sentinel used to represent a cached "no abstract" entry in a
# JSON-friendly form. The string "__bioresearch_no_abstract__"
# is intentionally exotic so it can never collide with a real
# abstract's content.
NO_ABSTRACT_SENTINEL = "__bioresearch_no_abstract__"


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Snapshot of cache counters returned by ``stats()``.

    Attributes
    ----------
    hits : int
        Number of lookups that found the key in the cache
        (regardless of whether the value was ``None`` or an
        ExtractionResult).
    misses : int
        Number of lookups that did NOT find the key.
    size : int
        Current number of entries in the cache.
    capacity : int
        Maximum number of entries the cache will hold.
        ``0`` means the cache is disabled (every lookup is a miss).
    """

    hits: int
    misses: int
    size: int
    capacity: int

    def as_dict(self) -> dict:
        """Return a JSON-friendly dict for the admin endpoint.

        Kept as a method (not a property) so the existing
        AbstractEnricher.cache_stats() contract -- which
        returns a plain dict -- is preserved.
        """
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": self.size,
            "capacity": self.capacity,
        }


# Lookup result returned by ``CacheProtocol.get``. The cache
# distinguishes "key not present" (MISS) from "key present but
# value is None" (HIT_NONE) -- this is the existing contract
# tested by ``test_cache_distinguishes_none_from_absent``.
HIT = "hit"          # key present, value is an ExtractionResult
HIT_NONE = "hit_none"  # key present, value is None (cached "no abstract")
MISS = "miss"        # key not present


@runtime_checkable
class CacheProtocol(Protocol):
    """Common interface for the abstract-enricher cache backends.

    Implementations: ``InMemoryLRUCache``, ``RedisCache``.

    All methods are synchronous. The Redis implementation
    uses a synchronous redis-py client (not asyncio) because
    the abstract-enricher is called from a sync code path.

    Lifetime
    --------
    The cache instance is created once per process at the
    call to ``get_identifier_resolver`` and held in the
    module-level ``_identifier_resolver`` global. With
    ``CACHE_BACKEND=memory`` that's the only state; with
    ``CACHE_BACKEND=redis`` there's a Redis connection pool
    attached to the cache instance that holds the TCP
    connections alive for the worker's lifetime.
    """

    def get(self, key: str) -> tuple[str, object | None]:
        """Look up ``key`` in the cache.

        Parameters
        ----------
        key : str
            The normalized cache key (caller-normalized -- the
            cache itself does no normalization).

        Returns
        -------
        (status, value) : tuple[str, ExtractionResult | None]
            - ``(HIT, value)`` if the key was present and
              value is non-None.
            - ``(HIT_NONE, None)`` if the key was present
              and the cached value is None.
            - ``(MISS, None)`` if the key was not present.

        ``value`` is an ``ExtractionResult`` instance (or
        whatever the implementation returns) -- the caller
        doesn't care about the underlying representation
        as long as the public attributes (``.abstract`` and
        ``.inferred``) work.

        The 3-valued status (``HIT`` / ``HIT_NONE`` / ``MISS``)
        matches the existing internal contract that
        "a cached None is distinct from not-cached".
        """
        ...

    def set(self, key: str, value: object | None) -> None:
        """Store ``value`` under ``key``.

        If ``value`` is None, the implementation must store
        a sentinel so the next ``get`` returns ``HIT_NONE``
        (not ``MISS``). This preserves the "negative cache"
        behavior for DOIs whose publisher returned a blocked
        page -- we don't want to retry the HTTP fetch just
        because the result was None.

        Implementations are responsible for LRU eviction
        when the cache is full -- callers don't see evictions.
        """
        ...

    def delete(self, key: str) -> bool:
        """Remove a single entry from the cache.

        Returns
        -------
        bool
            True if an entry was removed, False if no entry
            existed for the key. The in-memory impl reads this
            from the OrderedDict; the Redis impl uses ``DEL``.
        """
        ...

    def clear(self) -> int:
        """Remove every entry from the cache.

        Returns
        -------
        int
            Number of entries removed. Used by the admin
            endpoint to report the size of the wipe to operators.
        """
        ...

    def stats(self) -> CacheStats:
        """Return current hit/miss/size/capacity counters.

        In multi-worker mode with the memory backend, these
        counters are PER WORKER (not system-wide). The admin
        endpoint docstring calls this out. With the Redis
        backend, the counters are system-wide (atomic
        INCRBY), so operators see the real totals regardless
        of which worker handles the admin call.
        """
        ...

    @property
    def capacity(self) -> int:
        """Maximum number of entries. ``0`` means the cache
        is disabled (every lookup is a miss). Exposed as a
        property so the admin endpoint can report it without
        going through ``stats()``.
        """
        ...
