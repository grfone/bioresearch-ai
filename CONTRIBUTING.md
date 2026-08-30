# CONTRIBUTING

# Contributing to BioResearch AI

First, thank you for considering contributing to BioResearch AI.

Whether you're fixing bugs, improving documentation, implementing new features, or proposing new ideas, your contributions are greatly appreciated.

---

# Development Philosophy

Every contribution should follow three core principles:

* Modular
* Replaceable
* Testable

Business logic should remain independent of frameworks and external services.

---

# Getting Started

Clone the repository.

```bash
git clone <repository-url>
cd bioresearch-ai
```

Create a virtual environment.

```bash
python -m venv .venv
```

Activate it.

Linux/macOS

```bash
source .venv/bin/activate
```

Windows

```powershell
.venv\Scripts\activate
```

Install dependencies.

```bash
pip install -r requirements.txt
```

---

# Project Structure

```text
app/
    api/
    application/
    domain/
    infrastructure/   # pubmed, openalex, europe_pmc, biorxiv,
                      # llm (20+ providers), cache, pdf, latex,
                      # observability, storage
    config/
    core/             # FSM enums + transition table
```

Please place new functionality in the appropriate layer.

Architectural decisions are documented as
[ADRs in `docs/adr/`](docs/adr/). Before making a
significant change, please:

1. Read the existing ADRs that touch your area
   (`ls docs/adr/` to see the index).
2. If your change introduces a new architecture
   pattern, write a new ADR (numbered
   `ADR-NNN-descriptive-name.md`) following the
   template in [`docs/adr/README.md`](docs/adr/README.md).
3. Update the relevant ADR list in
   [README.md](README.md) — there's a markdown
   table that maps each ADR to its decision.

For new FSM actions specifically, follow the
**four-layer audit pattern** documented in
[ADR-009](docs/adr/ADR-009-publishing-state.md)
and formalised in
[ADR-012](docs/adr/ADR-012-fsm-aware-report-action.md):
audit the FSM table, the orchestrator runtime,
the structural assumption (route handler signature),
and the frontend wire-format before writing code.

---

# Branch Naming

Suggested branch names:

```text
feature/add-uniprot-provider
feature/evidence-synthesis
bugfix/pubmed-timeout
docs/update-roadmap
refactor/llm-factory
```

---

# Pull Requests

Before opening a pull request:

* Ensure the project builds successfully.
* Run the test suite.
* Add tests for new functionality.
* Update documentation when appropriate.
* Keep pull requests focused on a single change.

A good pull request includes:

* Clear description
* Motivation
* Implementation details
* Screenshots (if applicable)
* Linked issue (if applicable)

---

# Coding Guidelines

Please:

* Follow PEP 8
* Prefer type hints
* Write descriptive names
* Keep functions focused
* Avoid unnecessary complexity
* Favor composition over duplication

---

# Documentation

Documentation is a first-class part of the project.

When introducing new features, consider updating:

* `README.md` — features, "What's new since v0.1.0",
  test count, roadmap
* `ARCHITECTURE.md` — repository organization, FSM
  diagram, infrastructure integrations
* `CHANGELOG.md` — every public-facing change goes
  here
* `docs/architecture.md` — the high-level companion
  to `ARCHITECTURE.md`
* `docs/repository.md` — the file tree (kept in sync
  with `find app -type d`)
* `docs/ci.md` — CI workflow changes
* `docs/adr/` — a new ADR if the change introduces a
  new architecture pattern
* API documentation
* Examples

When updating existing documentation:

* **Preserve the style** — keep images, GIFs, and
  the existing visual rhythm. The user has explicitly
  asked for "update with the actual progress" but
  "keep the style in general".
* **Update the test count** — `806 backend + 289
  frontend` is the current value as of 2026-08-30.
* **Update the ADR list** — new ADRs need a row in
  the `README.md` table AND a bullet in
  `docs/adr/README.md`.

---

# Testing

All new functionality should include appropriate tests whenever practical.

Recommended test categories:

* Unit tests (`tests/unit/`)
* Integration tests (`tests/integration/`) — these
  require a real Redis instance (see `docs/ci.md`)
* Workflow tests
* Regression tests

Current test counts (as of 2026-08-30):

* **806 backend tests** (run via
  `pytest tests/unit/ tests/integration/ -q`)
* **289 frontend tests** (run via
  `cd frontend && npx vitest run`)
* **1095 total**

Both suites must pass before opening a pull request.
The CI pipeline runs all four jobs (backend, frontend,
docker-build, integration-redis) on every push; all
four must be green.

---

# Commit Messages

Examples:

```text
feat: add UniProt provider

fix: handle PubMed API timeout

docs: improve architecture documentation

refactor: simplify report generation workflow

test: add evidence synthesis tests
```

---

# Reporting Bugs

When reporting bugs, please include:

* Python version
* Operating system
* Steps to reproduce
* Expected behavior
* Actual behavior
* Relevant logs or stack traces

---

# Feature Requests

Feature proposals are welcome.

Please explain:

* The problem being solved
* The proposed solution
* Alternative approaches considered
* Potential implementation ideas

---

# Questions

If you have questions about the project, feel free to open a GitHub Discussion or Issue.

We welcome constructive feedback and scientific collaboration.

Thank you for helping make BioResearch AI better!
