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
├── OpenAI
├── MCP
├── Storage
└── A2A
```

Dependencies always point downward.

Infrastructure depends on Domain.

Application depends on Domain.

Domain depends on nothing.

---

# Repository Structure

```
bioresearch-ai/

app/

    domain/
        entities/
        interfaces/

    application/
        use_cases/
        services/
        workflows/
        agents/

    infrastructure/
        pubmed/
        llm/
        storage/
        mcp/
        a2a/

    api/
    tools/

tests/

docs/

examples/

notebooks/
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

# Planned Evolution

## Version 0.1

- Domain entities
- PubMed search

---

## Version 0.2

- LLM summarization

---

## Version 0.3

- Automatic evidence synthesis

---

## Version 0.4

- LangGraph workflow

---

## Version 0.5

- Multiple biological databases

- UniProt
- AlphaFold DB
- OpenTargets

---

## Version 0.6

- Memory
- Vector database
- Retrieval augmentation

---

## Version 0.7

- MCP servers

Each external biological resource becomes an MCP tool.

---

## Version 0.8

- Multi-agent collaboration

Planner

↓

Research Agent

↓

Biology Agent

↓

Reviewer Agent

↓

Report Generator

---

## Version 0.9

Scientific reasoning

The system begins comparing evidence across studies rather than summarizing individual papers.

---

## Version 1.0

Scientific assistant capable of supporting literature review, biological knowledge retrieval, evidence synthesis, and hypothesis generation.

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