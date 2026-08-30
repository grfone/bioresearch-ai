# ADR-011: Vancouver-style citation + anti-fabrication guard

## Status

Accepted

## Context

Biomedical literature uses **Vancouver style**: numbered
references, end-of-sentence placement, with the citation
order matching the bibliography order. The original
report payload emitted citations as raw `[paper:N]`
markers — visible to the user as literal text, not
rendered as numbered references.

A second, more dangerous problem emerged during
live-verify on real LLM outputs: the synthesis LLM
sometimes **invents citation indices beyond the
bibliography's range**. A 17-paper workspace would
emit `[paper:18]`, `[paper:19]`, ... up to
`[paper:24]` in a single body sentence. These
hallucinated indices would render as broken
hyperlinks in the frontend (no `#bib-18` exists) and
silently break the PDF bibliography's numbered list
ordering.

## Decision

Two changes:

1. **Frontend citation linkifier** —
   `frontend/src/lib/citationLink.ts`
   (`linkifyCitationMarkers`, `linkifyCitationDoi`)
   replaces `[paper:N]` with `[<a href="#citation-N">N</a>]`
   and any `https://doi.org/10.1234/abc.456` substring
   with a clickable DOI badge. The output is
   `Limitations` and `Future Research Directions` are
   wrapped via `renderItemWithCitationLinks` (a JSX
   walker, NOT `<ReactMarkdown>` per item — see ADR-009
   for why), which uses the same bold-underline styling
   as the executive summary (`text-primary font-bold
   underline hover:opacity-80`).

2. **Backend sanitizer at ingest** —
   `app/domain/services/citation_sanitizer.py`
   (called from the report-generation path) clamps any
   `[paper:N]` with `N > len(citations)` by either
   dropping the marker (standalone) or filtering the
   out-of-range entries from grouped markers
   (`[paper:18, paper:5]` → `[paper:5]`). Every call
   is logged with the running totals, exposed via
   `/health/sanitizer` (JSON) and `/metrics` (Prometheus)
   as `citation_sanitizer_calls_total`,
   `citation_sanitizer_dropped_total`, and
   `citation_sanitizer_calls_with_drops_total`.

The sanitizer runs **before** the report is persisted,
so the stored report payload already has clean
citation indices. The frontend never sees hallucinated
markers.

### Why not just hide the markers?

- The user needs to **see** the numbered references
  in the body so they can find the citation in the
  bibliography — Vancouver style is the entire
  purpose.
- A regex strip loses the citation → bibliography
  link, so the reader cannot navigate from in-text
  citation to its source.

### Why not just trust the LLM?

- Live-verify on 2026-08-30 saw 17/17 papers with at
  least one hallucinated citation. The LLM's prompt
  was hardened (commit `87dd725`), but the rate is
  non-zero. A defense-in-depth sanitizer is the right
  call.

## Consequences

### Positive

- Vancouver-style references work in both the UI and
  the PDF.
- The user can verify that the bibliography covers
  every cited paper by clicking the link.
- Hallucinated citation indices never reach the user.
- Operators can monitor the rate of dropped markers
  via `/health/sanitizer` and `/metrics`.

### Negative

- The frontend has a custom JSX walker
  (`renderItemWithCitationLinks`) instead of a
  one-liner `<ReactMarkdown>`. The walker is ~80 LOC
  and has its own test file
  (`citationRender.test.tsx`).

## References

- Commit `3bd1b5d fix(report): render Limitations/Future Work citations as clickable links`
- Commit `c93db9b fix(report): make Limitations/Future Work citation links bold + underlined`
- Commit `8cf20a3 fix(report): sanitise LLM-hallucinated citation markers at ingest`
- Commit `4f7e93a feat(observability): Prometheus /metrics exposition + sanitizer telemetry`
- `app/domain/services/citation_sanitizer.py`
- `frontend/src/lib/citationLink.ts`
- `frontend/src/lib/citationRender.tsx`
