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
