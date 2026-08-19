"""In-memory LRU cache implementation of ``CacheProtocol``.

This is the default backend. It is identical in behavior to
the original ``AbstractEnricher._cache`` ``OrderedDict`` (see
the ``6c5543a`` commit that introduced the LRU cache); the
only difference is the shape -- this is a class that
implements the protocol, not a raw dict held on the enricher.

Why the protocol matters
------------------------
Before this refactor, ``AbstractEnricher`` reached into its
own ``self._cache`` OrderedDict directly. That tightly coupled
the enricher to the in-memory implementation. With the
protocol, the enricher now calls ``cache.get(key)`` /
``cache.set(key, value)`` / etc., and the implementation
(in-memory or Redis) is selected at startup. This is what
makes the multi-worker fix possible.

LRU semantics
-------------
``set`` inserts at the end of an OrderedDict. ``get`` on a
hit calls ``move_to_end``. When the dict exceeds capacity,
``popitem(last=False)`` removes the least-recently-used entry
(the one at the front of the dict). This is the standard
"LRU via OrderedDict" pattern.

Capacity
--------
``capacity=0`` is a valid configuration -- it means the cache
is disabled. Every ``get`` returns ``MISS`` and every ``set``
is a no-op. The abstract-enricher used to support this via
``if self._cache_size > 0`` checks at every operation; the
cache protocol keeps that contract by making the in-memory
impl short-circuit when capacity is 0.

Counter semantics
-----------------
The in-memory impl's ``hits`` and ``misses`` are local to the
process. In multi-worker mode (``uvicorn --workers N``) each
worker has its own counter. The admin endpoint docstring
explicitly calls this out: when ``CACHE_BACKEND=memory`` and
``--workers > 1``, the admin endpoint shows per-worker
counters, not system-wide. Operators who need system-wide
counters should set ``CACHE_BACKEND=redis``.

Thread safety
-------------
The in-memory impl is NOT thread-safe. This is fine for the
async uvicorn worker model (one event loop per process, all
cache calls from the same loop) but is NOT safe for the
gunicorn sync-workers model (``--worker-class=gthread`` or
similar). If the project ever switches to threaded workers,
this impl will need a ``threading.Lock`` (Redis is already
thread-safe via the connection pool).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .cache_protocol import (
    HIT,
    HIT_NONE,
    MISS,
    NO_ABSTRACT_SENTINEL,
    CacheProtocol,
    CacheStats,
)


class InMemoryLRUCache(CacheProtocol):
    """LRU cache backed by a process-local ``OrderedDict``.

    This is the default backend. For multi-worker deployments
    that need shared state, set ``CACHE_BACKEND=redis`` and
    configure ``REDIS_URL``; the container module will swap in
    ``RedisCache`` instead.

    Parameters
    ----------
    capacity : int
        Maximum number of entries. ``0`` disables the cache.
        Default 256, matches the historical default in
        ``AbstractEnricher.__init__``.

    Notes
    -----
    The value type is ``dict`` (a deserialized ``ExtractionResult``)
    in this implementation, but callers should treat it as opaque --
    the public attributes the enricher reads are ``.abstract`` and
    ``.inferred``, both of which are present on the dict (since
    ``ExtractionResult.__init__`` stores them as instance attrs
    and ``dataclasses.asdict`` would yield the same shape, but
    we don't go through ``asdict`` -- we directly use the
    ExtractionResult instance).

    Actually: the value stored in this impl is the ExtractionResult
    *object itself* (we just put it in the dict and pull it out
    unchanged). The protocol's ``value`` is typed as ``object``
    to avoid coupling the protocol to ExtractionResult.
    """

    def __init__(self, capacity: int = 256) -> None:
        if capacity < 0:
            raise ValueError(
                f"capacity must be >= 0, got {capacity}"
            )
        self._capacity = capacity
        # ``OrderedDict[str, ExtractionResult | None]`` --
        # we keep the type as a generic dict because the
        # protocol is intentionally typed as object.
        # The LRU invariant: the most-recently-used entry is
        # at the end of the OrderedDict; the LRU is at the front.
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    def get(self, key: str) -> tuple[str, Any]:
        # Capacity 0 means the cache is disabled. Return
        # MISS but DON'T increment the miss counter --
        # the cache is "off" rather than "broken", and an
        # operator who sees ``cache_size=0`` in the admin
        # endpoint expects to see ``hits=0, misses=0``
        # (matching the historical contract preserved by
        # ``test_cache_size_zero_disables_caching``).
        if self._capacity == 0:
            return (MISS, None)

        if key not in self._data:
            self._misses += 1
            return (MISS, None)

        # Mark as most-recently-used by moving to the end.
        self._data.move_to_end(key)
        self._hits += 1
        value = self._data[key]
        if value is None:
            return (HIT_NONE, None)
        return (HIT, value)

    def set(self, key: str, value: Any) -> None:
        if self._capacity == 0:
            return  # cache disabled; no-op

        # ``value`` is either an ExtractionResult (real cache
        # hit) or None (negative cache entry for a DOI that
        # has no abstract). We store the value unchanged --
        # None stays None, ExtractionResult stays an object.
        # The sentinel-vs-None distinction only matters for
        # the Redis impl (where values are JSON-serialized).
        if key in self._data:
            # Update in place -- ``move_to_end`` refreshes LRU.
            self._data.move_to_end(key)
            self._data[key] = value
        else:
            self._data[key] = value
            # Evict the LRU if we're over capacity.
            while len(self._data) > self._capacity:
                # ``popitem(last=False)`` removes the first item
                # (the LRU -- least-recently used).
                self._data.popitem(last=False)

    def delete(self, key: str) -> bool:
        if key in self._data:
            del self._data[key]
            return True
        return False

    def clear(self) -> int:
        size = len(self._data)
        self._data.clear()
        # Counter reset: clear means "wipe the slate clean".
        # This matches the historical behavior in
        # ``AbstractEnricher.clear_cache``.
        self._hits = 0
        self._misses = 0
        return size

    def stats(self) -> CacheStats:
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            size=len(self._data),
            capacity=self._capacity,
        )

    def __repr__(self) -> str:
        return (
            f"InMemoryLRUCache(capacity={self._capacity}, "
            f"size={len(self._data)})"
        )
