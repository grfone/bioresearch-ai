# Complete Repository Structure

This document shows the file layout as it actually lives on
disk. The structure is enforced by the directory tree in
`app/` and `frontend/` (see [ADR-001](adr/ADR-001-adopt-clean-architecture.md)
and [ADR-014](adr/ADR-014-prometheus-metrics-health-probes.md)).

## Top level

```text
bioresearch-ai/
├── app/                  # Backend (FastAPI + Python)
├── frontend/             # Frontend (React + Vite)
├── tests/                # pytest suite (806 unit + 35 integration)
│   ├── unit/
│   └── integration/
├── docs/                 # All documentation
│   ├── adr/              # 15 Architecture Decision Records
│   ├── gifs/
│   ├── images/
│   ├── architecture.md
│   ├── ci.md
│   ├── multi-worker-cache-investigation.md
│   └── repository.md     # (this file)
├── scripts/              # verify-ci.sh, etc.
├── examples/
├── notebooks/
├── .github/workflows/    # ci.yml — 4 parallel jobs
├── bootstrap.py          # Foolproof Docker installer
├── main.py               # ASGI entrypoint
├── requirements/
│   ├── minimal-requirements.txt
│   └── requirements.txt
├── ARCHITECTURE.md
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── INSTALL.md
├── LICENSE
├── README.md
├── ROADMAP.md
├── SECURITY.md
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── pytest.ini
```

## Backend — `app/`

```text
app/

├── api/
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── admin.py            # /admin/enricher-cache, /admin/enricher-stats
│   │   ├── health.py           # /health, /health/sanitizer,
│   │   │                       # /health/title-fallback, /metrics
│   │   ├── papers.py
│   │   ├── report.py
│   │   ├── search.py
│   │   ├── workspace.py        # GET / POST /workspaces/{id}
│   │   └── workspace_actions.py  # POST /workspaces/{id}/actions/{action}
│   │
│   ├── schemas/                # Pydantic wire-format models
│   │   ├── __init__.py
│   │   ├── report_request.py
│   │   ├── report_response.py
│   │   ├── search_request.py
│   │   ├── search_response.py
│   │   ├── workspace_request.py
│   │   └── workspace_response.py
│   │
│   └── __init__.py

├── application/
│   ├── agents/                 # LangGraph research-pipeline agents
│   ├── prompts/
│   │   └── __init__.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── research_assistant.py
│   │   ├── workspace_service/  # WorkspaceOrchestrator runtime
│   │   └── citation_sanitizer.py  # Anti-fabrication guard
│   │
│   ├── use_cases/
│   │   ├── __init__.py
│   │   ├── create_workspace.py
│   │   ├── generate_report.py
│   │   ├── get_paper.py
│   │   ├── get_workspace.py
│   │   ├── search_literature.py
│   │   ├── summarize_papers.py
│   │   └── update_workspace.py
│   │
│   ├── validation/
│   │
│   └── workflows/

├── config/
│   ├── __init__.py
│   ├── container.py            # DI container
│   ├── database.py
│   ├── llm.py
│   ├── logging.py
│   ├── pubmed.py
│   └── settings.py

├── core/
│   ├── enums/
│   │   ├── __init__.py
│   │   ├── citation_style.py
│   │   ├── environment.py
│   │   ├── llm_provider.py
│   │   ├── log_level.py
│   │   ├── report_format.py
│   │   ├── search_source.py
│   │   └── workspace_state.py   # FSM transition table
│   │
│   ├── __init__.py
│   ├── exceptions.py
│   └── logger.py

├── domain/
│   ├── __init__.py
│   ├── entities/
│   │   ├── author.py
│   │   ├── citation.py
│   │   ├── journal.py
│   │   ├── paper.py
│   │   ├── published_report.py  # PDF / LaTeX bytes
│   │   ├── research_question.py
│   │   ├── research_report.py   # Synthesis output
│   │   ├── research_session.py
│   │   ├── summary.py
│   │   └── workspace.py
│   │
│   ├── interfaces/
│   │   ├── __init__.py
│   │   ├── knowledge_base.py
│   │   ├── literature_searcher.py
│   │   ├── llm_provider.py
│   │   ├── pdf_generator.py
│   │   └── workspace_repository.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── llm_response.py
│   │   └── prompt.py
│   │
│   └── value_objects/

├── infrastructure/
│   ├── cache/
│   │   ├── __init__.py
│   │   ├── cache_protocol.py    # Pluggable cache interface
│   │   ├── in_memory_cache.py   # Single-worker default
│   │   └── redis_cache.py       # Multi-worker shared cache
│   │
│   ├── latex/
│   │   ├── __init__.py
│   │   └── latex_generator.py   # /published-report.tex
│   │
│   ├── literature/
│   │   ├── __init__.py
│   │   ├── biorxiv_client.py
│   │   ├── europe_pmc_client.py
│   │   ├── multi_source.py      # Fan-out + dedup + ranking
│   │   └── openalex_client.py
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base_provider.py
│   │   ├── llm_factory.py
│   │   ├── openai_provider.py   # OpenAI-compatible base
│   │   ├── ollama_provider.py
│   │   ├── anthropic_provider.py
│   │   ├── azure_openai_provider.py
│   │   ├── alibaba_provider.py
│   │   ├── baidu_provider.py
│   │   ├── baichuan_provider.py
│   │   ├── bytedance_provider.py
│   │   ├── deepseek_provider.py
│   │   ├── genimi_provider.py
│   │   ├── hauwei_provider.py
│   │   ├── minimax_provider.py
│   │   ├── moonshot_provider.py
│   │   ├── sensetime_provider.py
│   │   ├── step_fun_provider.py
│   │   ├── tencent_provider.py
│   │   ├── yi_provider.py
│   │   ├── zhipu_provider.py
│   │   ├── report_generator.py
│   │   ├── report_mapper.py
│   │   └── title_fallback.py    # H1 fallback (ADR-013)
│   │
│   ├── observability/
│   │   ├── __init__.py
│   │   └── prometheus_exposition.py  # /metrics (ADR-014)
│   │
│   ├── pdf/
│   │   ├── __init__.py
│   │   └── reportlab_generator.py    # /published-report.pdf
│   │
│   ├── pubmed/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── mapper.py
│   │   └── provider.py
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   └── sqlite_workspace_repository.py
│   │
│   ├── mcp/
│   │
│   └── a2a/

├── presentation/             # Legacy Streamlit (no longer used in production)
│   ├── components/
│   ├── pages/
│   ├── state/
│   └── view_models/
│
├── tools/
│
└── __init__.py
```

## Frontend — `frontend/`

```text
frontend/

├── public/
│   └── favicon.ico
│
├── src/
│   ├── api/
│   │   └── client.ts               # runAction overload (ADR-012)
│   │
│   ├── assets/
│   │
│   ├── components/
│   │   ├── Button.tsx
│   │   ├── EvidencePanel.tsx
│   │   ├── LiteratureSearch.tsx
│   │   ├── LoadingSpinner.tsx
│   │   ├── Navigation.tsx
│   │   ├── PaperCard.tsx
│   │   ├── PaperList.tsx
│   │   ├── QuestionInput.tsx
│   │   ├── ReferencesPanel.tsx
│   │   ├── ReportPanel.tsx
│   │   ├── StatusBar.tsx
│   │   └── ToastContainer.tsx
│   │
│   ├── hooks/
│   │   └── useWorkspace.ts
│   │
│   ├── layouts/
│   │   └── MainLayout.tsx
│   │
│   ├── lib/                          # New in 0.6 — citation utilities
│   │   ├── citationLink.ts          # linkifyCitationMarkers, linkifyCitationDoi
│   │   └── citationRender.tsx       # renderItemWithCitationLinks
│   │
│   ├── models/
│   │   ├── paper.ts
│   │   ├── report.ts
│   │   └── workspace.ts
│   │
│   ├── pages/
│   │   ├── Home.tsx
│   │   ├── Report.tsx               # Generate PDF / Generate TeX (ADR-010)
│   │   └── Workspace.tsx
│   │
│   ├── state/
│   │   ├── toastStore.ts
│   │   └── workspaceStore.ts
│   │
│   ├── styles/
│   │   ├── components.css
│   │   ├── globals.css
│   │   ├── index.css
│   │   ├── tailwind.css
│   │   ├── utilities.css
│   │   └── variables.css
│   │
│   ├── test/                        # Vitest setup
│   │
│   ├── App.tsx
│   ├── main.tsx
│   └── router.tsx
│
├── index.html
├── package.json
├── postcss.config.js
├── tailwind.config.ts
├── tsconfig.json
└── vite.config.ts
```

## Tests — `tests/`

```text
tests/

├── unit/                              # 806 tests
│   ├── test_app/
│   ├── test_bootstrap_dns_retry.py    # 31 tests (ADR-015)
│   ├── test_citation_sanitizer.py     # Anti-fabrication (ADR-011)
│   ├── test_latex_report_generator.py # 35 tests (ADR-010)
│   ├── test_prometheus_metrics.py     # /metrics (ADR-014)
│   ├── test_reportlab_pdf_generator.py # 37 tests (ADR-010)
│   ├── test_title_fallback.py         # H1 fallback (ADR-013)
│   ├── test_workspace_fsm.py          # 12-state FSM
│   └── ...
│
└── integration/                       # 35 tests (real Redis required)
    └── test_real_redis_cache.py
```

## Docs — `docs/`

```text
docs/

├── adr/                               # 15 ADRs
│   ├── ADR-001-adopt-clean-architecture.md
│   ├── ADR-002-adopt-domain-driven-design.md
│   ├── ADR-003-pluggable-cache-backend.md
│   ├── ADR-004-section-based-abstract-extraction.md
│   ├── ADR-005-multi-identity-paper-dedup.md
│   ├── ADR-006-parallel-multi-source-search.md
│   ├── ADR-007-configurable-pdf-upload-cap.md
│   ├── ADR-008-one-click-report-from-papers-retrieved.md
│   ├── ADR-009-publishing-state.md
│   ├── ADR-010-pdf-and-latex-export.md
│   ├── ADR-011-vancouver-citations-anti-fabrication.md
│   ├── ADR-012-fsm-aware-report-action.md
│   ├── ADR-013-h1-title-fallback.md
│   ├── ADR-014-prometheus-metrics-health-probes.md
│   ├── ADR-015-bootstrap-dns-ipv6-retry-auto-fix.md
│   └── README.md
│
├── gifs/
│   └── demo.gif
│
├── images/
│   ├── architecture.png
│   ├── home.png
│   ├── logo.png
│   ├── report.png
│   └── workspace.png
│
├── architecture.md
├── ci.md
├── multi-worker-cache-investigation.md
└── repository.md                      # (this file)
```

## What changed since 0.1.0

- **`presentation/`** is now legacy (Streamlit); the React frontend
  lives in `frontend/`. The directory is kept for backward
  compatibility but is no longer built.
- **`app/infrastructure/cache/`** is new (ADR-003). The
  pluggable cache backend fixes the per-worker cache
  fragmentation documented in
  `docs/multi-worker-cache-investigation.md`.
- **`app/infrastructure/latex/`** is new (ADR-010). Generates
  the `.tex` source served at `/published-report.tex`.
- **`app/infrastructure/literature/`** is new (ADR-006). Multi-
  source fan-out (PubMed + OpenAlex + Europe PMC + bioRxiv)
  with DOI/PMID/title dedup.
- **`app/infrastructure/observability/`** is new (ADR-014). The
  hand-rolled Prometheus exposition for `/metrics`.
- **`app/infrastructure/pdf/`** is new (ADR-010). Replaced the
  hand-rolled PDF 1.4 generator with reportlab.
- **`app/infrastructure/llm/title_fallback.py`** is new
  (ADR-013). H1 title fallback for the synthesis LLM.
- **`app/domain/services/citation_sanitizer.py`** is new
  (ADR-011). Anti-fabrication guard at ingest.
- **`app/core/enums/workspace_state.py`** now holds a 12-state
  FSM table (was 11 states at 0.1.0; `PUBLISHING` added
  in 0.6).
- **`frontend/src/lib/`** is new (ADR-011). Citation
  linkifier utilities.
- **`tests/`** was empty at 0.1.0; now 806 unit tests +
  35 integration tests.
