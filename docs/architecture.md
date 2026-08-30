# BioResearch AI Architecture

## Overview

BioResearch AI is an extensible AI platform for biomedical literature discovery, evidence synthesis, and scientific reasoning.

The project is intentionally designed around **Clean Architecture** to ensure that new AI models, data sources, workflows, and communication protocols can be introduced without rewriting the existing application.

The goal is to build a system that evolves incrementally while maintaining a stable and maintainable codebase.

---

# Design Principles

The project follows a few core principles.

## 1. Separation of Concerns

Each component should have a single responsibility.

Examples:

- Domain entities represent biomedical concepts.
- Infrastructure communicates with external APIs.
- Use cases orchestrate business logic.
- Agents coordinate complex workflows.

Each layer should remain independent from the others whenever possible.

---

## 2. Dependency Inversion

High-level logic must never depend directly on implementation details.

For example:

```
SearchLiteratureUseCase
        │
        ▼
LiteratureSearcher
        ▲
        │
PubMedSearcher
```

The application knows about the interface, not PubMed itself.

This allows replacing PubMed with Europe PMC or Semantic Scholar without changing the application logic.

---

## 3. Extensibility

New capabilities should require **adding code**, not modifying existing code.

Examples:

Instead of

```
if provider == "OpenAI":
```

we create

```
OpenAIProvider
ClaudeProvider
GeminiProvider
```

that all implement

```
LLMProvider
```

The same applies to:

- Literature databases
- Knowledge bases
- Memory systems
- Agent frameworks

---

## 4. Testability

Business logic should be testable without internet access.

The application should be able to run with mocked interfaces.

Example:

```
MockLiteratureSearcher
```

instead of

```
PubMedSearcher
```

during unit testing.

---

## 5. Framework Independence

LangGraph, CrewAI, MCP, FastAPI, Streamlit, OpenAI, or any future framework should never define the project architecture.

Frameworks are implementation details.

The architecture should survive framework changes.

---

# Architecture

```
Presentation Layer
│
├── CLI
├── FastAPI
└── Streamlit

↓

Application Layer
│
├── Use Cases
├── Services
├── Workflows
└── Agents

↓

Domain Layer
│
├── Entities
└── Interfaces

↓

Infrastructure Layer
│
├── PubMed
├── OpenAlex
├── Europe PMC
├── bioRxiv
├── OpenAI-compatible LLMs
├── Cache (in-memory + Redis)
├── PDF (reportlab) + LaTeX export
├── Observability (Prometheus + health probes)
├── Storage (SQLite)
├── MCP
└── A2A
```

Dependencies always point downward.

Infrastructure depends on Domain.

Application depends on Domain.

Domain depends on nothing.

---

# Repository Structure

```text
bioresearch-ai/

    app/
        domain/
            entities/      # Paper, Author, Citation, Journal,
                             # Summary, ResearchQuestion,
                             # ResearchReport, PublishedReport
            interfaces/     # LiteratureSearcher, LLMProvider,
                             # PDFGenerator, CacheProtocol

        application/
            use_cases/
            services/       # WorkspaceOrchestrator
            workflows/      # LangGraph research pipeline
            agents/

        infrastructure/
            pubmed/
            openalex/
            europe_pmc/
            biorxiv/
            literature/     # MultiSourceSearcher, dedup, ranking
            llm/            # OpenAI-compatible providers
            cache/          # InMemoryLRUCache, RedisCache
            pdf/            # Reportlab-based PDF generator
            latex/          # LaTeX source generator
            observability/  # Prometheus /metrics, /health/sanitizer,
                             # /health/title-fallback
            storage/        # SQLiteWorkspaceRepository
            mcp/
            a2a/

        api/
        core/              # FSM enums, transition table, exceptions
        config/            # DI container
        tools/

tests/
    unit/                 # 806 tests (FSM, citation, PDF, LaTeX, …)
    integration/          # 35 tests (FSM end-to-end)

docs/
    images/
    gifs/
    architecture.md
    ci.md
    repository.md
    multi-worker-cache-investigation.md
    adr/                  # 9 ADRs

examples/
notebooks/
scripts/                  # verify-ci.sh, etc.
```

---

# Data Flow

Current version

```
User Question

↓

ResearchQuestion

↓

LiteratureSearcher

↓

PubMedSearcher

↓

Paper

↓

Summary

↓

ResearchReport
```

Future versions will gradually introduce more components while keeping this flow stable.

---

# What we shipped

This section tracks the substantive work that's landed
since the first public release. Each bullet maps to one
or more commits — see the [CHANGELOG](../../CHANGELOG.md)
for the full commit history.

## 0.1 (initial release, 2026-07-14)

- Domain entities
- PubMed search
- Clean Architecture + DDD scaffolding
- Modular LLM provider interface

## 0.2

- LLM summarization
- AI-powered paper summaries

## 0.3

- Automatic evidence synthesis (consensus, contradictions,
  gaps, future directions, side-by-side matrix)
- Cross-paper comparison endpoint

## 0.4

- LangGraph workflow topology
- WorkspaceOrchestrator runtime
- **FSM-aware REPORT action** that returns the full
  ReportResponse
- Recover & Retry CTA on errors (see the audit pattern
  in [ADR-009](../adr/ADR-009-publishing-state.md))

## 0.5

- **Multi-source literature search**: PubMed, OpenAlex,
  Europe PMC, bioRxiv (via `MultiSourceSearcher` with
  DOI/PMID/title dedup and `confidence × recency_boost`
  ranking)
- **Pluggable cache backend** (in-memory vs Redis) to
  fix per-worker cache fragmentation — see
  [multi-worker-cache-investigation.md](multi-worker-cache-investigation.md)

## 0.6

- **PUBLISHING FSM state** (twelfth transient state) for
  PDF export
- **Multi-page PDF + Unicode coverage** via reportlab
  + DejaVu Sans
- **Clickable DOI links** in both the PDF and the LaTeX
  source
- **LaTeX export** (`GET /workspaces/{id}/published-report.tex`)
- **Generate PDF / Generate TeX buttons** that
  auto-download
- **Vancouver-style citations** with anti-fabrication
  guard at ingest

## 0.7

- **Observability**: `/metrics` (Prometheus) +
  `/health/sanitizer` + `/health/title-fallback`
- **H1 title fallback** when the synthesis LLM omits the
  heading (with a >50%-fallback-rate warning log)

## 0.8 (planned)

- MCP servers — each external biological resource
  becomes an MCP tool

## 0.9 (planned)

- Multi-agent collaboration: a planner coordinates a
  research agent, a biology agent, a reviewer, and a
  report generator

## 1.0 (planned)

- Scientific assistant capable of supporting literature
  review, biological knowledge retrieval, evidence
  synthesis, and hypothesis generation

---

# Engineering Philosophy

The objective is not to build another chatbot.

The objective is to build an extensible AI platform that can support biomedical researchers throughout the scientific discovery process.

Every new feature should satisfy three questions:

1. Does it make the system more modular?
2. Can it be tested independently?
3. Can it be replaced without affecting the rest of the project?

If the answer to any of these questions is "no", the design should be reconsidered.

---

# Long-Term Vision

BioResearch AI is intended to evolve from a simple literature search tool into a modular ecosystem of AI components capable of:

- Retrieving biomedical literature.
- Integrating biological databases.
- Synthesizing scientific evidence.
- Supporting hypothesis generation.
- Coordinating specialized AI agents.
- Assisting researchers in making evidence-based decisions.

The architecture should allow continuous evolution while preserving a clean, maintainable, and extensible codebase.