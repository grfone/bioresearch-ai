# ADR-001: Adopt Clean Architecture

## Status

Accepted

---

## Context

BioResearch AI is expected to grow over time by integrating multiple
literature providers, language models, biological databases, and AI
frameworks.

Without clear architectural boundaries, introducing new components would
require modifications across the entire codebase.

---

## Decision

The project will follow Clean Architecture.

The codebase will be divided into:

- Domain
- Application
- Infrastructure
- API

The Domain layer must remain independent of external libraries.

Infrastructure components implement interfaces defined in the Domain.

---

## Alternatives Considered

### MVC

Simple but tightly coupled.

### Layered Architecture

Improves organization but still couples business logic to infrastructure.

### Clean Architecture

Provides clear dependency inversion and long-term maintainability.

Chosen.

---

## Consequences

Advantages

- Easier testing
- Modular components
- Easier provider replacement
- Better scalability

Disadvantages

- More initial boilerplate
- Slightly steeper learning curve

Future

This architecture naturally supports MCP, A2A and multi-agent systems.