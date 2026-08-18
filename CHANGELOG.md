# CHANGELOG

# Changelog

All notable changes to this project will be documented in this file.

The format is based on **Keep a Changelog**, and this project follows **Semantic Versioning (SemVer)**.

---

## [Unreleased]

### Added

* **Two-tab paper entry surface.** The ``AddPapersPanel`` now
  exposes only DOI bulk-paste and PDF drag-and-drop. The
  previous "Manual" tab was removed — researchers don't
  manually fill every field; they paste DOIs or drop PDFs. The
  bulk input accepts DOIs only; PMIDs are still accepted on
  the backend (PDF extraction can surface one) but the
  user-visible entry surface is DOI-first.
* **PaperCard and PaperList.** The card / list components
  were stubs (61 / 44 lines of incomplete logic). They now
  render real paper metadata: title, authors (truncated to
  "et al." after three), journal + year, abstract (truncated
  to 3 lines with a "Show more" toggle), DOI / PMID identifier
  badges each linking to their canonical resolver, and an
  external-link icon to ``paper.url``.
* **Partial-metadata marker.** Papers with thin metadata
  (no authors AND no abstract — the typical CrossRef fallback
  when the DOI resolves but the publisher doesn't expose the
  full record) get an amber asterisk (``*``) next to the
  title and a warning banner below the metadata. The
  ``isThinPaper(paper)`` helper centralises the predicate and
  is unit-tested. Callers can disable the marker via the
  ``showPartialMarker`` prop.

* **Multi-source literature search (OpenAlex, Europe PMC,
  bioRxiv).** The previous search was PubMed-only. Researchers
  can now pick from four sources — PubMed (NCBI canon),
  OpenAlex (200M+ works across all disciplines, free), Europe
  PMC (PubMed + preprints + many publishers), and bioRxiv
  (preprint server). The backend fans out via
  ``MultiSourceSearcher``, dedupes on DOI/PMID/title, and
  ranks by ``confidence × recency_boost``. The default source
  set is PubMed + OpenAlex + Europe PMC; bioRxiv is opt-in
  via ``BIORXIV_ENABLED=true`` and is gated in the UI to a
  year window (it has no keyword search).

* **Advanced Search modal (frontend).** The "Search PubMed"
  button in the action bar now opens a modal that exposes
  the full filter bundle: source checkboxes (PubMed /
  OpenAlex / Europe PMC / bioRxiv), ``since_year`` /
  ``until_year`` pickers, sort order (relevance / newest
  first), ``max_results``, document-type chips (journal
  article, review, preprint, dataset, conference paper,
  book chapter, thesis), and toggles for ``open_access_only``
  and ``include_abstracts``. The primary CTA posts the
  filter bundle to the same backend endpoint; the route
  detects the ``filters`` block and dispatches through
  ``WorkspaceOrchestrator.search_with_filters`` instead of
  the legacy ``search(query)``.

* **``AdvancedSearchFilters`` API schema.** New
  Pydantic-validated request shape on
  ``WorkspaceActionRequest``. Mirrors the domain
  ``SearchFilters`` dataclass with string literal types for
  source / sort / document-type so the frontend builds
  type-safe requests. All fields are optional with
  sensible defaults.

* **``SearchLiteratureUseCase.execute_with_filters`` and
  ``WorkspaceOrchestrator.search_with_filters``.** New
  use-case + orchestrator entry points that take the full
  filter bundle and an optional restricted source set. The
  legacy ``execute(question)`` / ``search(query)`` path is
  preserved for the ``/api/search`` endpoint.

* **Per-paper source attribution on ``WorkspaceResponse``.**
  Multi-source search always tracked which source returned
  which paper, but the route was stripping that envelope
  when storing papers. The new ``paper_sources`` field on
  ``WorkspaceResponse`` exposes the attribution map to
  the frontend. The frontend renders a small coloured
  "via <source>" badge next to each paper so researchers
  can see at a glance whether a paper came from PubMed,
  OpenAlex, Europe PMC, or bioRxiv. Legacy single-source
  workspaces don't get badges retroactively.

* **Advanced Search modal filter persistence.** The
  modal previously reset to defaults every time it opened.
  Researchers tweaking their filters (e.g. "last 5 years,
  reviews only, OpenAlex") would lose the configuration on
  the next modal open. The filter bundle now persists in
  localStorage (``bioresearch-ai:advanced-search-filters:v1``)
  with safe fallbacks for missing storage, malformed JSON,
  and thrown exceptions. The override query field is
  intentionally not persisted — it's a one-shot per-modal
  value that should align with the workspace's question.

* **Named Advanced Search presets.** Researchers can now
  save the current filter bundle under a name (e.g.
  "Last 5 years, reviews only, OpenAlex") and recall it
  with one click. Presets are persisted in localStorage
  (``bioresearch-ai:adv-search-presets:v1``) and shared
  across workspaces. The new "Saved presets" section in
  the modal lists existing presets with per-row load and
  delete buttons, plus a "Save preset" input. Empty /
  whitespace-only names are rejected; same-name presets
  overwrite (newest-first sort).

* **bioRxiv lock indicator now explains why it's gated.**
  The lock chip on the bioRxiv source checkbox used to
  say "date window required" — that told the user what
  to do without explaining the reason. It now reads
  "chronological dump — set date window" with a tooltip
  carrying the longer source hint, so researchers
  understand that bioRxiv has no keyword search and only
  indexes chronological preprints.

* **Bootstrap popup: alphabetical provider list with MiniMax
  default.** The provider dropdown was previously grouped
  by region (US / CN / EU) which made it hard to scan. The
  list is now sorted alphabetically by ``display_name`` and
  the region is preserved in the label (e.g. ``MiniMax
  [CN]``). The default provider is now ``minimax`` (with
  ``MiniMax-M3`` as the model), reflecting the user-facing
  workflow on this host. The bootstrap CLI accepts provider
  slugs (e.g. ``openai``) in addition to numeric indices, so
  tests are no longer brittle to the list order. The
  ``LOCAL_MODELS`` list is also alphabetical, and a new
  ``sorted_by_display_name()`` helper on the LLM provider
  catalog exposes the same ordering to any future caller.

* **Bootstrap wizard skips when ``.env`` has valid creds.**
  Previously the wizard popped up every time
  ``python3 bootstrap.py`` was run, even when the existing
  ``.env`` already had everything needed. The new
  ``_env_has_valid_creds()`` helper checks the minimum
  viable config (a valid ``DEFAULT_LLM_PROVIDER`` slug, the
  provider's API key env var with a non-empty value for
  non-local providers, and a non-empty ``PUBMED_EMAIL``)
  and skips the wizard automatically. A new ``--wizard``
  flag forces the wizard back for re-configuration.
  Optional fields (``PUBMED_API_KEY``, ``OLLAMA_MODEL``,
  custom ``BASE_URL``) don't disqualify the env.

* **OpenAlex fallback for missing DOI abstracts.** When
  CrossRef returns a paper with no abstract (common for
  book chapters, conference proceedings, and theses),
  the resolver now falls back to OpenAlex. OpenAlex is
  also free, no API key required, and stores abstracts
  as a positional-token inverted index. We reconstruct
  the abstract by sorting tokens by their positions and
  joining with spaces. The fallback only overrides the
  abstract field — the rest of the record (title,
  authors, year, DOI) stays from CrossRef. Network
  errors, 404s, malformed responses, and missing
  abstracts are all handled silently so the resolver
  never crashes the bulk-add flow.

* **Action bar auto-enables Summarize when papers exist.**
  Two paths populate the workspace with papers (the
  legacy ``LiteratureSearch`` and the new
  ``AdvancedSearchModal``), but neither used to update
  the FSM state the action bar reads. With 20 papers
  in the workspace, ``Summarize`` stayed disabled because
  the store's ``currentWorkspace`` was still in
  ``CREATED``. The store now mirrors the backend FSM
  transition (CREATED + ADD_PAPER → PAPERS_RETRIEVED) when
  papers are added, and the modal's submit handler calls
  ``setCurrentWorkspace(response)`` with the backend's full
  view. The ``"Search PubMed"`` button is now labeled
  ``"Advanced Search…"`` with a real ellipsis hint that it
  opens the multi-source modal. The dedup-by-PMID logic
  was also fixed — two papers with the same PMID in the
  incoming batch now correctly dedupe (the previous
  filter only checked the existing workspace).

* **Favicon regenerated.** The committed ``favicon.ico``
  was Targa-format garbage (32x29474 pixels) that
  browsers couldn't decode, so the tab logo was
  invisible even though ``index.html`` correctly
  referenced it. The file is now a proper Windows icon
  resource (16x16 + 32x32 + 48x48, 15 KB) regenerated
  from the existing ``favicon.svg``. New regression
  tests verify the index.html link, the SVG, and the
  ICO header bytes.

### Removed

* **AddPapersPanel — "Manual" tab.** Replaced by the DOI +
  PDF two-tab layout. The form had a slow "fill every field"
  workflow that real researchers almost never do.
* **AddPapersPanel — "PMID / DOI" tab label.** Now "DOI"
  (single label, single identifier type, single icon).
* **"PDF parsing is on the roadmap" toast.** The PDF tab is
  real now, so the "PDF" card in the empty-state workflow
  picker drops a file instead of showing the placeholder.

### Changed

* **Workspace.tsx — identifier naming.** ``identifierInputRef``
  / ``focusIdentifierInput`` are now ``doiInputRef`` /
  ``focusDoiInput`` for clarity (the input is DOI-only).
  Comments referencing PMID are updated.

### Fixed

* **CSS dead-code cleanup.** Removed unused
  ``.add-papers-manual-toggle`` / ``.add-papers-manual-form`` /
  ``.add-papers-manual-actions`` / ``.add-papers-row`` rules
  (the JSX that used them was deleted).

* **Title-driven paper recovery.**
  ``POST /workspaces/{id}/papers/from-title`` accepts a free-text
  title (plus optional first-author / journal / year hints) and
  resolves it via PubMed ESearch. This is the catch-all for the
  PDF upload flow: when the first page doesn't contain a
  recognisable DOI or PMID, the frontend offers an inline
  "Type the paper title" form that hits this endpoint.
  ``WorkspaceOrchestrator.resolve_and_add_by_title`` is a
  recording action — it layers one paper on top of whatever the
  workspace already has, no FSM advance required.

* **IdentifierResolver for PMIDs and DOIs.** New
  ``app/infrastructure/pubmed/identifier_resolver.py``
  classifies PMIDs (1-8 digits) and DOIs (10.xxxx/yyyy), routes
  each to its native upstream (PubMed EFetch for PMIDs, CrossRef
  REST for DOIs), and returns a uniform ``Paper`` list. Used by
  the bulk paste, one-shot fetch, and PDF upload flows.

* **PDF drag-and-drop uploader.** The PDF tab in
  ``AddPapersPanel`` is now a real drag-and-drop surface backed by
  ``POST /workspaces/{id}/papers/from-pdf``. The endpoint extracts
  the first page with ``pypdf`` and runs it through the
  ``IdentifierResolver``. Scanned PDFs with no recognisable
  identifiers get the inline title-fallback form.

* **Manual paper upload routes.**
  ``POST /workspaces/{id}/papers`` and
  ``DELETE /workspaces/{id}/papers/{paper_id}`` expose
  ``ADD_PAPER`` / ``REMOVE_PAPER`` over HTTP so the frontend
  can add papers that aren't in PubMed.

* **Vitest frontend test runner.** New ``npm test`` target runs
  56+ component / hook tests under jsdom. Includes jest-dom
  matchers, ``@testing-library/react`` for component tests, and
  ``useKeyboardShortcut`` (20), ``AddPapersPanel`` (28),
  ``LiteratureSearch`` (14), plus a smoke test for the setup
  itself.

* **PC-first keyboard shortcut hook.** New
  ``useKeyboardShortcut`` hook with ``Ctrl+K`` (PC) / ``⌘K`` (Mac)
  hint detection. The hook is wired into ``Workspace`` so the
  right input is focused based on FSM state — PMID/DOI textarea
  at CREATED, PubMed search input otherwise.

* **Inline API error class.** New ``APIError`` exported from
  ``client.ts`` exposes ``status`` and ``detail`` so callers can
  distinguish error codes (``no_identifiers_found``,
  ``title_no_confident_match``) without string-matching messages.

* **Conftest for test environment.** ``tests/conftest.py`` sets
  ``PUBMED_EMAIL``, ``OPENAI_API_KEY``, and other settings so the
  test suite runs on a clean machine without operator setup.

### Changed

* **WorkspaceOrchestrator.add_papers_bulk** is now a thin wrapper
  around a new private ``_add_papers_bulk`` helper. The
  ``resolve_and_add_by_title`` path shares the same dedupe /
  FSM-guard logic instead of duplicating it.

* **docker-compose.yml** mounts the parent directory
  (``./:/app/data``) instead of the database file, and passes
  ``DATABASE_URL`` so the container writes the SQLite file in
  the right place. See ``tests/unit/test_database_path.py`` for
  the regression guards.

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

### Added

* **PDF drag-and-drop upload.** The PDF tab in the AddPapersPanel
  is now a real drop zone, not a placeholder. The user drags a
  PDF (or clicks to pick one) and the new
  ``POST /workspaces/{id}/papers/from-pdf`` endpoint extracts
  DOI / PMID from the first page using ``pypdf`` (pure-Python,
  no ML deps), resolves them through the existing
  ``IdentifierResolver``, and adds the resulting papers in one
  transaction. Scanned PDFs surface a clear "no identifier
  found" error so the user can fall back to the PMID/DOI tab.

* **Select-to-add PubMed search.** ``LiteratureSearch`` now
  shows results as a checkbox list with "Add selected" — the
  user picks which papers enter the workspace instead of
  auto-appending everything. All results are selected by
  default; the user un-checks the irrelevant ones. The old
  "fetch and forget" auto-append was the consultant's Workflow
  C complaint and is now gone.

* **Ctrl/Cmd+K global shortcut.** The workspace now binds a
  global keyboard shortcut that focuses the right input based
  on the FSM state — at CREATED with zero papers it focuses
  the PMID/DOI textarea, otherwise it focuses the PubMed
  search input. PC users see ``Ctrl+K``; Mac users see ``⌘K``
  (the binding is the same because browsers on Mac fire
  ``ctrlKey`` for both Ctrl and Cmd). The hint is shown next
  to the relevant input and on the empty-state cards.

* **Three-zone empty state.** When a workspace has zero papers
  the page now shows three clickable workflow cards ("I have
  specific papers", "I want to discover papers", "I have PDFs
  on my machine") instead of the bare "No papers yet" message.
  Each card brings the matching entry surface into view —
  PMID/DOI input, PubMed search, or (eventually) PDF drop.
  Driven by UX consultation with bench-biology and clinical-
  biomedical-engineering personas.

* **Two-tier action bar.** The action bar is now split into a
  primary tier (Search PubMed) that's always visible, and a
  secondary tier (Summarize, Compare, Generate Report, Complete,
  Retry, Clear All) that's collapsed by default at CREATED and
  auto-expands once papers exist. The previous design listed all
  seven actions in a single row, which buried the most useful
  primary action in a wall of disabled buttons.

* **Identifier-first paper entry with bulk paste.** A new
  `POST /workspaces/{id}/papers/resolve` endpoint accepts a
  list of PMIDs and/or DOIs (one per line, comma-separated) and
  returns per-identifier status chips. The companion
  `POST /workspaces/{id}/papers/bulk` adds all resolved papers
  in one transaction; `POST /workspaces/{id}/papers/fetch`
  resolves one identifier and adds it in a single call (the
  identifier is a query parameter so DOIs with `/` work). The
  resolver uses PubMed EFetch for PMIDs and CrossRef for DOIs,
  both via `httpx` (no extra SDK dependency). The frontend's
  AddPapersPanel exposes the bulk workflow as the default tab.

* **Manual paper upload.** A new `POST /workspaces/{id}/papers`
  endpoint lets the user add a paper to a workspace manually,
  without going through PubMed. Useful when the user already
  knows the paper they want to study (and would rather not
  spend API quota on a search) or when the paper isn't indexed
  in PubMed at all. Title is the only required field; authors,
  journal, year, abstract, DOI, PMID, keywords, and URL are
  optional. The companion `DELETE
  /workspaces/{id}/papers/{paper_id}` endpoint removes a paper
  by PMID or DOI. Both endpoints respect the FSM: an illegal
  action returns HTTP 409 with `allowed_actions` in the body,
  the same contract as every other action endpoint. The
  frontend has a new "Upload Paper" toggle in the action bar
  that opens a compact form.

* **Proper SVG favicon.** A DNA-double-helix favicon (with
  cyan rungs and amber circuit nodes) now ships at
  `frontend/public/favicon.svg`. The previous `favicon.ico`
  was a malformed Targa image; the HTML referenced an
  unfindable `favicon.svg`, leaving the browser tab empty.

### Fixed

* **Workspace layout rendered as raw inline text.** The lab-bench
  stylesheet (`frontend/src/styles/lab-bench.css`) was never
  imported, so every `.lab-bench-*` class had no CSS — the
  lifecycle strip ("LifecycleCREATED0%"), the available-action
  pills ("Available actions:add_papersearch"), and the station
  labels all stacked as plain text without flex/inline layout.
  The `index.css` file now imports `lab-bench.css` after
  `components.css` so the lab-bench styles can override the
  defaults. The lifecycle strip now renders horizontally with
  proper spacing, dots, and pill labels.

* **"Test credentials" fails for MiniMax** with "'openai' Python package is not installed".**
  ``probe_credentials.py`` was hardcoded to use the OpenAI Python
  client for every non-local provider. MiniMax uses the Anthropic
  Messages API (``/v1/messages``) at ``https://api.minimax.io/anthropic``,
  so the OpenAI client couldn't talk to it. The probe now
  dispatches based on a new ``protocol`` field in the catalog:
  ``openai`` for the OpenAI-compatible ``/chat/completions`` schema,
  ``anthropic`` for the Anthropic Messages API, ``local`` for
  Ollama. MiniMax and Anthropic-style hosts are routed to the
  new ``probe_anthropic_compat`` function which uses ``httpx``
  directly — no SDK dependency. The catalog also got a
  ``base_url`` for Anthropic (``https://api.anthropic.com/v1``,
  the OpenAI-compat layer that the existing
  ``AnthropicProvider`` already uses) so the GUI's default
  is now correct instead of empty.

* **Bootstrap saved an empty ``BASE_URL`` for MiniMax / non-OpenAI
  providers.** The CLI wizard's default base URL was hardcoded
  to ``""`` for anything other than OpenAI. Now it falls back
  to the catalog value (``entry.base_url``), or for Anthropic
  uses ``https://api.anthropic.com`` as a sensible default.

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
