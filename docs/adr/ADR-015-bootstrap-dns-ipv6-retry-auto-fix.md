# ADR-015: Bootstrap DNS + IPv6 retry with auto-fix

## Status

Accepted

## Context

`bootstrap.py` is a single Python script that
one-shot installs Docker, builds the minimal image
(`bioresearch-ai:minimal`), and brings up the
container via `docker compose`. It is the documented
"foolproof install" path — users run
`python3 bootstrap.py` and expect a working system.

Live-verify in 2026-08-29/30 surfaced two distinct
network failures that bricked the install:

1. **DNS transient failure** —
   `lookup registry-1.docker.io on 127.0.0.53:53:
   server misbehaving` from the systemd-resolved stub
   resolver. Transient — a single retry usually
   succeeds. The user is on a corporate LAN where
   `192.168.1.1` is the upstream router, and the stub
   resolver returns `SERVFAIL` for a few seconds at a
   time.

2. **IPv6 unreachable** —
   `dial tcp [2606:4700:4403::ac40:904e]:443:
   connect: network is unreachable`. The host's IPv4
   works fine (HTTP 401 to `registry-1.docker.io/v2/`),
   but the IPv6 route is broken. Docker's Go resolver
   prefers IPv6 per RFC 6724 and tries the IPv6
   address first; the SYN is dropped; the build fails
   with a TCP-level error.

The user explicitly asked: *"I don't want having to
write to you every time."* — so the install must
recover automatically from both failure modes.

## Decision

A **four-layer defense** in `bootstrap.py`:

### Layer 1: Expanded pattern set

`_NETWORK_FAILURE_PATTERNS` covers both DNS-shaped
and TCP-shaped failures:

```
lookup <host> on 127.0.0.53:53: server misbehaving
lookup <host> on 127.0.0.1:53: server misbehaving
no such host
i/o timeout
temporary failure in name resolution
network is unreachable
connection refused
couldn.?t connect to server        # curl generic, IGNORECASE
connect: connection timed out
```

`_looks_like_dns_failure` is renamed to
`_looks_like_network_failure` (with a backward-compat
alias) — the patterns cover both DNS resolution
failures and TCP connect failures.

### Layer 2: TCP pre-flight probe

`_probe_docker_registry_connectivity(host,
port, per_attempt_timeout)` actually opens a TCP
socket to `registry-1.docker.io:443` for each address
family. Returns:

```python
{
    "action": "ok" | "ipv4_only" | "ipv6_only" | "unreachable",
    "ipv4_ok": bool,
    "ipv6_ok": bool,
    "ipv4_error": str | None,
    "ipv6_error": str | None,
    "attempted": list[tuple[str, int, str | None]],
}
```

The probe runs **before** the build. If the probe
reports `ipv4_only`, a clear WARN is logged with three
workarounds before the build even starts:

> Docker Hub is reachable over IPv4 but NOT over IPv6
> from this host. Docker's resolver prefers IPv6 by
> default (RFC 6724), so the build will fail...
> Workarounds: (1) disable IPv6 in the Docker daemon...
> (2) fix the host's IPv6 routing; (3) prepend an
> `--add-host registry-1.docker.io:<ipv4>` to the
> build command.

### Layer 3: Auto-fix daemon IPv6

`_disable_docker_ipv6()` writes
`{"ipv6": false}` to `/etc/docker/daemon.json`
(preserving any existing keys like `runtimes.nvidia`),
backs up the original to `daemon.json.bak`, and
restarts the docker daemon via `sudo -n systemctl
restart docker` (non-interactive).

The auto-fix is **opt-in** via
`BIORESEARCH_AUTO_FIX_DOCKER_IPV6=1` because:

- It modifies system-level config (the daemon.json)
  and requires root.
- It restarts a system service (dockerd), which can
  affect running containers.

If the user has NOPASSWD configured for the two
commands, the auto-fix succeeds and the build
retries immediately (no sleep). If NOPASSWD is not
configured, the fix falls back to logging the exact
commands to run manually.

### Layer 4: Subprocess hardening

The auto-fix's `subprocess.run` calls wrap their
input in a `try/except (OSError, subprocess.TimeoutExpired,
ValueError)`. The `ValueError` catches the
Python-3.12-specific quirk where `sudo -n` closes
stdin before `subprocess.communicate` flushes — a
real CI failure that the previous code path triggered.

### Retry loop

The retry loop runs:

1. Pre-flight DNS (`_resolve_with_retry`) — catches
   DNS-only failures.
2. Pre-flight TCP probe (`_probe_docker_registry_connectivity`)
   — catches TCP-only failures and emits the
   workarounds warning.
3. The build.
4. On build failure:
   - If `_looks_like_network_failure(captured_output)`:
     - If the probe said `ipv4_only` and the auto-fix
       has not been attempted AND the env var is set:
       invoke `_disable_docker_ipv6()`, then retry
       immediately (no sleep).
     - Otherwise: sleep with exponential backoff
       (1s, 2s, 4s) and retry up to 3 total attempts.
   - If the failure is not network-shaped: raise
     immediately (no masking of real build errors).

### Test coverage

`tests/unit/test_bootstrap_dns_retry.py` — 31 tests:

- `TestResolveWithRetry` (4): happy path, persistent
  failure, mixed attempts, raises on persistent
  failure
- `TestLooksLikeDnsFailure` (7): systemd-resolved
  misbehaving, no-such-host, IPv6 unreachable, no
  route to host, generic connection refused, curl
  `Couldn't connect`, non-failure doesn't match
- `TestRunBuildWithDnsRetry` (3): DNS failure
  triggers retry then succeeds; non-DNS failure
  doesn't retry; pre-flight DNS failure raises
- `TestProbeDockerRegistryConnectivity` (5): both
  families OK → `ok`; IPv4 only → `ipv4_only`;
  IPv6 only → `ipv6_only`; both unreachable →
  `unreachable`; connection timeout
- `TestDisableDockerIpv6` (5): happy path; already
  disabled short-circuits; write failure returns
  False; restart failure keeps config; preserves
  existing keys (e.g. `runtimes.nvidia`)
- `TestNetworkFailureTriggersAutoFix` (2): build
  fail → auto-fix → retry success; non-network
  failure skips auto-fix

## Consequences

### Positive

- The install recovers automatically from both DNS
  and TCP-level network failures without user
  intervention (when NOPASSWD is configured).
- When the auto-fix can't run (no NOPASSWD), the
  install surfaces a clear, actionable log message
  instead of a cryptic failure.
- The TCP probe catches the IPv6 routing problem
  BEFORE the build runs — saving 30+ seconds of
  wasted build time on broken-IPv6 hosts.

### Negative

- The auto-fix requires root and `sudo -n` access
  to `/etc/docker/daemon.json` and `systemctl
  restart docker`. Users without NOPASSWD still see
  the manual fallback.
- The probe adds ~3 seconds (one TCP connect attempt
  per address family) to the bootstrap's pre-flight.
- Module-level regex patterns grow over time; new
  network failures require updating the pattern set
  (and adding tests).

## References

- Commit `def5291 fix(bootstrap): retry Docker build on transient DNS failures`
- Commit `1467064 fix(bootstrap): futureproof network handling -- detect AND auto-fix broken IPv6`
- Commit `d6f226b test(bootstrap): harden auto-fix + regression tests`
- `bootstrap.py` —
  `_NETWORK_FAILURE_PATTERNS`,
  `_looks_like_network_failure`,
  `_probe_docker_registry_connectivity`,
  `_disable_docker_ipv6`,
  `_run_build_with_dns_retry`
- `tests/unit/test_bootstrap_dns_retry.py`
