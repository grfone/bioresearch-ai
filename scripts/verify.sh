#!/usr/bin/env bash
#
# verify.sh -- end-to-end smoke test for bioresearch-ai.
#
# Runs the full bootstrap (build + start container), then
# exercises every /admin/* diagnostic endpoint plus a
# functional smoke (create a workspace, fetch a Nature
# DOI, verify abstract + inferred_abstract contract).
# Tears down on success or failure.
#
# Use this when:
#   - You want to confirm a fresh checkout actually works
#     end-to-end (the "I don't know if you work properly"
#     worry).
#   - You changed the Dockerfile, container config, or
#     admin endpoints and want a quick go/no-go.
#   - You want to validate a CI artifact before merging.
#
# Exit codes:
#   0  - all checks passed
#   1  - one or more checks failed (teardown still runs)
#   2  - dependency missing (curl, jq, docker, python3)
#
# This script is INTENTIONALLY verbose -- it prints every
# step's progress so a reviewer can see exactly where
# things went wrong without re-running with extra flags.
#
# Designed to be safe to run repeatedly. Each step is
# idempotent: existing containers are stopped, existing
# images are deleted, .env is removed after teardown.

set -uo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BASE_URL="http://localhost:${BACKEND_PORT}"
LOG_PREFIX="VERIFY"

# Test DOI -- the famous LeCun/Bengio/Hinton "Deep learning"
# review in Nature (2015). Its abstract is reliably
# available from the publisher, ~807 chars. Picked because
# it has been used in many of our prior live-verify sessions
# and we know what success looks like.
TEST_DOI="10.1038/nature14539"
EXPECTED_ABSTRACT_LEN="${EXPECTED_ABSTRACT_LEN:-807}"

# Allow caller to override the workdir, e.g. for sandboxed
# environments where the project lives elsewhere.
cd "${PROJECT_ROOT}" || {
    echo "${LOG_PREFIX}: cannot cd to ${PROJECT_ROOT}" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Shared smoke-test library (helpers + admin endpoint checks)
# ---------------------------------------------------------------------------
# Sourced, not executed -- defines: step/ok/fail/warn/require_tool,
# http_get/http_post/http_delete, wait_for_healthy,
# run_admin_smoke_tests, print_summary. Both verify.sh and
# verify-ci.sh source this file so they share one source of
# truth for the smoke checks.
# shellcheck source=./verify-checks.sh
source "${SCRIPT_DIR}/verify-checks.sh"

# The shared library initialises its own step_count and
# fail_count counters; we don't need to repeat that here.

# Track whether we've started a container so teardown is
# conditional. Initialized to "no" so a script that fails
# before starting anything doesn't try to tear down.
CONTAINER_STARTED=0

teardown() {
    # teardown -- always run on exit. Stops the container
    # and removes the image. Best-effort; never raises.
    printf "\n%s%s[cleanup]%s Tearing down...\n" "$C_YELLOW" "$C_BOLD" "$C_RESET"
    if [[ "${CONTAINER_STARTED}" == "1" ]]; then
        docker compose --file "${PROJECT_ROOT}/docker-compose.yml" down \
            >/dev/null 2>&1 || warn "docker compose down failed"
    fi
    # Remove the image so the next verify run is a clean
    # build. This catches Dockerfile regressions that
    # would otherwise be hidden by a stale layer cache.
    docker rmi -f bioresearch-ai:minimal >/dev/null 2>&1 || true
    # Clean up .env if we created it
    if [[ -f "${PROJECT_ROOT}/.env" ]]; then
        rm -f "${PROJECT_ROOT}/.env"
        ok "removed .env"
    fi
}
trap teardown EXIT

# ---------------------------------------------------------------------------
# 0. Pre-flight
# ---------------------------------------------------------------------------
echo "${C_BOLD}${LOG_PREFIX}: end-to-end smoke test for bioresearch-ai${C_RESET}"
echo "Project: ${PROJECT_ROOT}"
echo "Backend: ${BASE_URL}"
echo "Test DOI: ${TEST_DOI}"

step "Pre-flight checks"
require_tool curl "apt install curl (Debian/Ubuntu) / brew install curl (macOS)"
require_tool jq "apt install jq (Debian/Ubuntu) / brew install jq (macOS)"
require_tool docker "https://docs.docker.com/engine/install/"
require_tool python3 "apt install python3 (Debian/Ubuntu) / brew install python@3.12 (macOS)"
ok "all required tools present"

# ---------------------------------------------------------------------------
# 1. Clean slate
# ---------------------------------------------------------------------------
step "Cleaning up any prior container/image"
# If a previous verify run died mid-flight, the container
# and image may still be around. Best-effort cleanup; we
# don't fail the script if these aren't present.
docker compose --file "${PROJECT_ROOT}/docker-compose.yml" down \
    >/dev/null 2>&1 || true
docker rm -f bioresearch-ai-backend 2>/dev/null || true
docker rmi -f bioresearch-ai:minimal 2>/dev/null || true
ok "cleanup complete"

# ---------------------------------------------------------------------------
# 2. .env setup
# ---------------------------------------------------------------------------
step "Creating .env with stub credentials"
# The verify script doesn't require real LLM creds --
# the smoke tests deliberately use DOIs whose abstracts
# come from the deterministic meta-tag path, not the LLM
# extractor. We give the container valid-looking but fake
# creds so its startup doesn't 500 on missing env vars.
cat > "${PROJECT_ROOT}/.env" <<EOF
APP_ENVIRONMENT=development
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-4o-mini
DEFAULT_LLM_TEMPERATURE=0
OPENAI_API_KEY=sk-verify-stub-not-real-credentials
OPENAI_BASE_URL=https://api.openai.com/v1
PUBMED_EMAIL=verify@example.com
DATABASE_URL=sqlite:////app/data/bioresearch.db
ABSTRACT_ENRICHER_ENABLED=true
LLM_ABSTRACT_EXTRACTION_ENABLED=false
LOG_LEVEL=INFO
EOF
ok ".env written"

# ---------------------------------------------------------------------------
# 3. Bootstrap
# ---------------------------------------------------------------------------
step "Running python3 bootstrap.py --skip-gui --no-browser"
# The bootstrap script handles:
#   - Docker BuildKit installation
#   - Building bioresearch-ai:minimal
#   - Starting the container
#   - Waiting for the backend to come up (its own wait
#     loop that polls /api for up to 120s)
# We use --skip-gui (no Tk wizard popup) and --no-browser
# (don't open the URL in a browser after boot).
if ! python3 bootstrap.py --skip-gui --no-browser; then
    fail "bootstrap.py exited non-zero"
    exit 1
fi
CONTAINER_STARTED=1
ok "bootstrap.py completed"

# ---------------------------------------------------------------------------
# 4. Wait for /health (in case bootstrap's wait loop exited
#    early on a flaky health check)
# ---------------------------------------------------------------------------
step "Waiting for /health to return healthy"
if wait_for_healthy 60; then
    ok "/health responded with status=healthy"
else
    fail "/health did not respond within 60s"
    exit 1
fi

# ---------------------------------------------------------------------------
# Run the shared admin smoke-test battery. This checks:
#   - /admin/enricher-stats (cache stats shape)
#   - /admin/orchestrator-stats (FSM state counts + total)
#   - workspace creation + Nature DOI fetch (functional)
#   - /admin/papers/refresh/<doi> (force-refresh)
#   - DELETE /admin/enricher-cache (full purge)
# Implemented in verify-checks.sh so verify-ci.sh shares the
# same logic.
if ! run_admin_smoke_tests "${TEST_DOI}"; then
    print_summary 1
fi

# Print summary (this exits 0 on success, 1 on failure).
print_summary 1