# CHANGELOG

# Changelog

All notable changes to this project will be documented in this file.

The format is based on **Keep a Changelog**, and this project follows **Semantic Versioning (SemVer)**.

---

## [Unreleased]

### Added

* **Finite State Machine for Research Workspaces.** The workspace
  moves through a deterministic FSM
  (``CREATED → SEARCHING → PAPERS_RETRIEVED → SUMMARIZING →
  SUMMARIZED → COMPARING → COMPARED → REPORTING → REPORTED →
  COMPLETED``) with explicit, testable transitions. The FSM lives
  in ``app/core/enums/workspace_state.py`` and is enforced by
  ``ResearchSession``.

* **WorkspaceOrchestrator.** New single entry point
  (``app/application/services/workspace_orchestrator.py``) that
  drives the FSM. The legacy ``ResearchAssistant`` is kept for
  backwards compatibility but the orchestrator is the only
  component that mutates workspace state.

* **Evidence Comparison (Phase 3).** New ``EvidenceComparison``
  and ``EvidenceMatrix`` domain entities, ``compare_evidence``
  use case, and ``LLMComparisonGenerator`` /
  ``EvidenceComparisonMapper`` infrastructure. The comparison
  contains consensus findings, contradictions, research gaps,
  future directions, and an optional side-by-side matrix.

* **Anti-fabrication guard.** New
  ``CitationValidator`` (in ``app/application/validation``)
  rejects any AI-generated artefact that references paper IDs
  not in the workspace's paper set. Used by both the
  comparison and report workflows.

* **LangGraph workflow topology.** The same workflow is now
  declared as a LangGraph ``StateGraph``
  (``app/application/workflows/research_workflow.py``) paving
  the way for Phase 5 multi-agent collaboration.

* **FSM-aware REST endpoints.** New action endpoints under
  ``/workspaces/{id}/actions/{search, summarize, compare,
  report, complete, retry}`` plus ``GET /transitions`` and
  ``GET /evidence-comparison``. Illegal actions return HTTP
  409 with the list of legal alternatives.

* **Lab-bench UI.** The ``Workspace.tsx`` page now renders a
  lifecycle strip (Question → Papers → Summary → Comparison →
  Report) with progress, current state, allowed actions, and
  a transition history. ``WorkspaceStatusBar`` and
  ``EvidenceComparisonPanel`` are the new building blocks.

* **57 unit + integration tests.** Full coverage of the FSM
  transition table, the citation validator, the orchestrator,
  the comparison mapper, and the FastAPI integration.

* **Persistent workspace state.** The SQLite repository
  performs an additive migration to v2 (new columns:
  ``state``, ``state_history``, ``evidence_comparison``).
  Legacy rows are auto-upgraded to the most advanced state
  their data supports.

### Changed

* The legacy ``POST /reports/generate`` endpoint is now a thin
  shim around the orchestrator's ``report`` action. Reports
  are generated from the workspace's current papers, never
  from a fresh PubMed search. The endpoint is marked
  ``deprecated=True`` in the OpenAPI schema.

* ``WorkspaceResponse`` now exposes the new FSM fields
  (``state``, ``allowed_actions``, ``progress``,
  ``has_evidence_comparison``, ``last_error``). The legacy
  ``status`` field is preserved for backwards compatibility
  and always mirrors ``state.value``.

### Fixed

* ``POST /reports/generate`` no longer re-queries PubMed. The
  endpoint used to call ``assistant.generate_report(question)``
  which re-searched literature from scratch, ignoring the
  workspace's curated paper set. The fix is enforced by the
  FSM: the orchestrator's ``report`` action takes the
  workspace as input and uses *its* papers.

### Planned

* Multi-agent collaboration
* Biological database integrations
* Long-term memory
* MCP support
* Agent-to-Agent (A2A) communication

---

## [0.1.0] - 2026-07-14

### Added

* Initial public release
* Clean Architecture implementation
* Domain entities for biomedical research
* PubMed integration
* AI-powered literature summarization
* Report generation foundation
* Modular LLM provider interface
* Project documentation
* Roadmap and architecture documentation

---

## Release Policy

Version numbers follow Semantic Versioning:

* **MAJOR** — Breaking API changes
* **MINOR** — New features with backward compatibility
* **PATCH** — Bug fixes and maintenance

Example:

```text
1.0.0
│ │ └── Patch
│ └──── Minor
└────── Major
```
