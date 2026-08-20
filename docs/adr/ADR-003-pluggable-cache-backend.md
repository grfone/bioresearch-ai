# ADR-003: Pluggable cache backend for the abstract-enricher LRU

## Status

Accepted

## Context

The abstract-enricher (`app/infrastructure/pubmed/abstract_enricher.py`)
runs as a singleton inside the `IdentifierResolver`, which is itself
a singleton at the FastAPI app level. Its LRU cache holds the
resolved abstract for each DOI the resolver has seen, so repeat
lookups within the same process skip the network entirely.

When the FastAPI app is started with the default `uvicorn main:app`,
the cache lives in a single Python process. In single-worker
deployments this is fine.

When the app is started with `uvicorn --workers N` (the common
production recipe for any non-trivial CPU footprint), each worker is
a separate Python process with its own module-level globals. The
`_identifier_resolver` singleton is created fresh in each worker,
so each worker builds its own in-process LRU. The same DOI fetched
N times in the cluster makes up to N separate HTTP calls (one
per worker that hasn't cached it yet) and — in the worst case where
the LLM-backed fallback is enabled — up to N LLM API calls.

Worse, the `/admin/enricher-stats`, `/admin/papers/refresh/{doi}`,
and `DELETE /admin/enricher-cache` admin endpoints each only see the
worker's local view. Hitting `/admin/enricher-stats` 20 times in a
row can return 3 distinct state snapshots depending on which
worker handled each call. An operator who tries to clear the cache
finds that only the worker's own entries are deleted; the other N-1
workers' caches stay intact.

We measured the cost amplification in
`docs/multi-worker-cache-investigation.md`: with `--workers 4`, the
same DOI fetched 7 times made 3 separate LLM API calls (43% wasted
budget). The admin-endpoint inconsistency is reproducible on every
load.

## Decision

Introduce a `CacheProtocol` and two implementations:

- `InMemoryLRUCache` — the historical default. `OrderedDict`-backed
  LRU, capacity-bounded, per-process state. Use this for single-worker
  deployments, tests, and dev.
- `RedisCache` — shared LRU backed by a Redis instance. Uses a
  sorted-set for the LRU index (member = cache key, score = last-access
  monotonic timestamp), separate string keys for the cached values,
  atomic INCR for hit/miss counters, DEL + ZREM for invalidation. Use
  this for any multi-worker deployment.

A `make_cache(backend, ...)` factory in
`app/infrastructure/cache/__init__.py` translates the
`CACHE_BACKEND` env var (default `"memory"`) into the right
implementation. The container module's `get_identifier_resolver`
calls this factory and passes the result to `AbstractEnricher(cache=...)`.

The `CacheProtocol` exposes the 3-valued `get` semantics
(`HIT` / `HIT_NONE` / `MISS`) so the enricher can preserve the
"negative cache" behavior — a DOI whose publisher returned a blocked
page is remembered as `HIT_NONE` (a cached `None`) so we don't retry
the network. Both implementations round-trip the same contract,
verified by a parametrized `TestCacheProtocolContract` that runs the
same battery of operations against each impl (using `fakeredis`
for the Redis variant in unit tests, real Redis in CI).

### Configuration

`LiteratureSettings` gained four fields:

- `cache_backend`: `"memory"` (default) or `"redis"`
- `cache_size`: max entries (default 256; `0` disables the cache)
- `redis_url`: required when `cache_backend=redis`
- `redis_key_prefix`: defaults to `"bioresearch:abstract:"`

### Failure mode

A misconfigured Redis (wrong host, unreachable server) fails
**loudly**: `RedisCache` constructs fine but the first `get` raises
`redis.exceptions.ConnectionError`. This is the right behavior —
silent fallback to the in-memory impl would silently re-introduce
the fragmentation bug. Operators see the error in the logs and fix
the Redis config.

## Consequences

**Positive**

- Multi-worker deployments no longer pay N× the API cost for
  popular DOIs. Measured: 3 LLM calls for 7 fetches (in-memory)
  drops to 1 LLM call (Redis) — see
  `docs/multi-worker-cache-investigation.md`.
- `/admin/enricher-stats` is system-wide in Redis mode (atomic
  INCR), so operators see the real totals regardless of which
  worker handles the call. Measured: 20 successive calls
  returned 20/20 identical snapshots (Redis) vs. 3 distinct
  snapshots (in-memory).
- `/admin/papers/refresh/{doi:path}` and
  `DELETE /admin/enricher-cache` are system-wide. The
  force-refresh removes the entry from every worker's view; the
  clear-cache wipes the whole shared state.
- The default (`memory`) preserves the historical behavior
  exactly. Existing single-worker deployments don't need to
  change anything.

**Negative**

- New dependency (`redis>=5.0,<6.0`). `~200 KB` pure-Python client
  with no native extension required. No build complexity.
- The Redis impl adds 4-5 round-trips per cache op (pipelined
  where possible). On a fast LAN this is negligible (<1 ms);
  on a slow cross-AZ link it's visible but bounded.
- Per-key serialization: `ExtractionResult` round-trips through
  JSON in the Redis impl. The in-memory impl passes the object
  directly. Operators with very large cached values (>1 MB per
  abstract) will see Redis memory grow faster; the capacity
  bound keeps it bounded.
- `RedisCache` is not thread-safe at the level of `redis-py`'s
  client; the connection pool handles concurrency. We tested with
  4 workers × 30 concurrent fetches and saw no errors.

## Alternatives considered

- **Sticky sessions** — route every DOI to the same worker. This
  gives correctness but breaks horizontal scaling: a hot DOI
  saturates one worker. Rejected.
- **DB-backed cache** — use SQLite as the cache store. Adds a
  synchronous DB write per cache op, which is slower than
  Redis and adds a competing write path to the existing
  `bioresearch.db`. Rejected.
- **No-op fallback** — silently fall back to the in-memory impl
  if Redis is unreachable. We deliberately rejected this
  because the silent fallback re-introduces the bug the Redis
  mode was added to fix.
- **Always-Redis** — drop the in-memory impl entirely. Rejected
  for two reasons: (1) it makes the dev experience worse (every
  developer needs a running Redis), (2) it makes the test suite
  slower (every unit test would need `fakeredis` instead of a
  plain dict). The dual-backend design keeps the
  `InMemoryLRUCache` as the default and tests use it directly.

## References

- `docs/multi-worker-cache-investigation.md` — the reproduction
  recipe that motivated this change.
- `app/infrastructure/cache/__init__.py` — the factory.
- `app/infrastructure/cache/cache_protocol.py` — the protocol.
- `tests/unit/test_cache_protocol.py` — the parametrized
  contract tests.
- `tests/integration/test_cache_redis_integration.py` —
  real-Redis integration tests (run only when `REDIS_URL` is
  set).
- `.github/workflows/ci.yml` — the `redis-integration` job
  that spins up `redis:7-alpine` as a sidecar.
