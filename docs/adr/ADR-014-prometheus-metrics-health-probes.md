# ADR-014: Prometheus /metrics + JSON health probes

## Status

Accepted

## Context

The product surface has grown to include LLM
behaviours that need monitoring:

- The citation sanitizer's drop rate (how often the
  LLM emits `[paper:N]` with `N > len(citations)`).
- The title-fallback rate (how often the synthesis LLM
  omits the `# ` heading).
- The cache hit ratio (how often the abstract-enricher
  cache avoids re-fetching PubMed).

Operators need a way to graph these in Prometheus and
Grafana. The product surface also exposes a JSON
health probe for ops dashboards that don't speak
Prometheus.

## Decision

Three endpoints:

| Path | Format | Purpose |
|------|--------|---------|
| `/metrics` | Prometheus text exposition | Scrape target for Prometheus |
| `/health/sanitizer` | JSON | Citation sanitizer counters |
| `/health/title-fallback` | JSON | Title-fallback counters and rate |

All three are **in-process** — the counters live in
module-level singletons (one per metric family). This
is intentional: each worker process reports its own
counters, and Prometheus scrapes them all separately.

### Why hand-rolled, not `prometheus_client`?

`prometheus_client` is the canonical Python
Prometheus library. It is ~150 KB on disk (not a deal
breaker) but pulls in `prometheus_client` as a runtime
dependency and would force a re-bake of the minimal
Docker image.

The hand-rolled formatter
(`app/infrastructure/observability/prometheus_exposition.py`)
emits the same wire-format as `prometheus_client` for
the seven metrics we need (no histograms, no summaries,
no exemplars). It's ~150 LOC and has zero
dependencies.

If we later need histograms (e.g. PDF render latency
distribution), the right move is to add
`prometheus_client` rather than re-implement the
spec.

### Metrics emitted

```
citation_sanitizer_calls_total             counter
citation_sanitizer_dropped_total           counter
citation_sanitizer_calls_with_drops_total  counter
title_fallback_calls_total                 counter
title_fallback_injections_total            counter
title_fallback_rate                        gauge
title_fallback_window_size                 gauge
```

All counters are monotonic; gauges are recomputed on
scrape from the sliding-window counter history.

### Sliding window

The title-fallback rate is computed over the last
**20 calls** (`WINDOW_SIZE = 20`). This is a
trade-off: shorter windows are noisier; longer
windows lag the LLM behaviour change. 20 is enough
to see a sustained regression (the WARNING at >50%
triggers when the LLM is consistently failing, not on
a transient bad prompt).

## Consequences

### Positive

- Operators can graph the sanitizer rate in Grafana
  and see a spike when the LLM prompt regresses.
- The title-fallback WARNING log is a real
  alerting path (not just a metric that nobody
  watches).
- JSON `/health/*` endpoints work with any ops
  dashboard that doesn't speak Prometheus.

### Negative

- Module-level singletons mean per-worker counters
  (not a global total). For the Real-Redis integration
  test, this is fine; for production with N workers,
  Prometheus scrapes each worker and Grafana sums
  across the instance label.

## References

- Commit `4f7e93a feat(observability): Prometheus /metrics exposition + sanitizer telemetry`
- Commit `7fd5f46 fix(observability): title-fallback rate + warning at >50%`
- `app/infrastructure/observability/prometheus_exposition.py`
- `app/api/routes/health.py` — `/health/sanitizer`,
  `/health/title-fallback`, `/health`, `/metrics`
- `tests/unit/test_prometheus_metrics.py`
