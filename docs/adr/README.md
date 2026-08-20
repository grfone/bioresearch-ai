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