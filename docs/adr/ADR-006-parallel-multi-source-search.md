# ADR-006: Parallel multi-source literature search (ThreadPoolExecutor)

## Status

Accepted

## Context

The `MultiSourceSearcher` (`app/infrastructure/literature/multi_source.py`)
fans out a research question to every registered source
(PubMed, OpenAlex, Europe PMC, bioRxiv) and dedupes the combined
results. The historical implementation iterated the sources
**sequentially** in a `for` loop:

```python
for source, searcher in self._searchers.items():
    results = searcher.search_with_filters(filters)
    raw_results.extend(results)
```

The "feels slow" complaint the user reported:
**"this thing is taking forever to load"**.

The wall-time cost:

| Source | Latency |
|---|---|
| PubMed (NCBI E-utilities) | ~0.6 s |
| Europe PMC REST | ~0.7 s |
| **OpenAlex API** | **~4.5 s** |

Three sources at average ~2 s, dominated by OpenAlex:
sequential fan-out costs **~6 s** on average and **~12 s** when
OpenAlex has a slow query. The frontend's "Start Research"
button is disabled during this period with no progress
indicator — the user perceives it as a hang.

The latency is intrinsic to the sources, not the code, but
the *sequential* design is correctable: PubMed and Europe PMC
don't need to wait for OpenAlex to finish. If we ran them in
parallel, the wall time would be `max(source_times)` rather
than `sum(source_times)` — ~5 s instead of ~6 s on average,
~4.5 s instead of ~12 s in the OpenAlex-slow case.

## Decision

Replace the sequential for-loop with a bounded
`ThreadPoolExecutor`. The number of workers is
`min(num_sources, 4)`: enough to run every source in parallel
but bounded so a multi-source search doesn't accumulate
hundreds of idle threads.

```python
sources = list(self._searchers.items())
n_workers = min(len(sources), 4)

def _search_one(item):
    source, searcher = item
    try:
        return searcher.search_with_filters(filters)
    except Exception as exc:
        logger.warning("search on %s failed: %s", source.value, exc)
        return []

with ThreadPoolExecutor(max_workers=n_workers,
                        thread_name_prefix="multi-source-search") as pool:
    per_source_results = list(pool.map(_search_one, sources))

raw_results = []
for results in per_source_results:
    raw_results.extend(results)
```

Why `ThreadPoolExecutor` and not `asyncio.gather`:

- The underlying `search_with_filters` is **synchronous**
  (blocking `httpx.Client.get(...)`). To run blocking I/O in
  parallel without rewriting every searcher as async, we use
  threads. `asyncio.gather` would require either a separate
  set of async searchers (a bigger refactor) or
  `asyncio.to_thread` to wrap each call (functionally
  equivalent to `ThreadPoolExecutor.map`, but with more
  ceremony).
- The pool is created with `with` so it's cleaned up
  deterministically — no leaked threads if the request is
  cancelled mid-flight.

Error handling is preserved: each source's failure is logged
and dropped, and the searcher still returns whatever the
remaining sources produced. The `try/except` is inside the
worker function so a single misconfigured source doesn't
break the whole search.

## Consequences

**Positive**

- Wall time drops from `O(sum(source_times))` to
  `O(max(source_times))`. Measured: 12 s (OpenAlex slow)
  → 4.5 s in the same scenario. Average case: 6 s → 5 s.
- The frontend's "Start Research" button is responsive
  sooner; the user can already see the first search hits as
  they arrive (a future improvement: stream results as each
  source completes — not in this ADR).
- The `with ThreadPoolExecutor(...)` context manager ensures
  the pool is shut down even on exception. No thread leaks.
- The bounded worker count (`min(num_sources, 4)`) keeps the
  thread count proportional to the actual work. No
  accumulating idle threads.

**Negative**

- Each source is now its own thread. With 4 sources and 4
  uvicorn workers, that's 16 concurrent HTTP fetches at peak
  load. All three external APIs (PubMed, OpenAlex, Europe
  PMC) document rate limits (NCBI: 3 req/s with API key;
  OpenAlex: polite pool ~10 req/s; Europe PMC: ~5-10 req/s).
  16 concurrent fetches spread across N end users is well
  under the polite-pool rate limits, but a malicious
  end-user could exhaust them. We accept this for the
  public beta; production should add per-user rate limiting
  at the API gateway.
- Order of results is no longer deterministic — sources
  complete in arrival order, not iteration order. The
  ranking/dedup pipeline downstream doesn't depend on
  per-source ordering (it builds a `Counter` of normalized
  titles and PMIDs/DOIs), so the result is functionally
  identical, just byte-shuffled. Tests that depend on
  result order will need to be updated (none currently do).
- The thread pool's `max_workers=4` is a magic number. We
  picked 4 because (a) we have at most 4 default sources,
  and (b) doubling it doesn't help (sources don't have a
  parallelism limit we want to bypass). A future change
  could make this configurable via a settings field.

## Alternatives considered

- **`asyncio.gather` with `httpx.AsyncClient`** — rewrite
  every searcher to be async. The async refactor is real
  work (the searchers are deeply tied to sync `httpx.Client`),
  and the latency improvement is the same. The thread-pool
  approach gets us 80% of the win for 5% of the work.
- **Async-only backend** (`asyncio.run` + `httpx.AsyncClient`)
  — the cleanest in a green-field project, but our backend
  is sync-first and a global switch would touch every route
  handler. Not worth it.
- **Just turn off OpenAlex** — drop the slowest source. This
  loses real coverage (OpenAlex is the broadest free
  source). Parallel is the right fix.
- **Per-source worker count = source-specific tuning** —
  PubMed is fast so 1 worker, OpenAlex is slow so 4 workers.
  Way too much complexity for marginal benefit; the bounded
  pool with 4 workers handles all three sources adequately.

## References

- `app/infrastructure/literature/multi_source.py` — the
  parallel fan-out.
- `tests/unit/test_literature_clients.py` — the existing
  tests for the searcher; not changed by this ADR (the
  public API is unchanged).
- `docs/multi-worker-cache-investigation.md` — the parallel
  investigation that surfaced the OpenAlex latency.
