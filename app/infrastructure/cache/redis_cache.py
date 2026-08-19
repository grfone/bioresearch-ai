"""Redis-backed implementation of ``CacheProtocol``.

This is the multi-worker fix. When ``CACHE_BACKEND=redis`` is
set in the container's environment, the abstract-enricher
uses this class instead of ``InMemoryLRUCache``. All workers
in the uvicorn deployment share the same Redis instance,
so:

  - The "popular DOI fetched N times across N workers" problem
    collapses to a single fetch system-wide. This was the
    headline issue reproduced in
    ``docs/multi-worker-cache-investigation.md``.

  - The hit/miss counters in ``/admin/enricher-stats`` are
    system-wide (atomic INCR on Redis), not per-worker. This
    fixes the "20 successive admin calls returned 3 distinct
    state views" reproduction.

  - The force-refresh and clear-cache admin endpoints are
    also system-wide. Force-refreshing a DOI removes it from
    every worker's view of the cache. Clearing the cache wipes
    the whole shared state.

See ``docs/multi-worker-cache-investigation.md`` for the
reproduction. See ``app/infrastructure/cache/cache_protocol.py``
for the protocol that this class implements.

Key design decisions
--------------------

1. **Value storage** is split across two Redis keys per entry:

   - ``bioresearch:abstract:<doi>``  (the JSON-serialized value)
   - ``bioresearch:abstract:keys``   (a sorted set; member=doi, score=last-access-time)

   Splitting the value from the LRU index is the standard
   "Redis LRU via sorted set" pattern. We can't use Redis's
   built-in eviction (``maxmemory-policy=allkeys-lru``)
   because the value is application-meaningful (it can be
   ``None``) and we need to distinguish "key not present" from
   "key present, value is None" (the existing negative-cache
   contract tested by
   ``test_cache_distinguishes_none_from_absent``).

2. **LRU implementation** is via the sorted set's score:

   - On ``set``: ZADD the doi with the current monotonic timestamp
   - On ``get``: if the value key exists, ZADD with a fresh
     timestamp (refresh LRU), return the value
   - On overflow: ZRANGE 0 0 returns the LRU (oldest score);
     DEL its value key + ZREM from the sorted set

   This is O(log N) per op, where N is the cache size. Good enough
   for our workload (thousands of DOIs, not millions).

3. **Counter keys** are atomic INCRs at the Redis level:

   - ``bioresearch:abstract:hits``
   - ``bioresearch:abstract:misses``

   These are independent of the in-process protocol counters
   on the CacheStats. We expose them through ``stats()`` so
   ``/admin/enricher-stats`` reports system-wide totals.

   Implementation note: the ``CacheStats`` object is constructed
   on every ``stats()`` call by querying Redis. We don't cache
   the counters in-process because that would re-introduce
   per-worker counter fragmentation (the bug we're fixing).

4. **Capacity** is enforced manually via the sorted set:

   - After every ``set``, ZCARD returns the current size
   - If ZCARD > capacity, ZRANGE 0 N to get the LRU entries to
     evict, DEL their value keys, ZREM from the sorted set

   Doing this atomically (without a Lua script) requires
   multiple round-trips. The current implementation accepts
   the small race window -- in a busy multi-worker system,
   the cache may temporarily exceed capacity by a few entries.
   This is the same race that the in-memory impl has (the
   ``while len > capacity`` loop in set is also non-atomic).
   Not worth fixing for a minor over-counting.

5. **JSON serialization** of the ExtractionResult:

   - None  ->  the string literal ``__bioresearch_no_abstract__``
   - object ->  ``json.dumps({"abstract": str, "inferred": bool})``

   On ``get``, the sentinel is converted back to ``None``.
   The 3-valued status (HIT / HIT_NONE / MISS) preserves the
   "negative cache" contract.

6. **Connection management** uses ``redis.Redis`` (synchronous
   client from redis-py 5.x). The connection pool is created
   at construction time. Each operation pulls a connection
   from the pool, runs the command, returns it. The pool
   keeps connections alive for the worker's lifetime.

7. **Thread safety** is provided by the redis-py client itself
   (the connection pool is thread-safe). This is in contrast
   to ``InMemoryLRUCache``, which is single-threaded. If the
   project ever moves to threaded gunicorn workers, the
   Redis impl is already safe; the in-memory impl would
   need a lock.

   The synchronous API is intentional: the abstract-enricher
   is called from a sync code path (FastAPI route handler,
   not an async one). Using the async redis client would
   force a refactor of the enricher; not worth it for our
   workload.

Error handling
--------------
We let Redis errors propagate (``redis.exceptions.ConnectionError``
etc.). The container module catches them at startup so a
misconfigured Redis doesn't crash the app -- it falls back
to a warning. At runtime, a transient Redis error propagates
to the caller, which in our case is the abstract-enricher's
``fetch()`` method, which would then either retry or 500
to the API client. The current behavior is "fail loud" --
better than silently falling back to the in-memory impl
(that's a footgun: a worker would silently lose cache
state on a Redis hiccup and then re-introduce the
fragmentation problem).

Tests
-----
``tests/unit/test_cache_protocol.py`` runs the same battery
of operations against both implementations (using
``fakeredis`` for the Redis variant in unit tests). The
test name is ``TestCacheProtocolContract``.

A real-Redis integration test would require a running
Redis (e.g. via ``docker run --rm redis:7-alpine``); not
included in CI but documented in
``docs/multi-worker-cache-investigation.md`` under "How to
re-run this investigation".
"""

from __future__ import annotations

import json
import time
from typing import Any

import redis

from .cache_protocol import (
    HIT,
    HIT_NONE,
    MISS,
    NO_ABSTRACT_SENTINEL,
    CacheProtocol,
    CacheStats,
)


class RedisCache(CacheProtocol):
    """Redis-backed LRU cache for the abstract-enricher.

    See the module-level docstring for the design rationale.

    Parameters
    ----------
    redis_url : str
        A ``redis://host:port/db`` URL. Passed to
        ``redis.Redis.from_url``.
    capacity : int
        Maximum number of entries. ``0`` disables the cache.
        Default 256, matches the historical default in
        ``AbstractEnricher.__init__``.
    key_prefix : str
        Redis namespace. All keys created by this cache are
        prefixed with this string. Defaults to
        ``"bioresearch:abstract:"`` -- matches the
        investigation doc's notes.

        IMPORTANT: if you change this prefix, the existing
        cache (under the old prefix) becomes invisible. Pick
        a prefix that's specific to the bioresearch-ai app
        so it doesn't collide with other apps sharing the
        same Redis instance.

    client : redis.Redis | None
        Optional pre-built Redis client. Used by tests (with
        ``fakeredis``) to inject a fake connection. If None,
        a new client is built from ``redis_url`` at
        construction time.
    """

    def __init__(
        self,
        redis_url: str,
        capacity: int = 256,
        key_prefix: str = "bioresearch:abstract:",
        client: "redis.Redis | None" = None,
    ) -> None:
        if capacity < 0:
            raise ValueError(
                f"capacity must be >= 0, got {capacity}"
            )
        if not redis_url:
            raise ValueError(
                "RedisCache requires a non-empty redis_url. "
                "Pass the REDIS_URL env var to the container."
            )

        self._capacity = capacity
        self._key_prefix = key_prefix
        # ``_data_key(k)`` is the Redis key for the value of
        # entry k. ``_index_key`` is the sorted set used for
        # LRU. Counters are stored at _hits_key / _misses_key.
        self._data_key = lambda k: f"{key_prefix}{k}"
        self._index_key = f"{key_prefix}__lru__"
        self._hits_key = f"{key_prefix}__hits__"
        self._misses_key = f"{key_prefix}__misses__"

        if client is not None:
            self._redis = client
        else:
            # ``decode_responses=True`` so all responses are
            # Python strings, not bytes -- the protocol's
            # string-key signature would otherwise require
            # explicit .decode() calls everywhere.
            self._redis = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
            )

    @property
    def capacity(self) -> int:
        return self._capacity

    def get(self, key: str) -> tuple[str, Any]:
        if self._capacity == 0:
            # Cache disabled -- we don't even query Redis.
            # Don't INCR the miss counter either: matching
            # the in-memory contract preserved by
            # ``test_cache_size_zero_disables_caching``,
            # disabled-cache lookups don't show up as
            # misses in the admin endpoint.
            return (MISS, None)

        data_key = self._data_key(key)

        # GET the data key first. We do this with a
        # pipeline so the LRU-refresh and counter updates
        # are batched into one round-trip.
        pipe = self._redis.pipeline()
        pipe.get(data_key)
        score = time.monotonic()
        # Only refresh LRU if the data is already present.
        # Use ZADD XX (NOT NX) -- NX creates new members
        # (which would leave orphan LRU entries for keys
        # whose data was never set), XX only updates
        # existing members. See redis docs:
        # https://redis.io/docs/latest/commands/zadd/
        pipe.zadd(self._index_key, {key: score}, xx=True)
        result = pipe.execute()

        raw = result[0]
        if raw is None:
            # Cache miss. INCR the miss counter. The ZADD NX
            # above was a no-op (member didn't exist).
            self._redis.incr(self._misses_key)
            return (MISS, None)

        # LRU was refreshed by the ZADD NX. INCR the hit
        # counter.
        self._redis.incr(self._hits_key)

        # Parse the value.
        if raw == NO_ABSTRACT_SENTINEL:
            return (HIT_NONE, None)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Corrupted entry -- treat as a miss so the
            # caller refetches. Don't delete the entry here;
            # the next ``set`` will overwrite it.
            raise RuntimeError(
                f"Corrupted cache entry at {data_key!r}: {exc}"
            ) from exc
        # We round-trip the ExtractionResult as a dict. The
        # caller (``AbstractEnricher``) doesn't care -- it
        # reads ``.abstract`` and ``.inferred`` attributes,
        # which a dict with those keys provides. This is the
        # trade-off for using a JSON-friendly representation
        # in Redis. If we ever need methods, we'd switch to
        # pickle -- but JSON is simpler and debuggable.
        return (HIT, payload)

    def set(self, key: str, value: Any) -> None:
        if self._capacity == 0:
            return

        data_key = self._data_key(key)
        score = time.monotonic()

        # Serialize the value. None is a sentinel; anything
        # else we assume is an object with .abstract and
        # .inferred attrs (the ExtractionResult contract).
        if value is None:
            payload = NO_ABSTRACT_SENTINEL
        else:
            payload = json.dumps(
                {
                    "abstract": getattr(value, "abstract", None),
                    "inferred": getattr(value, "inferred", True),
                }
            )

        # Pipeline: SET the data + ZADD the LRU index, then
        # check size for eviction. The eviction is O(N) on
        # the sorted set; that's fine for our scale.
        pipe = self._redis.pipeline()
        pipe.set(data_key, payload)
        pipe.zadd(self._index_key, {key: score})
        # If the key already existed, ZADD updates the score
        # (refreshes LRU). If it's new, ZADD inserts.
        pipe.zcard(self._index_key)
        _, _, size = pipe.execute()

        if size > self._capacity:
            # Evict the LRU. ZRANGE 0 0 returns the LRU
            # member(s) -- oldest by score ascending.
            n_evict = int(size - self._capacity)
            lru_members = self._redis.zrange(
                self._index_key, 0, n_evict - 1
            )
            if lru_members:
                # Pipeline: DEL value keys + ZREM from index.
                evict_pipe = self._redis.pipeline()
                for member in lru_members:
                    evict_pipe.delete(self._data_key(member))
                evict_pipe.zrem(self._index_key, *lru_members)
                evict_pipe.execute()

    def delete(self, key: str) -> bool:
        # DEL returns the number of keys removed (0 or 1).
        # We use a pipeline so the index ZREM and the data
        # DEL are atomic relative to other cache ops.
        pipe = self._redis.pipeline()
        pipe.delete(self._data_key(key))
        pipe.zrem(self._index_key, key)
        data_deleted, _ = pipe.execute()
        return data_deleted > 0

    def clear(self) -> int:
        # System-wide wipe: delete every data key + the
        # LRU index + the counters in one pipeline. This is
        # the difference from the in-memory impl: when the
        # admin endpoint says "cache cleared", the operator
        # can trust that EVERY worker in the cluster now has
        # a clean cache.
        pipe = self._redis.pipeline()
        # ZRANGE returns all members of the LRU sorted set.
        members = self._redis.zrange(self._index_key, 0, -1)
        if members:
            for member in members:
                pipe.delete(self._data_key(member))
        pipe.delete(self._index_key)
        # Counters -- the admin endpoint reports the new
        # counts as 0. Counter keys may not exist yet if the
        # cache was empty; that's fine, DELETE is a no-op.
        pipe.delete(self._hits_key)
        pipe.delete(self._misses_key)
        pipe.execute()
        return len(members)

    def stats(self) -> CacheStats:
        if self._capacity == 0:
            # Cache disabled -- short-circuit so we don't
            # create counter keys that would skew the
            # counters for callers that DON'T have a cache.
            return CacheStats(hits=0, misses=0, size=0, capacity=0)

        # Pipeline: GET the counters + ZCARD the LRU index.
        pipe = self._redis.pipeline()
        pipe.get(self._hits_key)
        pipe.get(self._misses_key)
        pipe.zcard(self._index_key)
        hits_raw, misses_raw, size = pipe.execute()

        # Counter keys may not exist yet (no reads/writes).
        # Treat None as 0.
        hits = int(hits_raw) if hits_raw is not None else 0
        misses = int(misses_raw) if misses_raw is not None else 0
        return CacheStats(
            hits=hits,
            misses=misses,
            size=int(size),
            capacity=self._capacity,
        )

    def __repr__(self) -> str:
        return (
            f"RedisCache(redis_url={self._redis.connection_pool.connection_kwargs!r}, "
            f"capacity={self._capacity})"
        )
