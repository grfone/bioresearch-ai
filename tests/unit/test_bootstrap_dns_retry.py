"""
Tests for the DNS-aware build retry helpers in
``bootstrap.py``.

Why these tests exist
---------------------
On 2026-08-30 the user reported a build failure during
``python3 bootstrap.py``:

    #2 ERROR: failed to do request: Head
    "https://registry-1.docker.io/v2/.../manifests/1.6":
    dial tcp: lookup registry-1.docker.io on
    127.0.0.53:53: server misbehaving

The error is transient: ``systemd-resolved``'s stub
resolver at ``127.0.0.53`` occasionally returns
SERVFAIL for a single query. The host's network is
fine; only the resolver blips.

The fix lives in three small helpers in ``bootstrap.py``:

- ``_resolve_with_retry`` -- pre-flight DNS check with
  exponential backoff.
- ``_looks_like_dns_failure`` -- regex-based detection of
  DNS-shaped errors in the build's stdout/stderr.

A follow-up fix on the same day added:

- ``_probe_docker_registry_connectivity`` -- TCP-level
  pre-flight that catches the ``network is unreachable``
  case (the user's host had broken IPv6 routing that
  ``getaddrinfo`` happily returned). See
  ``TestProbeDockerRegistryConnectivity``.
- ``_disable_docker_ipv6`` -- auto-fix that writes
  ``{"ipv6": false}`` to ``/etc/docker/daemon.json``
  and restarts the daemon when the probe says the host
  has broken IPv6. See ``TestDisableDockerIpv6``.
- ``TestNetworkFailureTriggersAutoFix`` -- end-to-end
  test of the build -> probe -> auto-fix -> retry chain.
- ``_run_build_with_dns_retry`` -- the wrapper that
  invokes the pre-flight, runs the build, and retries
  on detected DNS errors.

These tests pin the contract for each helper so future
refactors of ``bootstrap.py`` can't silently regress the
behaviour.
"""
from __future__ import annotations

import io
import socket
from typing import Any
from unittest import mock

import pytest

import bootstrap


def _make_proc_mock(*, returncode: int, stdout_text: str = "") -> mock.MagicMock:
    """Build a mock subprocess.Popen return value with a
    real ``io.StringIO`` for stdout (so ``readline()``
    works the way ``bootstrap.py`` expects).

    The default ``stdout_text=""`` simulates a build that
    emits no output (typical for a build that succeeded
    silently after BuildKit's progress bars).
    """
    proc = mock.MagicMock()
    proc.stdout = io.StringIO(stdout_text)
    proc.returncode = returncode
    proc.wait.return_value = returncode
    return proc


# ---------------------------------------------------------------------------
# _resolve_with_retry
# ---------------------------------------------------------------------------


class TestResolveWithRetrySuccess:
    """Happy path: ``getaddrinfo`` returns a result on
    the first attempt."""

    def test_succeeds_on_first_attempt(self) -> None:
        with mock.patch.object(
            socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("1.2.3.4", 443))]
        ) as m:
            bootstrap._resolve_with_retry("registry-1.docker.io")
        assert m.call_count == 1

    def test_succeeds_after_retries(self) -> None:
        """A transient SERVFAIL followed by a successful
        resolution returns without raising. The retry
        count is observable via the call count.
        """
        with mock.patch.object(
            socket,
            "getaddrinfo",
            side_effect=[
                socket.gaierror(-2, "Name or service not known"),
                socket.gaierror(-2, "Name or service not known"),
                [(2, 1, 6, "", ("1.2.3.4", 443))],
            ],
        ) as m:
            bootstrap._resolve_with_retry(
                "registry-1.docker.io",
                initial_delay_s=0.01,
                backoff=1.0,
            )
        # Three attempts: 2 failures + 1 success.
        assert m.call_count == 3

    def test_honours_max_attempts(self) -> None:
        """When all attempts fail, ``_resolve_with_retry``
        re-raises the last ``OSError``. The call count
        equals ``max_attempts``.
        """
        with mock.patch.object(
            socket,
            "getaddrinfo",
            side_effect=socket.gaierror(-2, "Name or service not known"),
        ) as m:
            with pytest.raises(socket.gaierror):
                bootstrap._resolve_with_retry(
                    "registry-1.docker.io",
                    max_attempts=4,
                    initial_delay_s=0.01,
                    backoff=1.0,
                )
        assert m.call_count == 4


# ---------------------------------------------------------------------------
# _looks_like_dns_failure
# ---------------------------------------------------------------------------


class TestLooksLikeDnsFailure:
    """Pin the regex detection of DNS-flavoured errors in
    the build's output. The patterns target the Go
    stdlib resolver message format that BuildKit's
    userland-DNS errors come through as.
    """

    def test_detects_systemd_resolved_misbehaving(self) -> None:
        # The exact error message the user reported on
        # 2026-08-30.
        msg = (
            "#2 ERROR: failed to do request: Head "
            "\"https://registry-1.docker.io/v2/.../manifests/1.6\": "
            "dial tcp: lookup registry-1.docker.io on 127.0.0.53:53: "
            "server misbehaving"
        )
        assert bootstrap._looks_like_dns_failure(msg) is True

    def test_detects_loopback_resolver_misbehaving(self) -> None:
        """Some hosts use a different loopback stub
        resolver (``127.0.0.1:53`` instead of
        ``127.0.0.53:53``). The detector should catch
        that variant too.
        """
        msg = (
            "dial tcp: lookup registry-1.docker.io on "
            "127.0.0.1:53: server misbehaving"
        )
        assert bootstrap._looks_like_dns_failure(msg) is True

    def test_detects_no_such_host(self) -> None:
        msg = "dial tcp: lookup nonexistent.example: no such host"
        assert bootstrap._looks_like_dns_failure(msg) is True

    def test_detects_i_o_timeout(self) -> None:
        msg = (
            "failed to do request: ... i/o timeout"
        )
        assert bootstrap._looks_like_dns_failure(msg) is True

    def test_detects_temporary_failure_in_name_resolution(self) -> None:
        # glibc resolver error string.
        msg = (
            "Resolving \"registry-1.docker.io\": "
            "temporary failure in name resolution"
        )
        assert bootstrap._looks_like_dns_failure(msg) is True

    def test_ignores_unrelated_build_error(self) -> None:
        """A non-DNS build failure (e.g. compile error)
        must NOT match. The fix is targeted -- we don't
        want a generic "retry on any failure" wrapper.
        """
        msg = (
            "ERROR: failed to solve: process \"/bin/sh -c "
            "pip install -r requirements.txt\" did not complete "
            "successfully: exit code: 1"
        )
        assert bootstrap._looks_like_dns_failure(msg) is False

    def test_ignores_successful_build_output(self) -> None:
        """Sanity check: a normal successful build line
        doesn't match.
        """
        msg = (
            "#24 DONE 0.0s\n"
            "#24 exporting layers\n"
            "#24 writing image sha256:abc123\n"
            "#24 naming to docker.io/library/bioresearch-ai:minimal\n"
        )
        assert bootstrap._looks_like_dns_failure(msg) is False

    def test_detects_ipv6_network_unreachable(self) -> None:
        """The exact error the user reported on
        2026-08-30: ``network is unreachable`` from
        Cloudflare's IPv6 block."""
        msg = (
            "#2 ERROR: failed to authorize: failed to fetch "
            "anonymous token: Get "
            "\"https://auth.docker.io/token?...\": "
            "dial tcp [2606:4700:4403::ac40:904e]:443: "
            "connect: network is unreachable"
        )
        assert bootstrap._looks_like_network_failure(msg) is True

    def test_detects_no_route_to_host(self) -> None:
        """``no route to host`` is a transient network
        failure (often a route flap). Worth retrying."""
        msg = (
            "#2 ERROR: failed to do request: Head "
            "\"https://registry-1.docker.io/v2/.../manifests/1.6\": "
            "dial tcp 1.2.3.4:443: connect: no route to host"
        )
        assert bootstrap._looks_like_network_failure(msg) is True

    def test_detects_connection_refused_anywhere(self) -> None:
        """Generic ``connection refused`` is worth
        retrying (a service that was down may come
        back). The previous fix only matched
        ``connection refused.*docker\.io`` which was
        too narrow -- a refusal on, say,
        ``auth.docker.io`` would slip through."""
        msg = "dial tcp 1.2.3.4:443: connect: connection refused"
        assert bootstrap._looks_like_network_failure(msg) is True

    def test_detects_curl_couldnt_connect(self) -> None:
        """``curl`` (used by the bootstrap for
        credential probes) emits ``couldn't connect
        to server`` for transport-level failures
        including ENETUNREACH, EHOSTUNREACH, and
        ECONNREFUSED. We should treat this as a
        network-failure-shaped error."""
        msg = "curl: (7) Couldn't connect to server"
        assert bootstrap._looks_like_network_failure(msg) is True


# ---------------------------------------------------------------------------
# _run_build_with_dns_retry
# ---------------------------------------------------------------------------


class TestRunBuildWithDnsRetry:
    """Pin the wrapper that ties pre-flight DNS check,
    build invocation, and post-build DNS detection
    together.
    """

    def test_successful_build_does_not_retry(self) -> None:
        """When the build exits 0 the first time, no
        retry. The build is invoked exactly once.
        """
        with mock.patch.object(
            bootstrap, "_resolve_with_retry"
        ) as resolve, mock.patch.object(
            bootstrap.subprocess, "Popen",
            return_value=_make_proc_mock(returncode=0),
        ) as popen:
            bootstrap._run_build_with_dns_retry(
                ["docker", "buildx", "build", "."],
                max_attempts=3,
            )
        resolve.assert_called_once_with("registry-1.docker.io")
        # Popen called exactly once (no retry).
        assert popen.call_count == 1

    def test_dns_failure_triggers_retry_then_success(self) -> None:
        """If the first build fails with a DNS error and
        the second succeeds, we return after two
        invocations.
        """
        call_count = {"n": 0}

        def fake_popen(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First attempt: DNS error.
                return _make_proc_mock(
                    returncode=1,
                    stdout_text=(
                        "dial tcp: lookup registry-1.docker.io "
                        "on 127.0.0.53:53: server misbehaving\n"
                    ),
                )
            # Second attempt: success.
            return _make_proc_mock(returncode=0)

        with mock.patch.object(
            bootstrap, "_resolve_with_retry"
        ), mock.patch.object(
            bootstrap.subprocess, "Popen", side_effect=fake_popen
        ), mock.patch.object(
            bootstrap.time, "sleep"
        ):
            bootstrap._run_build_with_dns_retry(
                ["docker", "buildx", "build", "."],
                max_attempts=3,
            )
        assert call_count["n"] == 2

    def test_exhausts_retries_on_persistent_dns_failure(self) -> None:
        """Three DNS failures in a row raise ``RuntimeError``
        after the last attempt -- the user has a real DNS
        problem.
        """
        call_count = {"n": 0}

        def fake_popen(*args, **kwargs):
            call_count["n"] += 1
            return _make_proc_mock(
                returncode=1,
                stdout_text=(
                    "dial tcp: lookup registry-1.docker.io on "
                    "127.0.0.53:53: server misbehaving\n"
                ),
            )

        with mock.patch.object(
            bootstrap, "_resolve_with_retry"
        ), mock.patch.object(
            bootstrap.subprocess, "Popen", side_effect=fake_popen
        ), mock.patch.object(
            bootstrap.time, "sleep"
        ):
            with pytest.raises(RuntimeError, match="Docker build failed"):
                bootstrap._run_build_with_dns_retry(
                    ["docker", "buildx", "build", "."],
                    max_attempts=3,
                )
        assert call_count["n"] == 3

    def test_non_dns_failure_does_not_retry(self) -> None:
        """A build that fails for non-DNS reasons
        (compile error, missing file, port conflict) is
        raised immediately. The fix is targeted, not a
        general "retry on any failure" wrapper.
        """
        call_count = {"n": 0}

        def fake_popen(*args, **kwargs):
            call_count["n"] += 1
            return _make_proc_mock(
                returncode=1,
                stdout_text=(
                    "ERROR: failed to solve: process \"/bin/sh\" "
                    "exited with code 1\n"
                ),
            )

        with mock.patch.object(
            bootstrap, "_resolve_with_retry"
        ), mock.patch.object(
            bootstrap.subprocess, "Popen", side_effect=fake_popen
        ):
            with pytest.raises(RuntimeError, match="Docker build failed"):
                bootstrap._run_build_with_dns_retry(
                    ["docker", "buildx", "build", "."],
                    max_attempts=3,
                )
        # Exactly one attempt -- no retry on non-DNS errors.
        assert call_count["n"] == 1

    def test_preflight_failure_raises_before_invoking_build(self) -> None:
        """If the pre-flight DNS check fails, we surface
        a clear DNS-specific error message -- not a
        generic "Docker build failed". The build is
        never invoked.
        """
        with mock.patch.object(
            bootstrap,
            "_resolve_with_retry",
            side_effect=socket.gaierror(-2, "Name or service not known"),
        ), mock.patch.object(
            bootstrap.subprocess, "Popen"
        ) as popen:
            with pytest.raises(RuntimeError, match="DNS pre-flight"):
                bootstrap._run_build_with_dns_retry(
                    ["docker", "buildx", "build", "."],
                    max_attempts=3,
                )
        # Build was never invoked.
        assert popen.call_count == 0


# ---------------------------------------------------------------------------
# _probe_docker_registry_connectivity  (NEW -- added 2026-08-30)
# ---------------------------------------------------------------------------


class TestProbeDockerRegistryConnectivity:
    """
    Pin the TCP-connectivity probe that catches the
    ``network is unreachable`` failure mode the user
    hit on 2026-08-30. The previous fix only checked
    DNS; this one actually opens a TCP socket to the
    resolved addresses so we can distinguish
    IPv4-reachable / IPv6-unreachable from
    unreachable / unreachable.
    """

    def _patch_getaddrinfo(self, infos):
        """Replace ``socket.getaddrinfo`` with a static
        return so we can drive both code paths
        deterministically."""
        return mock.patch.object(
            socket, "getaddrinfo", return_value=infos
        )

    def test_both_families_reachable_reports_ok(self) -> None:
        """When IPv4 and IPv6 both connect, the probe
        returns ``recommended_action == 'ok'`` and both
        family flags are True."""
        infos = [
            (2, 1, 6, "", ("1.2.3.4", 443)),     # AF_INET
            (10, 1, 6, "", ("fe80::1", 443, 0, 0)),  # AF_INET6
        ]
        fake_sock = mock.MagicMock()
        with self._patch_getaddrinfo(infos), mock.patch.object(
            socket, "socket", return_value=fake_sock
        ) as fake_socket:
            result = bootstrap._probe_docker_registry_connectivity(
                "registry-1.docker.io", timeout_s=1.0
            )
        assert result["recommended_action"] == "ok"
        assert result["reachable_families"]["ipv4"] is True
        assert result["reachable_families"]["ipv6"] is True
        assert result["ipv4_addr"] == "1.2.3.4"
        assert result["ipv6_addr"] == "fe80::1"

    def test_ipv4_only_signals_ipv4_only_action(self) -> None:
        """The user-reported failure mode: IPv4 connects,
        IPv6 raises ENETUNREACH (``network is
        unreachable``). The probe must surface this as
        ``recommended_action == 'ipv4_only'`` so the
        caller can auto-disable IPv6 in the docker
        daemon."""
        infos = [
            (2, 1, 6, "", ("1.2.3.4", 443)),     # AF_INET
            (10, 1, 6, "", ("fe80::1", 443, 0, 0)),  # AF_INET6
        ]
        fake_sock = mock.MagicMock()

        def fake_connect(sockaddr):
            if sockaddr[0] == "1.2.3.4":
                return  # IPv4 OK
            raise OSError(101, "Network is unreachable")

        fake_sock.connect.side_effect = fake_connect
        with self._patch_getaddrinfo(infos), mock.patch.object(
            socket, "socket", return_value=fake_sock
        ):
            result = bootstrap._probe_docker_registry_connectivity(
                "registry-1.docker.io", timeout_s=1.0
            )
        assert result["recommended_action"] == "ipv4_only"
        assert result["reachable_families"]["ipv4"] is True
        assert result["reachable_families"]["ipv6"] is False
        # The IPv6 failure reason is captured for
        # debugging.
        assert "Network is unreachable" in (
            result["unreachable_reasons"]["ipv6"]
        )

    def test_neither_family_reachable_reports_unreachable(self) -> None:
        """Full network outage -- both IPv4 and IPv6
        fail. The probe returns ``recommended_action ==
        'unreachable'`` so the caller can surface a
        clear 'check your network' message."""
        infos = [
            (2, 1, 6, "", ("1.2.3.4", 443)),
            (10, 1, 6, "", ("fe80::1", 443, 0, 0)),
        ]
        fake_sock = mock.MagicMock()
        fake_sock.connect.side_effect = OSError(
            101, "Network is unreachable"
        )
        with self._patch_getaddrinfo(infos), mock.patch.object(
            socket, "socket", return_value=fake_sock
        ):
            result = bootstrap._probe_docker_registry_connectivity(
                "registry-1.docker.io", timeout_s=1.0
            )
        assert result["recommended_action"] == "unreachable"
        assert result["reachable_families"]["ipv4"] is False
        assert result["reachable_families"]["ipv6"] is False

    def test_dns_failure_short_circuits(self) -> None:
        """When ``getaddrinfo`` itself raises (no
        records at all), the probe returns
        ``recommended_action == 'dns_failure'`` and
        records the error. The caller (the bootstrap)
        handles DNS failures via ``_resolve_with_retry``;
        the probe just surfaces the state."""
        with mock.patch.object(
            socket, "getaddrinfo",
            side_effect=OSError(-2, "Name or service not known"),
        ):
            result = bootstrap._probe_docker_registry_connectivity(
                "registry-1.docker.io", timeout_s=1.0
            )
        assert result["recommended_action"] == "dns_failure"
        assert "Name or service not known" in (
            result["unreachable_reasons"]["dns"]
        )

    def test_only_ipv4_returned(self) -> None:
        """Some hosts have IPv4-only DNS records. The
        probe must not crash on missing families --
        it returns ``ipv4_only`` (since the loop only
        sees AF_INET results) rather than reporting
        ``ok`` (which would be misleading)."""
        infos = [(2, 1, 6, "", ("1.2.3.4", 443))]  # only AF_INET
        fake_sock = mock.MagicMock()
        with self._patch_getaddrinfo(infos), mock.patch.object(
            socket, "socket", return_value=fake_sock
        ):
            result = bootstrap._probe_docker_registry_connectivity(
                "registry-1.docker.io", timeout_s=1.0
            )
        # Only IPv4 was returned by getaddrinfo. The
        # probe correctly classifies this as ``ipv4_only``
        # -- Docker's resolver will still prefer IPv4
        # (because there IS no IPv6 to prefer), so the
        # build will succeed. But the action is still
        # ``ipv4_only`` because the user might want the
        # warning about partial reachability.
        assert result["recommended_action"] == "ipv4_only"
        assert result["reachable_families"]["ipv4"] is True
        assert result["reachable_families"]["ipv6"] is False


# ---------------------------------------------------------------------------
# _disable_docker_ipv6  (NEW -- added 2026-08-30)
# ---------------------------------------------------------------------------


class TestDisableDockerIpv6:
    """
    Pin the auto-fix that writes ``{"ipv6": false}`` to
    ``/etc/docker/daemon.json`` and restarts the daemon.

    The tests stub the file I/O and subprocess calls so
    we can verify the behaviour without actually
    touching the host's docker config. The function
    hardcodes the path ``/etc/docker/daemon.json`` --
    we mock the ``Path`` constructor so the test
    environment's tmp_path is used instead.
    """

    def _patched_path_factory(self, tmp_path):
        """Return a function that mimics ``Path()`` but
        routes ``/etc/docker/...`` to ``tmp_path``.

        The bootstrap calls ``Path("/etc/docker/daemon.json")``
        and ``Path("/etc/docker/daemon.json.bak")``. We
        want to redirect both to ``tmp_path`` so the
        test doesn't touch the real daemon config.
        """
        real_path = __import__("pathlib").Path

        def fake_path(p, *args, **kwargs):
            if str(p) == "/etc/docker/daemon.json":
                return tmp_path / "daemon.json"
            if str(p) == "/etc/docker/daemon.json.bak":
                return tmp_path / "daemon.json.bak"
            return real_path(p, *args, **kwargs)

        return mock.patch.object(bootstrap, "Path", fake_path)

    def test_no_docker_dir_returns_false(self, tmp_path) -> None:
        """If ``/etc/docker`` doesn't exist (e.g. a
        non-systemd host), the auto-fix can't apply
        and the function returns False without
        raising."""
        # Don't create ``tmp_path / etc / docker`` --
        # just point ``Path('/etc/docker/...')`` at a
        # non-existent parent.
        self._patched_path_factory(tmp_path / "no_etc_docker")
        with mock.patch.object(bootstrap, "Path", lambda p, *a, **kw: tmp_path / "no_etc_docker" / "daemon.json" if str(p) == "/etc/docker/daemon.json" else __import__("pathlib").Path(p, *a, **kw)):
            with mock.patch.object(bootstrap.os, "geteuid", return_value=0):
                result = bootstrap._disable_docker_ipv6()
        assert result is False

    def test_already_disabled_short_circuits(self, tmp_path) -> None:
        """If the daemon.json already has ``ipv6: false``,
        the function returns True without writing the
        file or restarting docker (no-op fast path)."""
        daemon = tmp_path / "daemon.json"
        daemon.write_text(
            '{"ipv6": false, "runtimes": {}}'
        )
        with self._patched_path_factory(tmp_path):
            # Watch the subprocess module to confirm
            # we don't try to restart the daemon.
            with mock.patch.object(
                bootstrap, "subprocess"
            ) as fake_sub:
                with mock.patch.object(bootstrap.os, "geteuid", return_value=0):
                    result = bootstrap._disable_docker_ipv6()
        assert result is True
        # No subprocess calls (no ``tee`` write, no
        # ``systemctl restart``).
        assert fake_sub.run.call_count == 0
        # File content unchanged.
        assert (
            daemon.read_text()
            == '{"ipv6": false, "runtimes": {}}'
        )

    def test_happy_path_writes_and_restarts(self, tmp_path) -> None:
        """End-to-end: existing daemon.json with runtimes
        key is preserved, ``ipv6: false`` is added, the
        file is written (preserving other keys), and
        ``systemctl restart docker`` is invoked."""
        daemon = tmp_path / "daemon.json"
        daemon.write_text(
            '{"runtimes": {"nvidia": {"path": "x"}}}\n'
        )

        def fake_path(p, *a, **kw):
            if str(p) == "/etc/docker/daemon.json":
                return daemon
            if str(p) == "/etc/docker/daemon.json.bak":
                return tmp_path / "daemon.json.bak"
            return __import__("pathlib").Path(p, *a, **kw)

        def fake_run(cmd, *args, **kwargs):
            # ``tee`` writes its stdin to the file. We
            # simulate that by reading ``input`` and
            # writing to the target path. ``systemctl
            # restart`` and ``docker info`` are
            # no-ops for our purposes.
            if "tee" in cmd:
                content = kwargs.get("input", "")
                target = cmd[cmd.index("tee") + 1]
                __import__("pathlib").Path(target).write_text(content)
                return mock.MagicMock(returncode=0, stderr="")
            return mock.MagicMock(returncode=0, stderr="", stdout="false")

        with mock.patch.object(bootstrap, "Path", fake_path):
            with mock.patch.object(bootstrap.os, "geteuid", return_value=0):
                with mock.patch.object(
                    bootstrap, "subprocess"
                ) as fake_sub:
                    fake_sub.run.side_effect = fake_run
                    result = bootstrap._disable_docker_ipv6()
        assert result is True
        # File written with ipv6=false and existing
        # keys preserved.
        import json
        cfg = json.loads(daemon.read_text())
        assert cfg["ipv6"] is False
        assert "runtimes" in cfg
        # Backup created.
        assert (tmp_path / "daemon.json.bak").exists()

    def test_write_failure_returns_false(self, tmp_path) -> None:
        """If the ``tee`` write fails (e.g. permission
        denied, disk full), the function returns False
        and does NOT attempt to restart the daemon."""
        daemon = tmp_path / "daemon.json"
        daemon.write_text("{}")

        def fake_path(p, *a, **kw):
            if str(p) == "/etc/docker/daemon.json":
                return daemon
            if str(p) == "/etc/docker/daemon.json.bak":
                return tmp_path / "daemon.json.bak"
            return __import__("pathlib").Path(p, *a, **kw)

        with mock.patch.object(bootstrap, "Path", fake_path):
            with mock.patch.object(bootstrap.os, "geteuid", return_value=0):
                with mock.patch.object(
                    bootstrap, "subprocess"
                ) as fake_sub:
                    fake_sub.run.return_value = mock.MagicMock(
                        returncode=1,
                        stderr="Permission denied",
                    )
                    result = bootstrap._disable_docker_ipv6()
        assert result is False
        # No restart attempted (only the tee was called).
        assert fake_sub.run.call_count == 1
        # Original daemon.json unchanged.
        import json
        cfg = json.loads(daemon.read_text())
        assert "ipv6" not in cfg

    def test_restart_failure_keeps_config_written(self, tmp_path) -> None:
        """If the file writes but ``systemctl restart
        docker`` fails, the function returns False but
        the config has been written. The next run of the
        bootstrap will pick it up -- a manual
        ``sudo systemctl restart docker`` is enough to
        recover."""
        daemon = tmp_path / "daemon.json"
        daemon.write_text("{}")

        def fake_path(p, *a, **kw):
            if str(p) == "/etc/docker/daemon.json":
                return daemon
            if str(p) == "/etc/docker/daemon.json.bak":
                return tmp_path / "daemon.json.bak"
            return __import__("pathlib").Path(p, *a, **kw)

        def fake_run(cmd, *args, **kwargs):
            if "tee" in cmd:
                content = kwargs.get("input", "")
                target = cmd[cmd.index("tee") + 1]
                __import__("pathlib").Path(target).write_text(content)
                return mock.MagicMock(returncode=0, stderr="")
            # systemctl restart fails
            return mock.MagicMock(
                returncode=1, stderr="Unit not found"
            )

        with mock.patch.object(bootstrap, "Path", fake_path):
            with mock.patch.object(bootstrap.os, "geteuid", return_value=0):
                with mock.patch.object(
                    bootstrap, "subprocess"
                ) as fake_sub:
                    fake_sub.run.side_effect = fake_run
                    result = bootstrap._disable_docker_ipv6()
        assert result is False
        # Config was still written -- a manual restart
        # will pick it up.
        import json
        cfg = json.loads(daemon.read_text())
        assert cfg["ipv6"] is False


# ---------------------------------------------------------------------------
# Integration: build failure -> probe -> auto-fix -> retry
# ---------------------------------------------------------------------------


class TestNetworkFailureTriggersAutoFix:
    """
    End-to-end: the bootstrap's main retry loop must
    invoke the IPv6 auto-fix when the build fails with
    a network error AND the pre-flight probe said the
    host has broken IPv6.
    """

    def test_ipv4_only_failure_triggers_auto_fix(self) -> None:
        """Simulate: probe says IPv4-only, build fails
        with a network error, the auto-fix runs, the
        build is retried without sleeping, and a
        successful build returns. The systemdctl
        restart is verified to be called exactly once
        (we don't loop on auto-fix attempts)."""
        # Stub the build to fail the first time
        # with a network error, then succeed the
        # second time (after the auto-fix).
        build_calls: dict[str, Any] = {"count": 0}
        probe_result = {
            "reachable_families": {"ipv4": True, "ipv6": False},
            "unreachable_reasons": {"ipv4": None, "ipv6": "ENETUNREACH"},
            "ipv4_addr": "1.2.3.4",
            "ipv6_addr": "fe80::1",
            "recommended_action": "ipv4_only",
        }
        with mock.patch.object(
            bootstrap, "_resolve_with_retry"
        ), mock.patch.object(
            bootstrap, "_probe_docker_registry_connectivity",
            return_value=probe_result,
        ), mock.patch.object(
            bootstrap, "_disable_docker_ipv6", return_value=True
        ) as fake_disable, mock.patch.object(
            bootstrap.time, "sleep"
        ) as fake_sleep:
            # First Popen call: fail with network
            # error. Second call: succeed.
            fail_proc = mock.MagicMock()
            fail_proc.stdout = io.StringIO(
                "#2 ERROR: failed to do request: Head\n"
                "dial tcp [2606:4700::ac40:904e]:443: "
                "connect: network is unreachable\n"
            )
            fail_proc.returncode = 1
            fail_proc.wait.return_value = 1
            ok_proc = mock.MagicMock()
            ok_proc.stdout = io.StringIO(
                "#1 transferring dockerfile: 8.01kB done\n"
                "#1 DONE 0.0s\n"
            )
            ok_proc.returncode = 0
            ok_proc.wait.return_value = 0
            build_calls["procs"] = [fail_proc, ok_proc]

            def fake_popen(*args, **kwargs):
                proc = build_calls["procs"][build_calls["count"]]
                build_calls["count"] += 1
                return proc

            with mock.patch.object(
                bootstrap.subprocess, "Popen", side_effect=fake_popen
            ):
                bootstrap._run_build_with_dns_retry(
                    ["docker", "buildx", "build", "."],
                    max_attempts=3,
                )
        # Build attempted twice (first failed, second
        # succeeded after the auto-fix).
        assert build_calls["count"] == 2
        # Auto-fix called exactly once (the no-loop
        # guard).
        assert fake_disable.call_count == 1
        # No ``time.sleep`` was called -- the auto-fix
        # path retries immediately (we just changed
        # state).
        assert fake_sleep.call_count == 0

    def test_non_network_failure_skips_auto_fix(self) -> None:
        """If the build fails for a non-network reason
        (e.g. compile error), the auto-fix path must
        NOT trigger -- the daemon state shouldn't be
        modified for unrelated failures."""
        # Stub: probe says ok, build fails with a
        # generic error.
        probe_result = {
            "reachable_families": {"ipv4": True, "ipv6": True},
            "unreachable_reasons": {"ipv4": None, "ipv6": None},
            "ipv4_addr": "1.2.3.4",
            "ipv6_addr": "fe80::1",
            "recommended_action": "ok",
        }
        with mock.patch.object(
            bootstrap, "_resolve_with_retry"
        ), mock.patch.object(
            bootstrap, "_probe_docker_registry_connectivity",
            return_value=probe_result,
        ), mock.patch.object(
            bootstrap, "_disable_docker_ipv6"
        ) as fake_disable, mock.patch.object(
            bootstrap.time, "sleep"
        ):
            fail_proc = mock.MagicMock()
            fail_proc.stdout = io.StringIO(
                "ERROR: failed to solve: process \"/bin/sh\" "
                "exited with code 1\n"
            )
            fail_proc.returncode = 1
            fail_proc.wait.return_value = 1
            with mock.patch.object(
                bootstrap.subprocess, "Popen", return_value=fail_proc
            ):
                with pytest.raises(RuntimeError, match="Docker build failed"):
                    bootstrap._run_build_with_dns_retry(
                        ["docker", "buildx", "build", "."],
                        max_attempts=3,
                    )
        # Auto-fix was NOT called (the failure wasn't
        # network-shaped).
        assert fake_disable.call_count == 0
