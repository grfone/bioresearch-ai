# Multi-worker cache fragmentation — investigation findings

**Status**: investigation complete, remediation not yet chosen. See
["Recommended remediations"](#recommended-remediations) at the bottom
for the options.

**Date investigated**: 2026-08-19

**Author**: bioresearch-ai working session

---

## TL;DR

In `--workers 4` mode, each worker is a **separate Python process**,
and the `AbstractEnricher` LRU cache lives in a per-process module-level
global. The same DOI fetched N times costs up to **N redundant LLM API
calls** (plus N redundant CrossRef/OpenAlex fetches that bypass the meta-tag
regex). The `/admin/enricher-stats` endpoint reports per-worker counters
that are individually correct but collectively inconsistent — operators
lose system-wide cache visibility.

In our reproduction with 4 workers and a single popular DOI fetched 7
times, **3 MiniMax API calls** were made (when a single-worker baseline
would have made exactly 1). 4 fetches happened to land on warm workers
(so they got cache hits), but the cost is bounded above by
`num_workers × num_fetches_per_doi` in worst case.

---

## How we got here

### The current setup (default = single worker)

`Dockerfile` line in the production image:

```
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

No `--workers` flag ⇒ uvicorn runs **one worker process**, one `_identifier_resolver`
singleton, one `AbstractEnricher` LRU cache. This is fine in isolation
because Python's module-level globals persist for the lifetime of the
process.

### The container singleton

The `AbstractEnricher` LRU cache lives here (from
`app/config/container.py:386-408`):

```python
_identifier_resolver: IdentifierResolver | None = None

def get_identifier_resolver() -> IdentifierResolver:
    """..."""
    global _identifier_resolver
    if _identifier_resolver is None:
        # ...construct AbstractEnricher(llm_extractor=...)
        _identifier_resolver = IdentifierResolver(
            pubmed_provider=provider,
            abstract_enricher=enricher,
        )
    return _identifier_resolver
```

The `_identifier_resolver` variable is a **module-level global**. Inside
a single uvicorn worker process, this is held for the worker's lifetime,
the worker dies with it, and a new worker re-creates it from scratch.

This pattern was tested and validated for the single-worker case (see
PR `6c5543a` for the LRU cache, PR `216a4f8` for `/admin/enricher-stats`).

### What changes with `--workers N`

When uvicorn forks N worker processes (via `multiprocessing.Process`
internally), **each worker is a freshly-imported Python module**. The
`global _identifier_resolver` declaration is re-executed in each worker,
and each starts with `None`. The lazy `if _identifier_resolver is None:`
guard then runs once per worker, creating **N independent singleton
instances**, each with **its own LRU cache**.

Concretely, with `--workers 4`:

| Resource | Single worker | With --workers 4 |
|---|---|---|
| `_identifier_resolver` instances | 1 | 4 |
| `AbstractEnricher` LRU caches | 1 | 4 |
| CrossRef/OpenAlex fetch path | shared via cache | fragmented (4 caches) |
| LLM extractor instances (when `LLM_ABSTRACT_EXTRACTION_ENABLED=true`) | 1 | 4 |
| LLM API call cost for the same DOI cached N times | 1 call | up to 4 calls |
| `/admin/enricher-stats` total counters | system-wide | **per-worker** — operator loses the system-wide view |

## Reproduction

Set up on 2026-08-19 with the **just-shipped** `21fd43d` (Minimax
env var fix) and a real MiniMax key via `.env`:

```
APP_ENVIRONMENT=development
DEFAULT_LLM_PROVIDER=minimax
DEFAULT_LLM_MODEL=MiniMax-M3
MINIMAX_API_KEY=<redacted, sourced from ~/.hermes/.../minimax_api_key.txt>
PUBMED_EMAIL=verify-multi-worker@example.com
DATABASE_URL=sqlite:////app/data/bioresearch.db
ABSTRACT_ENRICHER_ENABLED=true
LLM_ABSTRACT_EXTRACTION_ENABLED=true
LOG_LEVEL=DEBUG
```

Built `:multi-worker-test` from the same Dockerfile:

```
docker build --target backend-minimal -t bioresearch-ai:multi-worker-test .
```

Launched with `--workers 4`, overriding the Dockerfile `CMD`:

```
docker run -d --name bioresearch-mw -p 8000:8000 \
  --env-file .env -v $(pwd):/app/data \
  bioresearch-ai:multi-worker-test \
  uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

Container boot (from `docker logs --tail 50 bioresearch-mw`):

```
INFO:     Started parent process [1]
INFO:     Started server process [8]
INFO:     Started server process [11]
INFO:     Started server process [10]
... AbstractEnricher config logged 4 times (=4 workers, each with its own enricher)
... started on uvicorn master PID 1, workers PID 7 8 9 10 11 (5 distinct Python3.12 processes)
```

PIDs verified via `/proc/<n>/comm` inside the container:

```
PID 1: uvicorn (master)
PID 7:  python3.12
PID 8:  python3.12
PID 9:  python3.12
PID 10: python3.12
PID 11: python3.12
```

(`PID 7` is the lifespan worker — the actual HTTP request handlers are
PIDs 8/9/10/11, the 4 request-handling workers.)

### Test 1: 7 fetches of the same DOI

We fetched `10.1016/j.cell.2024.01.001` (a Cell Press DOI whose meta-tag
regex returns nothing, forcing the LLM extractor) **7 times consecutively
over ~2 minutes** with a 30-second per-fetch timeout:

```
$ grep "(HIT|MISS) for 10.1016" /path/to/logs
11:10:10,132 MISS     # First hit lands on worker A — cache empty, LLM fires
11:10:18,228 MISS     # Second hit lands on worker B — B's cache empty, LLM fires AGAIN
11:10:28,975 HIT      # Third hit lands on worker C/D — already cached
11:10:30,613 HIT      # HIT
11:10:33,560 HIT      # HIT
11:10:48,930 MISS     # 6th hit: cycle back to A (or whichever worker expired oldest entry)
11:11:48,407 HIT      # Cycle back to a warm worker
```

**Result**: 7 fetches → **4 cache HIT, 3 cache MISS, 3 MiniMax API calls**.

Single-worker baseline would have been: **1 API call** (cache starts
empty, second fetch is a HIT forever).

Cost amplification factor: **3×** in this experiment; could be up to
**N×** in worst-case traffic patterns (where the most popular DOI is
randomly distributed across workers).

### Test 2: Admin endpoint inconsistency

20 successive `GET /admin/enricher-stats` calls. Each call is round-robined
to a different worker by uvicorn's load balancer:

```
$ for i in {1..20}; do curl -s http://localhost:8000/admin/enricher-stats; echo; done | sort | uniq -c
   18 {"hits":2,"misses":1,"size":1,"capacity":256}    ← most-common view: "warm" worker
    1 {"hits":0,"misses":1,"size":1,"capacity":256}    ← one worker that did the miss but not the hits
    1 {"hits":0,"misses":0,"size":0,"capacity":256}    ← a worker that hadn't been touched yet
```

**3 contradictory state views out of 20 calls.** This is the operator-experience
regression: an operator looking at `/admin/enricher-stats` literally has
no idea what the system as a whole is doing — only one worker's
local snapshot.

If they retry the call, they get a different worker's snapshot. Stats are
non-deterministic by worker-assignment roulette.

### Other affected endpoints

| Endpoint | Behavior in multi-worker |
|---|---|
| `GET /admin/enricher-stats` | per-worker; contradictory views. **Brittle**: an operator making a single call may see `size=0` and conclude the cache is empty when 3 other workers have entries. |
| `GET /admin/orchestrator-stats` | **NOT affected.** Counts workspaces by SQL `GROUP BY state` — that's a database query, shared across workers. The endpoint correctly reports the system-wide state. |
| `POST /admin/papers/refresh/{doi:path}` | per-worker; only invalidates the entry on the worker that handles the request. If the same DOI is cached on 3 other workers, those caches stay intact — **the force-refresh is partially effective** (3/4 of the cache stays). |
| `DELETE /admin/enricher-cache` | per-worker; only clears the worker that handles the request. **Same problem**: the clear-cache is partial (1 of 4 caches is cleared). |
| `GET /admin/papers/refresh/{doi:path}` returns `{doi, invalidate_returned: true}` even though 3 other workers' caches were never touched — **misleading**, suggests a complete clear when it isn't. |

The `/admin/papers/refresh/{doi:path}` partial-clear is the most operationally
dangerous — an operator who thinks they invalidated a stale cache entry
could be misled into trusting the result.

---

## Mitigation strategies (already-shipped code that helps)

These don't fix the fragmentation but they cap the worst-case damage
and limit the operational confusion:

1. **`/admin/orchestrator-stats` uses SQL GROUP BY → system-wide by design.**
   No fix needed.

2. **`/admin/papers/refresh/{doi:path}` returns the abstract length** of the
   re-fetched value, so an operator can verify the refresh worked.
   Doesn't fix the "3 other workers still have stale data" problem
   though — they'll be HIT but with the old cached value if the refresh
   just happened on this worker and the next request happens to land on
   a stale worker.

3. **The startup log line** `AbstractEnricher | llm_extractor=...` is now
   emitted 4 times in multi-worker mode (once per worker) — useful
   for **confirming** that workers are independent. Makes the bug
   *visible* rather than hiding it.

---

## Recommended remediations

These are options. **None** has been chosen and committed. The user
should pick one based on deployment scale and operational complexity.
The investigation is presented so the user can make an informed choice.

### Option A: Stay single-worker (no code change)

**When this is right**: small/mid-scale deployments, low concurrency,
LLM cost is acceptable.

**Cost**: 0 LOC changed. **Issue remains**: zero horizontal concurrency
within a single container. CPU-bound traffic (LLM extraction, summarization,
compare) cannot parallelize across cores.

**Action**: document the constraint in README/INSTALL, recommend
scaling with multiple containers instead.

### Option B: Redis-backed shared cache (recommended for production)

**When this is right**: any production deployment where multiple workers
are expected (HA, scale-out, GPU-box deployments).

**Approach**:
- Add a `redis>=5.0` dep to `requirements/minimal-requirements.txt`
- New abstraction: `cache_protocol.py` with `set/get/delete/clear_stats`
- Two implementations: `InMemoryLRUCache` (current behavior, default)
  and `RedisCache` (shares state across workers via Redis)
- `get_identifier_resolver` chooses based on `REDIS_URL` env var
- LLM API call results shared across workers → the "popular DOI
  fetched N times" problem reduces to **1 API call system-wide**
- `/admin/enricher-stats` and `/admin/orchestrator-stats` either:
  - Aggregate across workers using Redis SCAN
  - Or remain per-worker with a documented warning
- `/admin/papers/refresh/{doi:path}` and `DELETE /admin/enricher-cache`
  become **system-wide operations** via a single `DEL` or `FLUSHDB`

**Cost**: ~150-250 LOC, plus dependency on a Redis sidecar (already
common in production setups).

**Tradeoffs**:
- ✅ Fixes the fragmentation completely
- ✅ Fixes the admin endpoint consistency issue  
- ✅ Already a standard pattern (Redis, Memcached, etc.)
- ⚠️ Adds an external dependency (but the project already has `docker-compose.yml`
  for multi-service deploys, so adding Redis is straightforward)
- ⚠️ Network round-trips are slower than in-process dict access; cache
  hits should still be sub-ms but order of magnitude slower than
  in-memory dict

### Option C: Memcached instead of Redis

Same as B but with Memcached. Lighter weight, no Lua scripting (so
aggregate counter queries are clunkier). For this codebase specifically,
Redis is the better fit because we already use SQL; Redis fits more
naturally with the existing infrastructure story.

### Option D: Sticky sessions / pinning

**Approach**: instead of sharing cache, reduce the chance of duplicate
fetches by hashing the DOI to a worker. Worker that owns the hash
returns from its own cache; other workers could route there.

**Cost**: significant complexity in the load balancer. Doesn't fix the
underlying fragmentation — just shifts it. Worse than option B.

### Option E: Stateless design — move the cache to the database

**Approach**: every cache hit/miss hits the SQLite database.

**Cost**: extends SQLite with cache-eviction logic (LRU + size limits,
which the database doesn't natively support). Slow path. Doesn't fit
the architecture (cache is supposed to be a fast pre-database optimization).

### Option F: Disable LLM extractor in multi-worker mode

**When this is right**: a stopgap while evaluating B.

**Approach**: at boot, if `WORKERS > 1` and `LLM_ABSTRACT_EXTRACTION_ENABLED=true`,
log a warning and set `LLM_ABSTRACT_EXTRACTION_ENABLED=false` automatically.
The deterministic meta-tag regex still works fine in multi-worker
mode (each worker will fetch from the publisher, but the fan-out is
acceptable — fetches are cheap, the LLM calls were the expensive part).

**Cost**: 20 LOC; just a boot-time check.

**Tradeoffs**:
- ✅ Easy to ship, removes the cost amplification
- ✅ Deterministic path is genuinely functional under multi-worker
- ⚠️ Doesn't actually fix the cache fragmentation
- ⚠️ Users who want max coverage in multi-worker setups lose it

---

## What we did NOT change

Nothing in the codebase has been modified as a result of this
investigation. The container was torn down, the test image was deleted,
the `.env` file was removed, and no commits were made.

The user should pick a remediation and the appropriate commits will
land in a follow-up session.

---

## How to re-run this investigation

From `~/PycharmProjects/bioresearch-ai`:

```bash
# 1. Build with real MiniMax key
cat > .env <<EOF
APP_ENVIRONMENT=development
DEFAULT_LLM_PROVIDER=minimax
DEFAULT_LLM_MODEL=MiniMax-M3
MINIMAX_API_KEY=$(cat ~/.hermes/profiles/job-finder-agent-profile/secrets/minimax_api_key.txt)
PUBMED_EMAIL=multi-worker@example.com
DATABASE_URL=sqlite:////app/data/bioresearch.db
ABSTRACT_ENRICHER_ENABLED=true
LLM_ABSTRACT_EXTRACTION_ENABLED=true
LOG_LEVEL=DEBUG
EOF
chmod 600 .env

# 2. Build + run with --workers 4 (override CMD)
docker build --target backend-minimal -t bioresearch-ai:multi-worker-test .

docker run -d --name bioresearch-mw -p 8000:8000 \
  --env-file .env -v "$(pwd):/app/data" \
  bioresearch-ai:multi-worker-test \
  uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

# 3. Wait for health
for i in $(seq 1 30); do
  curl -fs http://localhost:8000/health 2>/dev/null | grep -q healthy && break
  sleep 1
done

# 4. Reproduce
WS_ID=$(curl -s -X POST http://localhost:8000/workspaces \
  -H "Content-Type: application/json" \
  -d '{"question":"multi-worker fragmentation test"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['workspace_id'])")
for i in $(seq 1 7); do
  curl -s -X POST "http://localhost:8000/workspaces/$WS_ID/papers/fetch?identifier=10.1016/j.cell.2024.01.001" \
    --max-time 30 -o /dev/null
done

# 5. Inspect
docker logs --tail 200 bioresearch-mw 2>&1 | grep -E "(HIT|MISS) for 10.1016|LLM extraction|LLMExtractor:"

# 6. Cleanup
docker rm -f bioresearch-mw
docker rmi -f bioresearch-ai:multi-worker-test
rm -f .env
```

The expected output for step 5 is a mix of HIT and MISS lines (and
multiple `LLMExtractor` log lines), demonstrating the fragmentation.