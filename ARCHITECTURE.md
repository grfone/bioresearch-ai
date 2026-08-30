# ARCHITECTURE

# BioResearch AI Architecture

## Overview

BioResearch AI follows **Clean Architecture** combined with **Domain-Driven Design (DDD)** principles. The system is organized into independent layers so that business logic remains isolated from AI frameworks, databases, APIs, and user interfaces.

This architecture allows new language models, biomedical databases, workflows, and agents to be introduced without modifying the core domain.

---

# Architectural Principles

The project is built around five guiding principles:

* Separation of concerns
* Dependency inversion
* Replaceable infrastructure
* Testability
* Extensibility

Dependencies always point inward toward the domain.

```
                   ┌──────────────────────┐
                   │   Presentation       │
                   │  API / CLI / UI      │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │    Application       │
                   │ Use Cases & Services │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │      Domain          │
                   │ Business Rules       │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │   Infrastructure     │
                   │ LLMs • PubMed • DB   │
                   └──────────────────────┘
```

---

# Layer Responsibilities

## 1. Presentation Layer

Responsible for interacting with external clients.

Examples include:

* FastAPI endpoints
* CLI commands
* Web interface
* Future desktop applications

Responsibilities:

* Validate requests
* Invoke application use cases
* Return formatted responses
* No business logic

---

## 2. Application Layer

Coordinates the execution of business workflows.

Components include:

* Use Cases
* Services
* Agents
* LangGraph workflows

Responsibilities:

* Orchestrate operations
* Coordinate repositories and providers
* Execute workflows
* Manage AI reasoning pipelines

Examples:

```
Search Literature

↓

Retrieve Papers

↓

Summarize Papers

↓

Generate Evidence Report
```

The Application layer knows **what** should happen but not **how** external services implement it.

---

## 3. Domain Layer

The Domain layer represents the scientific knowledge model.

It contains no framework-specific code.

Entities include:

* Paper
* Author
* Citation
* Journal
* Summary
* ResearchQuestion
* ResearchReport

Interfaces define contracts for:

* Literature search
* LLM providers
* Report generation
* Knowledge bases

Because the domain depends on abstractions instead of implementations, infrastructure can evolve independently.

---

## 4. Infrastructure Layer

Implements all external integrations.

### Literature

* PubMed (NCBI canon)
* OpenAlex (200M+ works, free)
* Europe PMC (PubMed + preprints + many publishers)
* bioRxiv (preprint server, opt-in via `BIORXIV_ENABLED=true`)

### Language Models

* OpenAI
* Anthropic
* Ollama
* Azure OpenAI
* Alibaba
* DeepSeek
* Moonshot
* Baidu
* Tencent
* Zhipu
* Yi
* MiniMax
* and others

### Storage

* **SQLite** (current default, in-process via `SQLiteWorkspaceRepository`)
* **Redis** for the abstract-enricher cache (via `CacheProtocol` -- shared across workers, fixes the per-worker cache fragmentation documented in `docs/multi-worker-cache-investigation.md`)
* Future support: PostgreSQL, vector databases

### Report export

* **PDF** via `app/infrastructure/pdf/reportlab_generator.py` — embeds DejaVu Sans (TTF, full Unicode coverage) and produces real clickable `/Dest` link annotations for numbered references.
* **LaTeX** via `app/infrastructure/latex/latex_generator.py` — emits a complete `.tex` source the user can compile with `pdflatex report.tex && pdflatex report.tex`. Uses `hyperref` for clickable in-text references.

### Observability

* `/metrics` (Prometheus text format) — sanitizer counters, title-fallback rate, gauges
* `/health/sanitizer` and `/health/title-fallback` (JSON) for ops dashboards

### Scientific Integrations (planned)

* UniProt
* Ensembl
* AlphaFold DB
* ClinicalTrials.gov
* OpenTargets

Infrastructure can be replaced without affecting business logic.

---

# Repository Organization

```
app/

├── api/

├── application/
│   ├── services/
│   ├── use_cases/
│   └── workflows/

├── domain/
│   ├── entities/
│   │   └── # Paper, Author, Citation, Journal,
│   │      # Summary, ResearchQuestion, ResearchReport,
│   │      # PublishedReport
│   ├── interfaces/
│   │   └── # LiteratureSearcher, LLMProvider,
│   │      # PDFGenerator, CacheProtocol
│   └── models/

├── infrastructure/
│   ├── cache/                # InMemoryLRUCache, RedisCache
│   ├── latex/               # LatexReportGenerator (.tex export)
│   ├── literature/          # PubMed, OpenAlex, Europe PMC, bioRxiv
│   ├── llm/                 # OpenAI-compatible providers
│   ├── observability/       # /metrics Prometheus exposition
│   ├── pdf/                 # Reportlab-based PDF generator
│   ├── pubmed/
│   ├── storage/             # SQLiteWorkspaceRepository
│   ├── mcp/
│   └── a2a/

├── config/                  # DI container + Settings
├── core/                     # Enums (WorkspaceState, WorkspaceAction),
│                            # exceptions, FSM transition table
└── tools/
```

---

# Dependency Rule

Dependencies always flow inward.

```
Presentation
      │
      ▼
Application
      │
      ▼
Domain
      ▲
      │
Infrastructure
```

The Domain layer never imports infrastructure code.

Infrastructure implements interfaces declared inside the Domain.

---

# Typical Request Flow

A literature search follows this sequence:

```
Client

↓

FastAPI Endpoint

↓

SearchLiteratureUseCase

↓

LiteratureSearcher Interface

↓

PubMed Provider

↓

Retrieved Papers

↓

Summarization Service

↓

Report Generator

↓

Response
```

Only the Infrastructure layer communicates with external APIs.

---

# Finite State Machine

The workspace lifecycle is a deterministic finite state machine (FSM) — every transition is enumerated in `app/core/enums/workspace_state.py`. Illegal actions are rejected with HTTP 409 and the list of legal next actions. See [ADR-009](docs/adr/ADR-009-publishing-state.md) for the four-layer audit pattern used to add new actions.

```
CREATED ──search──▶ SEARCHING ──▶ PAPERS_RETRIEVED ──report──▶ REPORTING ──▶ REPORTED
                                          │                                          │
                                          ├─compare──▶ COMPARING ──▶ COMPARED ───────┘
                                          │
                                          └─summarize──▶ SUMMARIZING ──▶ SUMMARIZED ──report──▶ REPORTING ──▶ REPORTED

REPORTED ──publish──▶ PUBLISHING ──(force_state)──▶ COMPLETED
                                  │
                                  └─ renders PDF (reportlab)
                                  └─ persists on session (PublishedReport)
                                  └─ serves via GET /workspaces/{id}/published-report.pdf
```

`PUBLISHING` is transient — added to `_TRANSIENT_STATES` so the workspace-status strip treats it like `SEARCHING` or `REPORTING`. The user only sees `COMPLETED` once the network round-trip resolves.

Every state transition records a `StateTransition` with `(action, reason)` for the audit trail. The four-layer audit pattern (FSM table → orchestrator → structural → frontend wire-format) is the standing recipe for any new FSM action.

---

# AI Workflow Evolution

The platform is designed to evolve through progressively more capable workflows.

## Phase 1

Single LLM calls

```
Question

↓

LLM

↓

Answer
```

---

## Phase 2

Retrieval-Augmented Generation

```
Question

↓

PubMed Search

↓

Relevant Papers

↓

LLM

↓

Evidence-Based Answer
```

---

## Phase 3

Evidence Synthesis

```
Question

↓

Search

↓

Retrieve Papers

↓

Compare Findings

↓

Detect Consensus

↓

Generate Scientific Report
```

---

## Phase 4

LangGraph Workflows

Deterministic execution graphs provide:

* retries
* validation
* branching
* human review
* checkpointing

---

## Phase 5

Multi-Agent Collaboration

Specialized agents collaborate on scientific tasks.

```
Planner

↓

Literature Agent

↓

Biology Agent

↓

Evidence Reviewer

↓

Report Generator
```

Each agent performs one well-defined responsibility.

---

## Phase 6

Persistent Scientific Memory

Future versions will maintain long-term knowledge using vector databases.

Capabilities include:

* prior searches
* previous reports
* reusable summaries
* citation history

---

## Phase 7

MCP Integration

External biological resources become discoverable through Model Context Protocol servers.

Potential MCP tools include:

* PubMed
* UniProt
* AlphaFold
* Ensembl
* ClinicalTrials.gov

---

## Phase 8

Agent-to-Agent Collaboration

Future distributed agents may collaborate across multiple systems using A2A protocols.

Examples:

* laboratory assistants
* clinical assistants
* genomics agents
* drug discovery agents

---

# Extension Points

The architecture is intentionally open for extension.

Adding a new literature provider requires:

1. Implementing `LiteratureSearcher`
2. Registering the provider
3. Updating configuration

No domain code changes are required.

The same approach applies to:

* new LLM providers
* biological databases
* report generators
* storage engines
* workflow engines

---

# Technology Stack

| Layer          | Technologies                                                    |
| -------------- | --------------------------------------------------------------- |
| Presentation   | FastAPI, CLI                                                    |
| Application    | Python, LangGraph                                               |
| Domain         | Pure Python                                                     |
| Infrastructure | OpenAI-compatible providers, PubMed, OpenAlex, Europe PMC, bioRxiv |
| Storage        | SQLite (default), Redis cache (multi-worker)                   |
| Report export  | Reportlab (PDF) + custom LaTeX generator                         |
| Observability  | Hand-rolled Prometheus exposition (`/metrics`), JSON health probes (`/health/sanitizer`, `/health/title-fallback`) |
| Container      | Docker (built by `python3 bootstrap.py` with auto-recovering DNS + IPv6 handling) |

---

# Design Goals

BioResearch AI is designed to remain maintainable as the platform grows from a simple literature search tool into a comprehensive biomedical research assistant.

Every architectural decision is guided by three principles:

* **Modular** — Components have clear responsibilities.
* **Replaceable** — External technologies can be swapped without affecting core logic.
* **Testable** — Business logic can be validated independently of infrastructure.

This foundation enables the project to scale from single-model interactions to sophisticated multi-agent scientific reasoning while preserving a stable and maintainable codebase.
