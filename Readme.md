# BioResearch AI

An extensible AI platform for biomedical literature discovery, evidence synthesis, and scientific reasoning.

BioResearch AI helps researchers search scientific literature, compare findings across publications, retrieve biological knowledge from multiple databases, and generate evidence-based reports using modern AI systems.

The project is designed around a modular architecture so new capabilities can be added without rewriting existing code.

---

## Vision

Large language models are excellent at explaining biology.

Scientists are excellent at asking the right questions.

BioResearch AI aims to bridge those strengths by combining foundation models, biomedical databases, and agentic workflows into a system that supports scientific discovery.

Rather than replacing researchers, the goal is to help them explore the rapidly growing biomedical literature, identify knowledge gaps, and make more informed decisions.

---

## Current Features

- PubMed literature search
- Paper summarization
- Citation-aware responses

---

## Planned Roadmap

### Layer 1

✅ PubMed Search

Search biomedical literature directly from PubMed.

---

### Layer 2

Automatic Evidence Synthesis

Compare multiple papers and identify:

- consensus
- disagreement
- limitations
- future directions

---

### Layer 3

Finite State Workflow

Introduce deterministic scientific workflows using LangGraph.

Example:

Understand Question

↓

Search Literature

↓

Evaluate Results

↓

Summarize Evidence

↓

Generate Report

↓

Validate Citations

---

### Layer 4

Multi-Agent System

Specialized agents collaborate on different tasks.

- Planner
- Literature Agent
- Biology Agent
- Reviewer Agent
- Report Generator

---

### Layer 5

Biological Knowledge Integration

Support additional databases.

- UniProt
- Ensembl
- AlphaFold DB
- OpenTargets
- ClinicalTrials.gov

---

### Layer 6

Long-Term Memory

Persistent knowledge using vector databases.

---

### Layer 7

MCP Integration

Expose biological resources as Model Context Protocol tools.

---

### Layer 8

A2A Scientific Collaboration

Distributed agents communicate through Agent-to-Agent protocols.

---

## Architecture

This project follows Clean Architecture.

```

Presentation Layer

↓

Application Layer

↓

Domain Layer

↓

Infrastructure Layer

```

This separation allows AI frameworks, APIs, databases, and models to evolve independently.

---

## Repository Structure

```

bioresearch-ai/

app/

domain/
entities/
interfaces/
models/

application/
services/
workflows/
use_cases/

infrastructure/
pubmed/
llm/
storage/
mcp/
a2a/

agents/

tools/

api/

tests/

docs/

examples/

notebooks/

```

---

## Technology Stack

Python

OpenAI

LangGraph

MCP

FastAPI

PubMed API

UniProt API

OpenTargets

ChromaDB

Docker

---

## Development Philosophy

Every feature should satisfy three principles:

- Modular
- Replaceable
- Testable

Adding a new data source or AI model should require adding new components—not rewriting existing ones.

---

## Weekly Progress

### Week 1

PubMed Search

### Week 2

Paper Comparison

### Week 3

Evidence Synthesis

### Week 4

LangGraph Workflow

### Week 5

Biological Databases

### Week 6

MCP

### Week 7

Multi-Agent Collaboration

### Week 8

Web Interface

---

## Long-Term Goal

Create an extensible AI platform capable of assisting biomedical researchers throughout the scientific discovery process—from literature exploration to hypothesis generation.
