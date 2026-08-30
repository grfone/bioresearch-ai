# ADR-013: H1 title fallback for the synthesis LLM

## Status

Accepted

## Context

The synthesis LLM emits a Markdown body for the
report. The first non-blank line is expected to be the
`# <title>` heading, which becomes the report's
`title` field. Live-verify on 2026-08-29 found the
LLM omits the heading **~30% of the time** — the body
starts directly with a paragraph, and the report's
title field is `None` (or, in the worst case, the
first sentence is duplicated as both the body and the
title).

The original fallback path was:

```python
title = body_lines[0] if body_lines else None
```

— which captured the first line as both the title and
the first body line, producing the duplication bug
seen in PDF output (PDF title: "The landscape of
Alzheimer's disease (AD) biomarkers has evolved
rapidly, with new..." with the same line appearing as
the first body paragraph).

## Decision

Add a deterministic **title fallback** in
`app/infrastructure/llm/title_fallback.py`:

1. **Detect missing title.** If the first non-blank
   body line does not start with `# `, the title is
   missing.
2. **Derive a title from the first sentence.** Take
   the first sentence of the first body paragraph,
   then **truncate at the last content word** (not at
   a dangling conjunction, preposition, or relative
   pronoun). The fallback's `_TITLE_STOPWORDS` set
   covers English stopwords plus biomedical-specific
   ones ("associated", "compared", "demonstrated").
3. **Inject the H1 line** at the top of the body so
   downstream PDF / LaTeX / frontend rendering all see
   the same Markdown.
4. **Idempotent.** If the title already exists, the
   function is a no-op.

### Telemetry

Every call increments an in-process counter exposed
via:

- `/health/title-fallback` — JSON `{calls, injections,
  rate, window_size}` for ops dashboards
- `/metrics` — Prometheus
  `title_fallback_calls_total`,
  `title_fallback_injections_total`, plus a gauge
  `title_fallback_rate` and `title_fallback_window_size`
  (sliding 20-call window)

When the rate exceeds **50%** over the sliding
window, a WARNING is logged:

```
WARNING: title-fallback rate 60.0% over last 20 calls
(synthesizer prompt may need revisiting)
```

The threshold is intentionally low (the LLM should
emit the heading reliably — fallback is a safety net,
not the primary path).

### Why not fix the prompt?

We did (commit `87dd725`) — the prompt now includes an
emphatic directive to emit the `# <title>` heading on
the first line. The fallback is defense-in-depth for
when the directive still slips through (LLM rate of
omission dropped from ~30% to ~5% with the directive).

## Consequences

### Positive

- Every report has a real title (no `Untitled`, no
  duplicated first sentence).
- The PDF and LaTeX outputs render the same title the
  frontend shows.
- Operators see the fallback rate in real time and
  can revisit the prompt if it creeps above 50%.

### Negative

- The title may not be a perfect noun phrase if the
  first sentence is unusually long. The truncation
  heuristics are tuned for English; non-English bodies
  may need locale-specific stopword lists later.

## References

- Commit `b00b34a fix(report): inject H1 title fallback when synthesis LLM omits it`
- Commit `7fd5f46 fix(observability): title-fallback rate + warning at >50%`
- `app/infrastructure/llm/title_fallback.py`
- `app/api/routes/health.py` — `/health/title-fallback`
- `app/infrastructure/observability/prometheus_exposition.py`
- `tests/unit/test_title_fallback.py`
