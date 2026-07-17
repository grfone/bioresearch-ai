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

Examples:

### Literature

* PubMed

Future:

* Semantic Scholar
* Europe PMC
* arXiv

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

Future support includes:

* ChromaDB
* PostgreSQL
* Redis
* Vector databases

### Scientific Integrations

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
│
├── application/
│   ├── agents/
│   ├── services/
│   ├── use_cases/
│   └── workflows/
│
├── domain/
│   ├── entities/
│   ├── interfaces/
│   └── models/
│
├── infrastructure/
│   ├── llm/
│   ├── pubmed/
│   ├── storage/
│   ├── mcp/
│   └── a2a/
│
├── config/
├── core/
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

| Layer          | Technologies                             |
| -------------- | ---------------------------------------- |
| Presentation   | FastAPI, CLI                             |
| Application    | Python, LangGraph                        |
| Domain         | Pure Python                              |
| Infrastructure | OpenAI, Anthropic, Ollama, PubMed, MCP   |
| Storage        | ChromaDB (planned), PostgreSQL (planned) |

---

# Design Goals

BioResearch AI is designed to remain maintainable as the platform grows from a simple literature search tool into a comprehensive biomedical research assistant.

Every architectural decision is guided by three principles:

* **Modular** — Components have clear responsibilities.
* **Replaceable** — External technologies can be swapped without affecting core logic.
* **Testable** — Business logic can be validated independently of infrastructure.

This foundation enables the project to scale from single-model interactions to sophisticated multi-agent scientific reasoning while preserving a stable and maintainable codebase.
