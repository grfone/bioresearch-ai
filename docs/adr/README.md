# Architecture Decision Records (ADR)

This directory contains Architecture Decision Records (ADRs) for BioResearch AI.

An ADR documents an important architectural decision, the context in which it was made, the available alternatives, and the rationale behind the chosen solution.

These documents serve as long-term project documentation and help future contributors understand the evolution of the system.

## Index

- [ADR-001: Adopt Clean Architecture](ADR-001-adopt-clean-architecture.md) — separation of
  concerns across domain / application / infrastructure / API layers.
- [ADR-002: Adopt Domain-Driven Design](ADR-002-adopt-domain-driven-design) — the
  domain layer is the source of truth for entities, value objects, and invariants.
- [ADR-003: Pluggable cache backend for the abstract-enricher LRU](ADR-003-pluggable-cache-backend.md) —
  in-memory vs Redis; the multi-worker fragmentation fix.
- [ADR-004: Section-based abstract extraction](ADR-004-section-based-abstract-extraction.md) —
  prefer `<section id="Abs[0-9]+">` over `<meta name="description">`; strip trailing `"..."`.
- [ADR-005: Multi-identity paper deduplication](ADR-005-multi-identity-paper-dedup.md) —
  PMID / DOI / title; the two-tier dedup algorithm in the frontend store.
- [ADR-006: Parallel multi-source literature search](ADR-006-parallel-multi-source-search.md) —
  `ThreadPoolExecutor` for parallel fan-out; OpenAlex no longer blocks the other sources.
- [ADR-007: Configurable PDF upload size cap](ADR-007-configurable-pdf-upload-cap.md) —
  `PDF_UPLOAD_MAX_BYTES` env var, 50 MB default, 200 MB hard cap.
- [ADR-008: One-click report from PAPERS_RETRIEVED](ADR-008-one-click-report-from-papers-retrieved.md) —
  drop the "Summarize first" gate; orchestrator auto-summarises when needed.
- [ADR-009: PUBLISHING FSM state for PDF export](ADR-009-publishing-state.md) —
  twelve-state FSM with the new transient `PUBLISHING` state, a hand-rolled
  PDF 1.4 generator, and the four-layer audit pattern (FSM table →
  orchestrator → structural → frontend wire-format).
- [ADR-010: Reportlab-based PDF + LaTeX export](ADR-010-pdf-and-latex-export.md) —
  the hand-rolled PDF 1.4 generator is replaced by reportlab + DejaVu Sans
  (Unicode, real wrap, `/Dest` clickable references); a new
  `LatexReportGenerator` emits a self-contained `.tex` source.
- [ADR-011: Vancouver-style citations + anti-fabrication guard](ADR-011-vancouver-citations-anti-fabrication.md) —
  `[paper:N]` → `[<a href="#citation-N">N</a>]` in the frontend; a backend
  sanitizer at ingest clamps out-of-range indices and exposes running
  totals via `/health/sanitizer` and `/metrics`.
- [ADR-012: FSM-aware REPORT action returns full ReportResponse](ADR-012-fsm-aware-report-action.md) —
  the `REPORT` action returns `ReportResponse` (not `WorkspaceResponse`),
  via a `runAction` overload. Formalises the layer-4 audit pattern.
- [ADR-013: H1 title fallback for the synthesis LLM](ADR-013-h1-title-fallback.md) —
  when the synthesis LLM omits the `# ` heading, inject one derived from
  the first sentence (idempotent). Tracks the fallback rate over a 20-call
  sliding window and WARNs at >50%.
- [ADR-014: Prometheus /metrics + JSON health probes](ADR-014-prometheus-metrics-health-probes.md) —
  hand-rolled Prometheus exposition (no `prometheus_client` dep); seven
  metrics for sanitizer and title-fallback counters. JSON `/health/*`
  endpoints for non-Prometheus ops dashboards.
- [ADR-015: Bootstrap DNS + IPv6 retry with auto-fix](ADR-015-bootstrap-dns-ipv6-retry-auto-fix.md) —
  expanded network-failure patterns, TCP pre-flight probe, opt-in
  `BIORESEARCH_AUTO_FIX_DOCKER_IPV6=1` auto-fix (writes
  `{"ipv6": false}` to `/etc/docker/daemon.json` and restarts the
  daemon), safe subprocess handling.
- [ADR-016: Remove the COMPARING/COMPARED FSM states](ADR-016-remove-compared-state.md) —
  the cross-paper evidence-comparison subsystem is gone end-to-end
  (entity, use case, LLM generator, validator, persistence column,
  HTTP endpoint, frontend panel) because the report generator
  never consumed it as input. FSM is now linear: search →
  summarise → report → done. v7 migration drops the
  `evidence_comparison` SQLite column on connect.
- [ADR-017: Collapse the FSM to four states mapped 1:1 to the three pages](ADR-017-three-page-fsm.md) —
  the FSM collapses from nine to four states (`INITIAL` →
  `INTERMEDIATE` → `FINAL`, plus `ERROR`). Transient in-flight
  markers (SEARCHING, SUMMARIZING, REPORTING, PUBLISHING) are
  gone — the UI's spinner is the source of truth for "an
  operation is in flight." Five actions collapse to three:
  `search`, `generate` (does summary + report + PDF + LaTeX in
  one HTTP call), and `retry`. The FSM wire-format gains a
  new `page` field so the SPA can route without parsing the
  FSM state. v8 migration adds the `last_known_state` column
  so `retry` from `ERROR` can restore the pre-error state.
- [ADR-018: Context-aware FSM transitions via callable resolvers](ADR-018-context-aware-fsm-transitions.md) —
  closes the ADR-017 TODO. The FSM transition table now
  accepts callable resolvers of the form
  `Callable[[ResearchSession], WorkspaceState]` for entries
  that depend on session context (papers, summary, last
  known state). The first such entry is `ERROR + RETRY →
  _retry_target`, which replaces the static `INITIAL`
  fallback + `force_state` override pattern. The orchestrator's
  `retry()` method reduces to a single `transition_to` call,
  the audit trail records one transition per retry instead of
  two, and `force_state` is again reserved for its documented
  purpose (deserialization, action-outcome recording).
- [ADR-019: Citations are a strict subset of workspace.papers (structural invariant)](ADR-019-citation-subset-invariant.md) —
  enforces the user's hard rule "the executive reports can
  contain only references available at INTERMEDIATE, not more
  (less is possible, but definitely not more!)" at the entity
  layer. `ResearchSession.set_summary` and
  `ResearchSession.set_report` validate that every paper
  referenced is in `self.papers`; the validation uses
  `_paper_identity` so LLM-rewritten titles still match the
  corpus. Every paper mutation (`add_papers`,
  `replace_papers`, `remove_paper`) routes through a single
  `_mutate_papers` helper that clears the stale `summary`,
  `report`, and `published_report` so the invariant cannot be
  violated by reading a stale artefact. Violations raise
  `ValueError`, which the orchestrator's `_fail` helper catches
  and surfaces as a clear `last_error` (the workspace moves
  to `ERROR`, the user retries per ADR-018).

- [ADR-020: Bibliography equals workspace.papers](ADR-020-bibliography-equals-workspace-papers.md) —
  removes the legacy `_MAX_CITATIONS = 20` cap and rewrites
  `ReportMapper._build_citations` with a 3-phase logic:
  marker-cited papers first (Phase 1), substring-matched papers
  second (Phase 2), and remaining workspace papers last
  (Phase 3, corpus order). The bibliography now always
  equals the workspace paper count (after PMID/DOI dedup),
  so the user can verify that every paper at INTERMEDIATE
  appears in the report. Also fixes a latent `replace_papers`
  bug where direct entity callers would leave the state at
  INITIAL after adding papers (the orchestrator's
  `_enter_action` masks this on the normal search path).

## Every ADR follows the same format:

> # ADR-XXX Title
> 
> ## Status
> 
> Accepted
> 
> ---
> 
> ## Context
> 
> Why is this decision needed?
> 
> ---
> 
> ## Decision
> 
> What was decided?
> 
> ---
> 
> ## Alternatives Considered
> 
> Option 1
> 
> Option 2
> 
> Option 3
> 
> ---
> 
> ## Consequences
> 
> Advantages
> 
> Disadvantages
> 
> Future considerations