# ROADMAP

# BioResearch AI Roadmap

## Vision

BioResearch AI aims to become an extensible AI platform that assists biomedical researchers throughout the complete scientific discovery lifecycle—from literature exploration to evidence synthesis, hypothesis generation, and collaborative AI research.

---

# Development Strategy

Development is divided into progressive layers. Each layer introduces new capabilities while preserving the existing architecture.

---

# Phase 1 — Literature Search

**Status:** ✅ Completed

## Goals

* PubMed integration
* Paper retrieval
* Metadata extraction
* Citation support

Deliverables

* Search biomedical literature
* Retrieve abstracts
* Structured paper objects

### Bonus (added during Phase 1)

* **OpenAlex, Europe PMC, bioRxiv** multi-source
  search (PubMed is no longer the only source — see
  `app/infrastructure/literature/multi_source.py`)
* **DOI / PMID / title dedup** across sources
  (`confidence × recency_boost` ranking)
* **Section-based abstract extraction** with
  `<section id="Abs[0-9]+">` preferred over
  `<meta name="description">` (ADR-004)
* **Multi-identity paper deduplication** (ADR-005)

---

# Phase 2 — Paper Summarization

**Status:** ✅ Completed (2026-08-15)

## Goals

* Single-paper summaries
* Key findings extraction
* Study limitations
* Clinical relevance

Deliverables

* AI-generated summaries
* Citation-aware responses

---

# Phase 3 — Evidence Synthesis

**Status:** ✅ Completed (2026-08-18)

## Goals

Compare multiple publications to identify:

* Consensus
* Contradictions
* Strength of evidence
* Research gaps
* Future directions

Deliverables

* Comparative reports
* Evidence matrices
* Scientific conclusions

---

# Phase 4 — LangGraph Scientific Workflows

**Status:** ✅ Completed (2026-08-22)

## Goals

Introduce deterministic scientific workflows.

Example pipeline

```
Research Question

↓

Search Literature

↓

Evaluate Quality

↓

Summarize Findings

↓

Generate Report

↓

Validate Citations
```

Deliverables

* Stateful workflows (FSM with 12 stable/transient
  states — see `app/core/enums/workspace_state.py`
  and [ADR-009](docs/adr/ADR-009-publishing-state.md))
* Retry logic (`RETRY` action from `ERROR`)
* Validation (citation anti-fabrication guard at
  ingest — see
  [ADR-011](docs/adr/ADR-011-vancouver-citations-anti-fabrication.md))
* Human review support (Recover & Retry CTA on
  errors)

### Bonus (added during Phase 4)

* **`PUBLISHING` FSM state** (ADR-009) for PDF
  export with full audit trail
* **Four-layer audit pattern** (ADR-009) for adding
  new FSM actions safely

---

# Phase 5 — Multi-Agent Research System

**Status:** 🚧 In progress (single-agent today)

Specialized AI agents collaborate on scientific tasks.

Agents include:

* Planner
* Literature Agent
* Biology Agent
* Reviewer
* Report Generator

Goals

* Parallel reasoning
* Task delegation
* Quality assurance
* Improved report generation

The LangGraph workflow topology is in place; the
multi-agent coordinator is the next milestone.

---

# Phase 6 — Biological Knowledge Integration

**Status:** ⏳ Planned

Expand beyond scientific papers.

Planned integrations:

* UniProt
* Ensembl
* AlphaFold DB
* OpenTargets
* ClinicalTrials.gov
* Gene Ontology
* Reactome

Goals

* Protein information
* Gene annotation
* Disease associations
* Biological pathways

---

# Phase 7 — Long-Term Memory

**Status:** ✅ Substantially shipped (2026-08-26)

Introduce persistent knowledge.

Capabilities

* Previous searches
* Cached summaries
* Citation history
* Research sessions
* User workspaces

Implemented via

* **Redis-backed abstract-enricher cache**
  (ADR-003,
  `app/infrastructure/cache/redis_cache.py`) — shares
  state across worker processes
* **In-memory LRU cache** as the single-worker
  default
* **SQLite** as the workspace storage
  (`app/infrastructure/storage/sqlite_workspace_repository.py`)
* See [multi-worker-cache-investigation.md](docs/multi-worker-cache-investigation.md)
  for the cache-fragmentation problem and the
  remediation that was shipped.

---

# Phase 8 — MCP Integration

**Status:** 🚧 Scaffolded (skeleton in `app/infrastructure/mcp/`)

Expose biological resources through Model Context Protocol.

Potential MCP servers

* PubMed
* UniProt
* AlphaFold
* ClinicalTrials.gov

Goals

* Standardized tool access
* Easy extensibility
* Shared ecosystem compatibility

---

# Phase 9 — Agent-to-Agent Collaboration

**Status:** ⏳ Planned

Support distributed AI systems.

Capabilities

* Cross-agent communication
* Distributed workflows
* Remote execution
* Shared scientific reasoning

---

# Phase 10 — Research Assistant

**Status:** ⏳ Planned (long-term)

Long-term vision

An AI assistant capable of:

* Literature discovery
* Evidence synthesis
* Biological reasoning
* Hypothesis generation
* Report writing
* Citation validation
* Research planning

---

# Phase 0.6 — Report Export (added 2026-08-30)

**Status:** ✅ Completed

This phase was added out-of-order when the
`PUBLISHING` FSM state was introduced.

Deliverables

* **Multi-page reportlab-based PDF generator** with
  embedded DejaVu Sans (Unicode coverage for Greek
  letters, diacritics, em-dashes)
* **Clickable numbered references** (Vancouver
  style) — both in the PDF (`/Dest` annotations)
  and in the LaTeX source (`\hyperref`)
* **LaTeX export** via
  `GET /workspaces/{id}/published-report.tex`
* **Generate PDF / Generate TeX buttons** that
  auto-download
* **Bold + underlined Limitations and Future Research
  citation links** matching the executive-summary
  style

See [ADR-010](docs/adr/ADR-010-pdf-and-latex-export.md).

---

# Phase 0.7 — Observability (added 2026-08-30)

**Status:** ✅ Completed

This phase was added when the operator needed
visibility into the in-process LLM-safety counters.

Deliverables

* **`/metrics` Prometheus exposition** — sanitizer
  and title-fallback counters and gauges (hand-rolled,
  no `prometheus_client` dep)
* **`/health/sanitizer` JSON probe** — running totals
  for dropped citation markers
* **`/health/title-fallback` JSON probe** — fallback
  rate over a sliding 20-call window with WARN at
  >50%

See [ADR-014](docs/adr/ADR-014-prometheus-metrics-health-probes.md).

---

# Future Ideas

Potential future capabilities include:

* PDF ingestion
* Figure interpretation
* Clinical guideline comparison
* Drug discovery workflows
* Knowledge graph construction
* Automated systematic reviews
* Experimental design assistance
* Notebook integration
* Laboratory workflow support

---

# Success Criteria

BioResearch AI succeeds when researchers can:

* Find evidence faster
* Understand literature more efficiently
* Generate higher-quality reports (✅ — see
  [ADR-010](docs/adr/ADR-010-pdf-and-latex-export.md))
* Explore biological knowledge seamlessly
* Collaborate with trustworthy AI systems

---

# Guiding Principles

Every new feature should be:

* Modular
* Replaceable
* Testable
* Well documented (ADRs required for new
  architecture patterns)
* Backward compatible whenever practical
