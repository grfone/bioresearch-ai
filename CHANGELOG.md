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

### Added

* **Conda channel mirror.** The Dockerfile now defaults to
  `https://conda.anaconda.cloud/conda-forge` (the conda-forge
  canonical host as of the 2026 transition; the legacy
  `conda-forge.org` and `conda.anaconda.org` URLs are being
  phased out) and accepts a `CONDA_CHANNEL` build-arg. The
  bootstrap CLI exposes `--mirror <url>` so users on restrictive
  networks can point at Tsinghua, Aliyun, or any other mirror.
  The choice is saved to `.env` so subsequent runs reuse it.
  The conda install also retries up to three times with a
  back-off, and the install step is split into download + link
  so a transient failure doesn't require re-downloading the
  entire package set.

* **BuildKit (buildx) by default.** The bootstrap installs
  `docker-buildx` alongside `docker.io` on Linux and calls
  `docker buildx build` instead of the deprecated `docker build`.
  macOS and Windows Docker Desktop users already have buildx.
  The bootstrap falls back to the legacy builder if buildx is
  not available, with a clear warning.

* **22 working LLM providers.** A new `LLMProviderCatalog`
  (`app/application/services/llm_provider_catalog.py`) is the
  single source of truth for everything related to provider
  selection. The bootstrap GUI now lists every provider grouped
  by region (Local / US / EU / CA / CN). The factory registers
  every entry. New providers: `xai`, `mistral`, `cohere`,
  `perplexity`. The Chinese tier covers DeepSeek, MiniMax
  (the user's existing provider is preserved), Moonshot Kimi,
  Zhipu GLM, Alibaba Qwen, Baidu Qianfan, Tencent Hunyuan,
  ByteDance Doubao, Baichuan, 01.AI Yi, SenseTime, iFlytek
  Spark, StepFun, and Huawei Pangu.

* **OpenAI-compatible shared base class.** Every provider that
  exposes an OpenAI-compatible `/chat/completions` endpoint is
  now a thin subclass of `OpenAICompatibleProvider` in
  `app/infrastructure/llm/_openai_compatible.py`. Adding a new
  provider is one entry in the catalog plus one tiny subclass
  file.

* **Catalog-driven bootstrap GUI.** The first-run picker is
  driven by the catalog. Each row shows the provider display
  name, region, default model, and the API-key environment
  variable. Theater-style hints update when the user selects
  a different provider.

* **One-command install (`bootstrap.py`).** `python3 bootstrap.py`
  detects the OS, installs Docker, builds the container image,
  opens a Tkinter first-run GUI that asks for LLM credentials
  and PubMed, probes each credential live via
  `scripts/probe_credentials.py`, saves the values to `.env`,
  and opens the app in the default browser. Re-running is
  idempotent.

* **Docker image.** New `Dockerfile` (single image, micromamba +
  Node) and `docker-compose.yml` (backend + optional Ollama
  service with GPU passthrough). The backend serves the
  prebuilt React bundle so the entire app is reachable on port
  8000.

* **Local LLM option.** Real `OllamaProvider` connects to a
  local Ollama daemon over its OpenAI-compatible endpoint.
  `LLMProviderEnum.LOCAL` is a user-facing alias for `OLLAMA`.
  The bootstrap shows a hardware-aware model picker that
  recommends `deepseek-r1-distill-llama-8b-q4_k_m` for GPUs
  with ≥ 8 GB VRAM, `deepseek-coder-v2-lite-instruct-q4_k_m`
  for ≥ 16 GB CPU, and `q3_k_m` for ≥ 8 GB CPU.

* **Static SPA serving.** `main.py` mounts `frontend/dist` at
  `/` when the build is present; the legacy `/` status endpoint
  is moved to `/api`.

* **Installation guide.** New `INSTALL.md` documents the
  one-command flow, the model-tier table, the daily workflow,
  and troubleshooting.

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
