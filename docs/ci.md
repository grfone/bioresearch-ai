# CI / Continuous Integration

This document covers the GitHub Actions workflows that run
on every push and pull request. The actual workflow files
live in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

## Four parallel jobs

| Job | What it does | Why |
|-----|--------------|-----|
| `backend-tests` | Install `poppler-utils` + `texlive-latex-*` + `pip install -r requirements/minimal-requirements.txt` + `pytest tests/` | Catches "tests pass with full dev deps but break in the slim Docker image" regressions. PDF text-extraction tests need `pdftotext`; LaTeX live-compile is opt-in via `BIORESEARCH_RUN_LATEX_COMPILE=1`. |
| `frontend-tests` | `npm ci` + `npm test` + `npm run build` | Validates React components, hooks, and TypeScript models |
| `docker-build` | `docker build --target backend-minimal` + container smoke test | Validates the Dockerfile builds cleanly AND that the resulting container boots and responds healthy |
| `integration-redis-tests` | Spins up a real Redis service + `pytest tests/integration/` | Validates the multi-worker cache backend (ADR-003) doesn't fragment across workers |

### Why four separate jobs?

Different layers of defence. A test that passes locally
with `requirements.txt` (full dev deps) but fails on
`minimal-requirements.txt` (what the slim image ships)
is a **production regression** that wouldn't show up
until a real user pulls the image. The backend-tests
job runs against the minimal set precisely to catch
that class of bug.

A Dockerfile that builds but whose container crashes
on startup is similarly invisible from a unit test --
the docker-build job's smoke test catches that.

The integration-redis-tests job catches a different
class of bug entirely: state fragmentation across
workers. An in-process cache that "works" on a single
worker but loses entries when the orchestrator is
scaled horizontally is invisible to the backend-tests
job (which runs single-process) and invisible to the
docker-build job (which builds, not serves traffic).
The real-Redis integration test is the only place
this is exercised.

### PDF / LaTeX test dependencies

The CI runner on `ubuntu-latest` does NOT ship
`poppler-utils` (for `pdftotext`) or
`texlive-latex-extra` (for `textgreek`) by default.
Both are installed by the `Install poppler-utils
(for PDF text extraction in tests)` step in
`backend-tests`:

```yaml
- name: Install poppler-utils (for PDF text extraction in tests)
  run: |
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends \
      poppler-utils \
      texlive-latex-recommended \
      texlive-fonts-recommended \
      texlive-latex-extra
```

The reportlab PDF tests use
`_extract_text_or_skip` which gracefully `pytest.skip`s
when `pdftotext` is unavailable — but on CI it's
present and runs. The LaTeX live-compile test
(`TestLatexCompiles.test_generated_latex_compiles`)
is **opt-in** via `BIORESEARCH_RUN_LATEX_COMPILE=1`;
CI skips it.

### Why no live smoke check?

The live `/admin/*` smoke check requires:

- Real LLM credentials
- Network access to CrossRef, OpenAlex, etc.
- A real DOI to fetch

CI doesn't have any of these. The manual `make verify`
flow (described in the project root README) is the right
tool for end-to-end contract checks. CI is for fast,
hermetic regressions that don't depend on external
resources.

### Concurrency

The workflow uses `concurrency.cancel-in-progress: true`.
If you push a follow-up commit while CI is running,
GitHub cancels the in-flight run and starts a new one.
Saves runner minutes when iterating quickly.

### Local validation

Before pushing workflow changes, you can validate each
job locally:

```bash
# Backend job simulation
python3 -m venv /tmp/ci-test && \
  sudo apt-get install -y --no-install-recommends \
    poppler-utils texlive-latex-recommended \
    texlive-fonts-recommended texlive-latex-extra && \
  /tmp/ci-test/bin/pip install -r requirements/minimal-requirements.txt && \
  /tmp/ci-test/bin/pip install pytest pytest-asyncio && \
  APP_ENVIRONMENT=test DATABASE_URL='sqlite:///:memory:' \
  PUBMED_EMAIL=ci@example.com \
  OPENAI_API_KEY=stub OPENAI_BASE_URL=http://localhost:9 \
  DEFAULT_LLM_PROVIDER=openai ABSTRACT_ENRICHER_ENABLED=false \
  LLM_ABSTRACT_EXTRACTION_ENABLED=false LOG_LEVEL=WARNING \
  PYTHONPATH=. /tmp/ci-test/bin/python -m pytest tests/ -q

# Frontend job simulation
cd frontend && npm ci && npm test && npm run build

# Docker job simulation
docker build --target backend-minimal -t bioresearch-ai:ci-minimal .
docker run -d --name ci-smoke -p 8001:8000 \
  -e APP_ENVIRONMENT=test \
  -e DEFAULT_LLM_PROVIDER=openai \
  -e OPENAI_API_KEY=stub \
  -e OPENAI_BASE_URL=http://localhost:9 \
  -e PUBMED_EMAIL=ci@example.com \
  -e 'DATABASE_URL=sqlite:////tmp/ci-smoke.db' \
  -e ABSTRACT_ENRICHER_ENABLED=false \
  -e LLM_ABSTRACT_EXTRACTION_ENABLED=false \
  bioresearch-ai:ci-minimal
curl http://localhost:8001/health
docker rm -f ci-smoke
docker rmi -f bioresearch-ai:ci-minimal

# Real-Redis integration job simulation (requires Docker)
docker run -d --name ci-redis -p 6379:6379 redis:7-alpine
REDIS_URL=redis://localhost:6379/0 \
  PYTHONPATH=. /tmp/ci-test/bin/python -m pytest tests/integration/ -q
docker rm -f ci-redis
```

## Recent CI fixes

- **`Install poppler-utils (for PDF text extraction in tests)` step** — added 2026-08-30 (commit `cde368c`) so the reportlab PDF tests can call `pdftotext` and assert body content. Without it, every body-content test would silently pass.
- **`BIORESEARCH_RUN_LATEX_COMPILE=1` opt-in** — added 2026-08-30 (commit `0af713f`) so the LaTeX live-compile test runs only on dev machines that have the full TeX Live stack installed. CI skips.
