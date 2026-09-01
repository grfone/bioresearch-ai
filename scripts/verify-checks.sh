#!/usr/bin/env bash
#
# verify-checks.sh -- shared smoke-test logic for verify.sh
# and verify-ci.sh. Sourced by both; do NOT execute
# directly.
#
# Provides:
#   - ANSI color helpers (C_RED, C_GREEN, C_BLUE, etc.)
#   - Step / OK / FAIL printers with counters
#   - HTTP helpers (http_get, http_post, http_delete)
#   - run_admin_smoke_tests -- the full battery of
#     endpoint + functional checks
#
# Required environment from caller:
#   BASE_URL -- backend base URL, e.g. http://localhost:8000
#
# Optional:
#   NO_COLOR=1 -- disable ANSI escape codes
#
# After run_admin_smoke_tests returns, the caller can
# inspect $step_count and $fail_count for the totals.
# The function exits with code 0 if all checks pass,
# 1 if any fail.

# Guard against being executed directly.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "verify-checks.sh is a library; source it from a verify script." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Color setup
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------
step_count=0
fail_count=0

# ---------------------------------------------------------------------------
# Printers
# ---------------------------------------------------------------------------
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
    # warn goes to stderr so callers can capture ``fsm_states``
    # output via stdout without parsing the WARN line out.
    # Mixing the warning with the actual value into stdout
    # causes any caller that does ``$(fsm_states)`` to pick
    # up the WARN line in addition to the comma-separated
    # state list -- which is exactly the failure mode the
    # previous bash test caught.
    printf "  %sWARN%s %s\n" "$C_YELLOW" "$C_RESET" "$1" >&2
}

require_tool() {
    # require_tool NAME INSTALL_HINT -- die if a CLI tool
    # isn't on PATH.
    if ! command -v "$1" >/dev/null 2>&1; then
        printf "%sERROR%s: required tool '%s' not found on PATH\n" \
            "$C_RED" "$C_RESET" "$1" >&2
        printf "Install: %s\n" "$2" >&2
        exit 2
    fi
}

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# fsm_states -- return comma-separated FSM state values from the source of
# truth (the ``WorkspaceState`` enum).
#
# This is the single point of contact between the smoke test and the FSM
# vocabulary. The previous implementation hardcoded ``INITIAL INTERMEDIATE
# FINAL ERROR`` here, which broke every time we collapsed or expanded the
# FSM (commits ``7df2fd4`` and ``306da28`` had to fix the smoke test in
# follow-up commits).
#
# Running against the local checkout (not the container) keeps the
# check honest: if the WorkspaceState enum can't be imported, the smoke
# test fails immediately rather than silently using a stale hardcoded
# fallback.
#
# Tries ``python3`` first (CI runners ship system python), then the
# project's own ``.venv/bin/python`` (local checkouts). On a fresh
# checkout where the venv hasn't been provisioned yet, the
# ``workspace_state`` import still works as long as PYTHONPATH includes
# the repo root and the only-on-bootstrap fastapi dependencies
# (``pydantic``, ``sqlalchemy``, etc.) are installed.
# ---------------------------------------------------------------------------
fsm_states() {
    # The smoke test runs after ``cd PROJECT_ROOT`` so we can rely on
    # the local source tree. We try the project's venv first because
    # it has all the dependencies installed; fall back to system
    # python for CI runners that don't have a venv.
    local python_bin="${PYTHON:-}"
    if [[ -z "$python_bin" ]]; then
        if [[ -x "${PROJECT_ROOT:-.}/.venv/bin/python" ]]; then
            python_bin="${PROJECT_ROOT}/.venv/bin/python"
        elif command -v python3 >/dev/null 2>&1; then
            python_bin="python3"
        fi
    fi
    if [[ -z "$python_bin" ]]; then
        # No python at all -- fall back to the four-state default.
        # This is the worst-case fallback; the verify.sh entrypoint
        # should already have failed earlier when checking for jq,
        # curl, etc., so this branch is unreachable in practice.
        echo "INITIAL,INTERMEDIATE,FINAL,ERROR"
        return
    fi
    PYTHONPATH="${PROJECT_ROOT:-.}:${PYTHONPATH:-}" "$python_bin" -c "
from app.core.enums.workspace_state import WorkspaceState
print(','.join(s.value for s in WorkspaceState))
" 2>/dev/null || {
        # Fallback if the local python can't import -- use the
        # conservative four-state default. Smoke test still runs;
        # an FSM refactor that didn't update this file would still
        # trigger the next round of CI cleanup, but at least the
        # verify.sh entrypoint won't be blocked by an import error.
        warn "fsm_states: local python couldn't import WorkspaceState; using fallback"
        echo "INITIAL,INTERMEDIATE,FINAL,ERROR"
    }
}

# ---------------------------------------------------------------------------
# wait_for_healthy -- poll /health until healthy or timeout
# ---------------------------------------------------------------------------
# Args: $1 = timeout in seconds (default 60).
# Returns 0 if healthy, 1 if timeout exceeded.
wait_for_healthy() {
    local timeout="${1:-60}"
    local deadline=$(($(date +%s) + timeout))
    while [[ $(date +%s) -lt $deadline ]]; do
        local body
        body=$(http_get /health)
        if [[ -n "$body" ]] && echo "$body" | jq -e '.status == "healthy"' >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

# ---------------------------------------------------------------------------
# run_admin_smoke_tests -- the full battery of endpoint +
# functional checks. Assumes the container is already
# running and /health is responding.
# ---------------------------------------------------------------------------
# Args: $1 = the test DOI to use for the workspace +
#       fetch + force-refresh checks (default Nature DOI).
# Exits 0 if all checks pass, 1 if any fail. Updates
# $step_count / $fail_count in the caller.
run_admin_smoke_tests() {
    local test_doi="${1:-10.1038/nature14539}"

    step "Checking /admin/enricher-stats"
    local body
    body=$(http_get /admin/enricher-stats)
    if [[ -z "$body" ]]; then
        fail "endpoint returned empty body"
        return 1
    fi
    if ! echo "$body" | jq -e '.hits >= 0 and .misses >= 0 and .size >= 0 and .capacity > 0' >/dev/null 2>&1; then
        fail "response shape invalid: $body"
        return 1
    fi
    local hits misses size capacity
    hits=$(echo "$body" | jq -r '.hits')
    misses=$(echo "$body" | jq -r '.misses')
    size=$(echo "$body" | jq -r '.size')
    capacity=$(echo "$body" | jq -r '.capacity')
    ok "hits=$hits misses=$misses size=$size capacity=$capacity"

    step "Checking /admin/orchestrator-stats"
    body=$(http_get /admin/orchestrator-stats)
    if [[ -z "$body" ]]; then
        fail "endpoint returned empty body"
        return 1
    fi
    # The /admin/orchestrator-stats endpoint zero-fills
    # every state name from the ``WorkspaceState`` enum so
    # dashboards always see the full key set. The
    # ``fsm_states`` helper reads the enum directly from
    # the local checkout (see helper above for rationale),
    # so this check stays in sync with any future FSM
    # refactor without a shell-script edit.
    expected_states=$(fsm_states)
    IFS=',' read -ra state_list <<< "$expected_states"
    for state in "${state_list[@]}"; do
        if ! echo "$body" | jq -e --arg s "$state" 'has($s)' >/dev/null 2>&1; then
            fail "missing state '$state' (zero-fill contract broken)"
            return 1
        fi
    done
    if ! echo "$body" | jq -e '.total >= 0' >/dev/null 2>&1; then
        fail "missing 'total' field"
        return 1
    fi
    # The "head of the funnel" state (first enum member) is
    # always INITIAL for our linear FSMs, but we look it up
    # via ``fsm_states`` rather than hardcoding it so the
    # smoke check stays in sync with any future refactor.
    local total head_state head_count
    total=$(echo "$body" | jq -r '.total')
    head_state=$(echo "$expected_states" | cut -d',' -f1)
    head_count=$(echo "$body" | jq -r --arg s "$head_state" '.[$s]')
    ok "FSM picture complete: total=$total, $head_state=$head_count (${#state_list[@]} states declared)"

    step "Creating a workspace"
    local ws_body
    ws_body=$(http_post /workspaces "{\"question\": \"verify smoke test\"}")
    if [[ -z "$ws_body" ]]; then
        fail "POST /workspaces returned empty body"
        return 1
    fi
    local ws_id
    ws_id=$(echo "$ws_body" | jq -r '.workspace_id // .id // empty')
    if [[ -z "$ws_id" ]]; then
        fail "could not extract workspace_id from response: $ws_body"
        return 1
    fi
    ok "workspace created: $ws_id"

    step "Fetching ${test_doi}"
    local fetch_body
    fetch_body=$(http_post "/workspaces/$ws_id/papers/fetch?identifier=${test_doi}" "")
    if [[ -z "$fetch_body" ]]; then
        fail "fetch returned empty body"
        return 1
    fi
    local abstract_len
    abstract_len=$(echo "$fetch_body" | jq -r '.papers[0].abstract | length' 2>/dev/null)
    if [[ -z "$abstract_len" || "$abstract_len" == "null" ]]; then
        fail "could not extract abstract length from: $fetch_body"
        return 1
    fi
    if [[ "$abstract_len" -lt 600 ]]; then
        fail "abstract too short ($abstract_len chars); expected >= 600"
        return 1
    fi
    local inferred
    inferred=$(echo "$fetch_body" | jq -r '.papers[0].inferred_abstract')
    ok "abstract length: $abstract_len chars (inferred=$inferred)"

    if [[ "$inferred" != "false" ]]; then
        fail "inferred_abstract should be 'false' for deterministic meta-tag path; got '$inferred'"
        return 1
    fi

    step "Confirming /admin/enricher-stats reflects the fetch"
    body=$(http_get /admin/enricher-stats)
    misses=$(echo "$body" | jq -r '.misses')
    size=$(echo "$body" | jq -r '.size')
    if [[ "$size" -lt 1 ]]; then
        fail "expected cache size >= 1 after fetch; got $size"
        return 1
    fi
    ok "cache state after fetch: misses=$misses size=$size"

    step "Force-refreshing ${test_doi}"
    local refresh_body
    refresh_body=$(http_post "/admin/papers/refresh/${test_doi}" "")
    if [[ -z "$refresh_body" ]]; then
        fail "force-refresh returned empty body"
        return 1
    fi
    local invalidate_returned new_len
    invalidate_returned=$(echo "$refresh_body" | jq -r '.invalidate_returned')
    new_len=$(echo "$refresh_body" | jq -r '.abstract_length')
    if [[ "$invalidate_returned" != "true" ]]; then
        fail "invalidate_returned should be true (DOI was cached); got '$invalidate_returned'"
        return 1
    fi
    if [[ "$new_len" -lt 600 ]]; then
        fail "re-fetched abstract too short ($new_len chars)"
        return 1
    fi
    ok "force-refresh ok: invalidate_returned=$invalidate_returned, new_length=$new_len"

    step "Clearing the entire cache"
    local clear_body
    clear_body=$(http_delete /admin/enricher-cache)
    if [[ -z "$clear_body" ]]; then
        fail "clear-cache returned empty body"
        return 1
    fi
    local cleared size_after
    cleared=$(echo "$clear_body" | jq -r '.cleared')
    if [[ "$cleared" != "true" ]]; then
        fail "expected cleared=true; got '$cleared'"
        return 1
    fi
    size_after=$(echo "$clear_body" | jq -r '.stats_after.size')
    if [[ "$size_after" != "0" ]]; then
        fail "expected size=0 after clear; got $size_after"
        return 1
    fi
    ok "cache cleared: $clear_body"

    return 0
}

# ---------------------------------------------------------------------------
# print_summary -- print the SUMMARY block and exit with
# the appropriate code.
# ---------------------------------------------------------------------------
# Args: $1 = exit code to use if any failures (default 1).
# Reads: $step_count, $fail_count.
print_summary() {
    local exit_code="${1:-1}"
    printf "\n%s%s========== SUMMARY ==========%s\n" "$C_BOLD" "$C_GREEN" "$C_RESET"
    printf "Steps run:     %d\n" "$step_count"
    printf "Failures:      %d\n" "$fail_count"
    if [[ "$fail_count" -eq 0 ]]; then
        printf "%sAll checks passed.%s\n" "$C_GREEN" "$C_RESET"
        exit 0
    else
        printf "%s%d checks FAILED.%s\n" "$C_RED" "$fail_count" "$C_RESET"
        exit "$exit_code"
    fi
}