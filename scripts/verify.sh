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
# Helpers
# ---------------------------------------------------------------------------
# ANSI colors. Disabled if NO_COLOR is set or stdout is
# not a TTY (e.g. when piped to a file or CI log).
if [[ -z "${NO_COLOR:-}" && -t 1 ]]; then
    C_RED=$'\033[0;31m'
    C_GREEN=$'\033[0;32m'
    C_YELLOW=$'\033[0;33m'
    C_BLUE=$'\033[0;34m'
    C_BOLD=$'\033[1m'
    C_RESET=$'\033[0m'
else
    C_RED="" C_GREEN="" C_YELLOW="" C_BLUE="" C_BOLD="" C_RESET=""
fi

step_count=0
fail_count=0

step() {
    # step "Title" -- print a numbered step heading.
    step_count=$((step_count + 1))
    printf "\n%s%s[%d] %s%s\n" "$C_BLUE" "$C_BOLD" "$step_count" "$1" "$C_RESET"
}

ok() {
    printf "  %sOK%s %s\n" "$C_GREEN" "$C_RESET" "$1"
}

fail() {
    fail_count=$((fail_count + 1))
    printf "  %sFAIL%s %s\n" "$C_RED" "$C_RESET" "$1"
}

warn() {
    printf "  %sWARN%s %s\n" "$C_YELLOW" "$C_RESET" "$1"
}

require_tool() {
    # require_tool NAME -- die if a CLI tool isn't on PATH.
    if ! command -v "$1" >/dev/null 2>&1; then
        printf "%sERROR%s: required tool '%s' not found on PATH\n" \
            "$C_RED" "$C_RESET" "$1" >&2
        printf "Install: %s\n" "$2" >&2
        exit 2
    fi
}

http_get() {
    # http_get PATH -- curl GET with timeout, returns body
    # or empty on non-2xx.
    local path="$1"
    curl -fsS --max-time 30 "${BASE_URL}${path}" 2>/dev/null
}

http_post() {
    # http_post PATH [ json_body ]
    local path="$1"
    local body="${2:-}"
    if [[ -n "$body" ]]; then
        curl -fsS --max-time 60 -X POST \
            -H "Content-Type: application/json" \
            -d "$body" "${BASE_URL}${path}" 2>/dev/null
    else
        curl -fsS --max-time 60 -X POST "${BASE_URL}${path}" 2>/dev/null
    fi
}

http_delete() {
    # http_delete PATH
    local path="$1"
    curl -fsS --max-time 30 -X DELETE "${BASE_URL}${path}" 2>/dev/null
}

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
deadline=$(( $(date +%s) + 60 ))
healthy=0
while [[ $(date +%s) -lt $deadline ]]; do
    body=$(http_get /health)
    if [[ -n "$body" ]] && echo "$body" | jq -e '.status == "healthy"' >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep 2
done
if [[ $healthy -eq 1 ]]; then
    ok "/health responded with status=healthy"
else
    fail "/health did not respond within 60s"
    exit 1
fi

# ---------------------------------------------------------------------------
# 5. /admin/enricher-stats
# ---------------------------------------------------------------------------
step "Checking /admin/enricher-stats"
body=$(http_get /admin/enricher-stats)
if [[ -z "$body" ]]; then
    fail "endpoint returned empty body"
    exit 1
fi
if ! echo "$body" | jq -e '.hits >= 0 and .misses >= 0 and .size >= 0 and .capacity > 0' >/dev/null 2>&1; then
    fail "response shape invalid: $body"
    exit 1
fi
hits=$(echo "$body" | jq -r '.hits')
misses=$(echo "$body" | jq -r '.misses')
size=$(echo "$body" | jq -r '.size')
capacity=$(echo "$body" | jq -r '.capacity')
ok "hits=$hits misses=$misses size=$size capacity=$capacity"

# ---------------------------------------------------------------------------
# 6. /admin/orchestrator-stats
# ---------------------------------------------------------------------------
step "Checking /admin/orchestrator-stats"
body=$(http_get /admin/orchestrator-stats)
if [[ -z "$body" ]]; then
    fail "endpoint returned empty body"
    exit 1
fi
# Must have every WorkspaceState + total.
for state in CREATED SEARCHING PAPERS_RETRIEVED SUMMARIZING SUMMARIZED COMPARING COMPARED REPORTING REPORTED COMPLETED ERROR; do
    if ! echo "$body" | jq -e --arg s "$state" 'has($s)' >/dev/null 2>&1; then
        fail "missing state '$state' (zero-fill contract broken)"
        exit 1
    fi
done
if ! echo "$body" | jq -e '.total >= 0' >/dev/null 2>&1; then
    fail "missing 'total' field"
    exit 1
fi
total=$(echo "$body" | jq -r '.total')
created=$(echo "$body" | jq -r '.CREATED')
ok "FSM picture complete: total=$total, CREATED=$created"

# ---------------------------------------------------------------------------
# 7. Functional smoke: create a workspace + fetch Nature DOI
# ---------------------------------------------------------------------------
step "Creating a workspace"
ws_body=$(http_post /workspaces '{"question": "verify.sh smoke test"}')
if [[ -z "$ws_body" ]]; then
    fail "POST /workspaces returned empty body"
    exit 1
fi
ws_id=$(echo "$ws_body" | jq -r '.workspace_id // .id // empty')
if [[ -z "$ws_id" ]]; then
    fail "could not extract workspace_id from response: $ws_body"
    exit 1
fi
ok "workspace created: $ws_id"

step "Fetching ${TEST_DOI}"
fetch_body=$(http_post "/workspaces/$ws_id/papers/fetch?identifier=${TEST_DOI}" "")
if [[ -z "$fetch_body" ]]; then
    fail "fetch returned empty body"
    exit 1
fi
abstract_len=$(echo "$fetch_body" | jq -r '.papers[0].abstract | length' 2>/dev/null)
if [[ -z "$abstract_len" || "$abstract_len" == "null" ]]; then
    fail "could not extract abstract length from: $fetch_body"
    exit 1
fi
# Allow a generous lower bound -- the abstract is at
# least 600 chars from a healthy Nature DOI fetch. We
# don't check exact length because minor publisher
# tweaks (whitespace, etc.) could shift it.
if [[ "$abstract_len" -lt 600 ]]; then
    fail "abstract too short ($abstract_len chars); expected >= 600"
    exit 1
fi
inferred=$(echo "$fetch_body" | jq -r '.papers[0].inferred_abstract')
ok "abstract length: $abstract_len chars (inferred=$inferred)"

if [[ "$inferred" != "false" ]]; then
    fail "inferred_abstract should be 'false' for deterministic meta-tag path; got '$inferred'"
    exit 1
fi

# ---------------------------------------------------------------------------
# 8. /admin/enricher-stats reflects the fetch
# ---------------------------------------------------------------------------
step "Confirming /admin/enricher-stats reflects the fetch"
body=$(http_get /admin/enricher-stats)
misses=$(echo "$body" | jq -r '.misses')
size=$(echo "$body" | jq -r '.size')
if [[ "$size" -lt 1 ]]; then
    fail "expected cache size >= 1 after fetch; got $size"
    exit 1
fi
ok "cache state after fetch: misses=$misses size=$size"

# ---------------------------------------------------------------------------
# 9. /admin/papers/refresh/{doi:path}
# ---------------------------------------------------------------------------
step "Force-refreshing ${TEST_DOI}"
refresh_body=$(http_post "/admin/papers/refresh/${TEST_DOI}" "")
if [[ -z "$refresh_body" ]]; then
    fail "force-refresh returned empty body"
    exit 1
fi
invalidate_returned=$(echo "$refresh_body" | jq -r '.invalidate_returned')
new_len=$(echo "$refresh_body" | jq -r '.abstract_length')
if [[ "$invalidate_returned" != "true" ]]; then
    fail "invalidate_returned should be true (DOI was cached); got '$invalidate_returned'"
    exit 1
fi
if [[ "$new_len" -lt 600 ]]; then
    fail "re-fetched abstract too short ($new_len chars)"
    exit 1
fi
ok "force-refresh ok: invalidate_returned=$invalidate_returned, new_length=$new_len"

# ---------------------------------------------------------------------------
# 10. DELETE /admin/enricher-cache
# ---------------------------------------------------------------------------
step "Clearing the entire cache"
clear_body=$(http_delete /admin/enricher-cache)
if [[ -z "$clear_body" ]]; then
    fail "clear-cache returned empty body"
    exit 1
fi
cleared=$(echo "$clear_body" | jq -r '.cleared')
if [[ "$cleared" != "true" ]]; then
    fail "expected cleared=true; got '$cleared'"
    exit 1
fi
size_after=$(echo "$clear_body" | jq -r '.stats_after.size')
if [[ "$size_after" != "0" ]]; then
    fail "expected size=0 after clear; got $size_after"
    exit 1
fi
ok "cache cleared: $clear_body"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\n%s%s========== SUMMARY ==========%s\n" "$C_BOLD" "$C_GREEN" "$C_RESET"
printf "Steps run:     %d\n" "$step_count"
printf "Failures:      %d\n" "$fail_count"
if [[ $fail_count -eq 0 ]]; then
    printf "%sAll checks passed.%s\n" "$C_GREEN" "$C_RESET"
    exit 0
else
    printf "%s%d checks FAILED.%s\n" "$C_RED" "$fail_count" "$C_RESET"
    exit 1
fi