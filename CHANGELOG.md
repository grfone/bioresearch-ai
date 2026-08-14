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

### Fixed

* **GUI crash with "`Container ... instance has no attribute 'strip'`" (root cause).**
  A previous version had ``provider_hint_var.set("...").strip()`` —
  a chained call that returned ``None`` from ``set()`` and then
  crashed with ``AttributeError: 'NoneType' object has no attribute
  'strip'``. The fix is to apply ``.strip()`` to the string
  argument first, then pass the result to ``set()``. This also
  affects any Tkinter ``StringVar.set()`` chain (``append``,
  ``extend``, ``write``, etc.) that returns None.

* **Bootstrap crashes with "cannot join thread before it is started".**
  The previous ``_prompt`` helper used ``threading.Thread`` without
  calling ``.start()`` before ``.join()``. Replaced with plain
  ``input(text)`` — the most reliable cross-terminal behaviour.

* **GUI crash on Tk with bare ``StringVar()`` calls.** A previous
  version declared ``api_key_var``, ``pubmed_email_var`` and
  ``pubmed_api_key_var`` with ``tk.StringVar()`` (no default).
  Some Tk versions return ``None`` from a freshly-constructed
  StringVar's ``.get()``, which made ``.get().strip()`` raise
  ``AttributeError: 'NoneType' object has no attribute 'strip'``.
  All StringVars now use ``value=""`` and every ``.get().strip()``
  call is wrapped as ``(X.get() or '').strip()`` for belt-and-braces
  protection. The GUI's ``on_save`` is also wrapped in a
  ``try/except`` that shows a clear message instead of crashing
  the bootstrap on any unexpected error.

### Changed

* **Dropped conda entirely.** The ``backend-local`` build target
  no longer uses micromamba/conda. It installs the ML stack
  (torch, transformers, scikit-learn, rdkit, pandas, scipy)
  via pip on the same ``python:3.12-slim`` base. This cuts the
  local image from ~3 GB to ~1.2 GB and avoids the 404-prone
  conda-forge channel entirely. When the host has an NVIDIA
  GPU, the bootstrap now sets ``TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124``
  so pip pulls the CUDA build of torch instead of the CPU build.

* **No conda, no micromamba.** The ``environment.yaml`` file is
  retained for users who keep the legacy conda runbook, but the
  Dockerfile no longer reads it. New users can ignore it.

### Added

* **Robust first-run setup.** The bootstrap auto-installs
  ``python3-tk`` on Linux / macOS when tkinter is missing, and
  falls back to a terminal-based wizard when the GUI can't run
  (e.g. no DISPLAY on a remote server over SSH). The terminal
  wizard handles the same fields as the GUI wizard and refuses
  to run in a non-TTY context with a clear error pointing at
  ``--skip-gui``.

* **Slim Docker image by default.** The Dockerfile now ships two
  build targets: `bioresearch-ai:latest` (slim, ~250 MB, no
  conda, no Node.js, no ML libraries) and `bioresearch-ai:local`
  (heavy, ~3 GB, with the full ML stack via conda). The default
  is the slim image. Users pick the heavy image by passing
  `--local` to bootstrap.py. The slim image uses
  `python:3.12-slim` and only installs the 7 backend runtime
  packages the FastAPI app actually imports. The local image
  keeps the previous conda-based build for users who want to
  run the original research scripts.

* **Conda channel mirror.** The Dockerfile defaults to
  `https://conda.anaconda.org/conda-forge` (the only conda-forge
  URL that reliably returns 200 today) and accepts a
  `CONDA_CHANNEL` build-arg. The bootstrap CLI exposes
  `--mirror <url>` so users on restrictive networks can point at
  a working host. The conda install retries up to three times on
  transient failures and bails out immediately on a 404 response
  so a wrong channel URL doesn't waste 30 seconds of retrying.

* **BuildKit (buildx) by default.** The bootstrap installs
  `docker-buildx` on Linux as a **separate step** after the Docker
  check, so users with an existing Docker install also get
  buildx added on the first run. The build then calls
  `docker buildx build` instead of the deprecated `docker build`.
  macOS and Windows Docker Desktop users already have buildx
  (the bootstrap symlinks it on PATH if it isn't already).
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
