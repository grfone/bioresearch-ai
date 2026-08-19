#!/usr/bin/env bash
#
# verify-ci.sh -- cheaper end-to-end smoke test for
# bioresearch-ai. Assumes the container is ALREADY running
# (e.g. started by a previous verify.sh, by docker compose
# up, or by a CI workflow step).
#
# Does NOT:
#   - Run bootstrap.py (no build, no .env setup)
#   - Tear down the container (caller's responsibility)
#
# DOES:
#   - Pre-flight: verify curl, jq are on PATH
#   - Wait for /health to return "healthy" (max 60s)
#   - Run the same admin smoke-test battery as verify.sh
#     (hits /admin/enricher-stats, /admin/orchestrator-stats,
#      creates a workspace, fetches a real DOI, exercises
#      /admin/papers/refresh and DELETE /admin/enricher-cache)
#
# Use this when:
#   - The container is already running and you want a cheap
#     re-run of just the smoke checks (no rebuild).
#   - A CI workflow has started the container in a previous
#     step and wants to verify the admin endpoints before
#     declaring success.
#
# Exit codes:
#   0 - all checks passed
#   1 - one or more checks failed
#   2 - dependency missing (curl, jq)
#
# Set BACKEND_PORT to override the backend URL. Default: 8000.

set -uo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BASE_URL="http://localhost:${BACKEND_PORT}"
LOG_PREFIX="VERIFY-CI"

cd "${PROJECT_ROOT}" || {
    echo "${LOG_PREFIX}: cannot cd to ${PROJECT_ROOT}" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Shared smoke-test library (helpers + admin endpoint checks)
# ---------------------------------------------------------------------------
# Same shared source of truth as verify.sh -- adding a new
# check here updates both scripts automatically.
# shellcheck source=./verify-checks.sh
source "${SCRIPT_DIR}/verify-checks.sh"

# ---------------------------------------------------------------------------
# 0. Pre-flight
# ---------------------------------------------------------------------------
echo "${C_BOLD}${LOG_PREFIX}: cheap end-to-end smoke test for bioresearch-ai${C_RESET}"
echo "Project: ${PROJECT_ROOT}"
echo "Backend: ${BASE_URL}"
echo "Assumes the container is already running (no build, no teardown)."

step "Pre-flight checks"
require_tool curl "apt install curl (Debian/Ubuntu) / brew install curl (macOS)"
require_tool jq "apt install jq (Debian/Ubuntu) / brew install jq (macOS)"
ok "curl and jq present"

# ---------------------------------------------------------------------------
# 1. Wait for /health (assume container is up)
# ---------------------------------------------------------------------------
step "Waiting for /health to return healthy (max 60s)"
# We assume the container is already up (started by a CI
# step or by docker compose up). Just wait for it to be
# responsive.
if wait_for_healthy 60; then
    ok "/health responded with status=healthy"
else
    fail "/health did not respond within 60s"
    fail "is the container running? Try: docker compose up -d"
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Run the shared smoke-test battery
# ---------------------------------------------------------------------------
# This calls the same function verify.sh uses, so the
# checks are identical: cache stats, FSM counts,
# workspace + DOI fetch, force-refresh, clear-cache.
if ! run_admin_smoke_tests; then
    # The library already incremented fail_count and
    # printed which step failed. Exit with the
    # appropriate code.
    print_summary 1
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
# print_summary exits with code 0 on success, 1 on failure.
print_summary 1