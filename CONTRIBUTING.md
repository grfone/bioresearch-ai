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
    infrastructure/
    config/
    core/
```

Please place new functionality in the appropriate layer.

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

* README.md
* ARCHITECTURE.md
* ROADMAP.md
* API documentation
* Examples

---

# Testing

All new functionality should include appropriate tests whenever practical.

Recommended test categories:

* Unit tests
* Integration tests
* Workflow tests
* Regression tests

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
