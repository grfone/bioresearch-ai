"""
Tests for the fallback-rate telemetry + alert.

Background
----------
The synthesis LLM is asked to emit a ``# <report title>``
heading at the start of the body. When it omits one, the
fallback injects a derived title. If the LLM is
consistently omitting the H1, the user prompt may need
tightening. To help operators detect this, ``inject_h1_fallback``
maintains a rolling-window rate and emits a WARNING log
line when the rate exceeds a threshold.

The stats are also exposed via ``/health/title-fallback``
(mirroring the citation-sanitizer pattern) for
external monitoring tools.

Tests pin:
  1. ``_record_fallback_call`` updates the rolling window.
  2. ``get_fallback_stats`` returns a snapshot.
  3. ``reset_fallback_stats`` clears the buffer.
  4. Warning fires when rate exceeds threshold over a
     meaningful sample size.
  5. Warning does NOT fire when rate is below threshold.
  6. Warning does NOT fire on small samples (avoid noise).
  7. Window is capped at ``_FALLBACK_RATE_WINDOW`` entries.
"""


import logging

import pytest

from app.infrastructure.llm.title_fallback import (
    _FALLBACK_RATE_THRESHOLD,
    _FALLBACK_RATE_WINDOW,
    get_fallback_stats,
    inject_h1_fallback,
    reset_fallback_stats,
)


@pytest.fixture(autouse=True)
def _reset_stats():
    """Reset stats before AND after each test so the
    in-process rolling window doesn't leak between tests.
    The module-level ``_FALLBACK_WINDOW`` is shared
    process state, so without this fixture a test that
    runs after another (e.g. via ``pytest -x``) would
    inherit whatever the previous test left in the
    window -- false positives / negatives on the alert
    threshold check.
    """
    reset_fallback_stats()
    yield
    reset_fallback_stats()


class TestRecordFallbackCall:
    """Direct unit tests on the rolling-window update
    helper, isolated from the public API."""

    def test_first_call_records_zero_or_one(self):
        """A single call records exactly one entry."""
        from app.infrastructure.llm.title_fallback import (
            _FALLBACK_WINDOW,
            _record_fallback_call,
        )

        _record_fallback_call(injected=True)
        assert _FALLBACK_WINDOW == [1]


class TestGetFallbackStats:
    """The public stats snapshot."""

    def test_empty_window_returns_zero_stats(self):
        stats = get_fallback_stats()
        assert stats["total_calls"] == 0
        assert stats["total_fallbacks"] == 0
        assert stats["rate"] == 0.0
        assert stats["window_size"] == 0
        assert stats["current_window"] == []

    def test_stats_after_injections(self):
        for _ in range(5):
            inject_h1_fallback("Body without H1.")
        for _ in range(3):
            inject_h1_fallback("# Real Title\n\nBody")
        stats = get_fallback_stats()
        assert stats["total_calls"] == 8
        assert stats["total_fallbacks"] == 5
        assert stats["rate"] == 5 / 8
        assert stats["window_size"] == 8
        # Last 3 entries should be 0 (LLM had H1).
        assert stats["current_window"][-3:] == [0, 0, 0]

    def test_window_capped_at_max_size(self):
        """The rolling window is capped at
        ``_FALLBACK_RATE_WINDOW`` entries. Anything beyond
        drops the oldest entries.
        """
        # Push 2x the window size.
        for _ in range(_FALLBACK_RATE_WINDOW * 2):
            inject_h1_fallback("Body without H1.")
        stats = get_fallback_stats()
        # Window is capped.
        assert stats["window_size"] == _FALLBACK_RATE_WINDOW


class TestResetFallbackStats:
    """``reset_fallback_stats`` clears the rolling
    window."""

    def test_reset_clears_the_window(self):
        for _ in range(5):
            inject_h1_fallback("Body without H1.")
        # Stats are populated.
        assert get_fallback_stats()["total_calls"] == 5
        # Reset.
        reset_fallback_stats()
        assert get_fallback_stats()["total_calls"] == 0
        assert get_fallback_stats()["current_window"] == []


class TestFallbackRateAlert:
    """The WARNING log line fires when the rate exceeds
    the threshold. This is the operator-facing alert.
    """

    def test_warning_fires_when_rate_exceeds_threshold(
        self, caplog
    ):
        """A high fallback rate (LLM consistently omits
        the H1) triggers a WARNING log so operators see
        the degraded prompt in the container logs.
        """
        # All 20 calls need the fallback -- 100% rate.
        with caplog.at_level(
            logging.WARNING,
            logger="app.infrastructure.llm.title_fallback",
        ):
            for _ in range(_FALLBACK_RATE_WINDOW):
                inject_h1_fallback("Body without H1.")
            warnings = [
                r for r in caplog.records
                if r.levelno == logging.WARNING
                and "fallback rate is" in r.message
            ]
            assert len(warnings) >= 1, (
                f"expected at least one WARNING log on "
                f"high fallback rate; got {len(warnings)}"
            )

    def test_warning_silent_when_rate_is_low(self, caplog):
        """When the LLM mostly complies (low fallback
        rate), no WARNING fires.
        """
        # 20 calls, all with H1 -- 0% rate.
        with caplog.at_level(
            logging.WARNING,
            logger="app.infrastructure.llm.title_fallback",
        ):
            for _ in range(_FALLBACK_RATE_WINDOW):
                inject_h1_fallback("# Real Title\n\nBody")
            warnings = [
                r for r in caplog.records
                if r.levelno == logging.WARNING
                and "fallback rate is" in r.message
            ]
            assert len(warnings) == 0

    def test_warning_silent_on_small_samples(self, caplog):
        """Below the minimum sample size (half the
        window), the alert doesn't fire. This avoids
        noise -- a single fallback in 2 calls would
        otherwise give 50% which is just chance.
        """
        # Only 3 calls -- well below ``_FALLBACK_RATE_WINDOW // 2 = 10``.
        with caplog.at_level(
            logging.WARNING,
            logger="app.infrastructure.llm.title_fallback",
        ):
            for _ in range(3):
                inject_h1_fallback("Body without H1.")
            warnings = [
                r for r in caplog.records
                if r.levelno == logging.WARNING
                and "fallback rate is" in r.message
            ]
            assert len(warnings) == 0, (
                "small-sample high-rate should NOT alert; "
                "the noise would be misleading"
            )

    def test_warning_threshold_boundary(self, caplog):
        """Exactly at the threshold (50%), the warning
        fires (the predicate is ``rate >= threshold``).
        """
        n = _FALLBACK_RATE_WINDOW
        with caplog.at_level(
            logging.WARNING,
            logger="app.infrastructure.llm.title_fallback",
        ):
            # n/2 with H1, n/2 without -- exactly 50%.
            for _ in range(n // 2):
                inject_h1_fallback("Body without H1.")
            for _ in range(n - n // 2):
                inject_h1_fallback("# Real Title\n\nBody")
            warnings = [
                r for r in caplog.records
                if r.levelno == logging.WARNING
                and "fallback rate is" in r.message
            ]
            assert len(warnings) >= 1, (
                f"at-threshold rate ({_FALLBACK_RATE_THRESHOLD * 100}%) "
                f"should trigger the WARNING"
            )

    def test_warning_logs_recent_window_for_debugging(
        self, caplog
    ):
        """The WARNING log includes the trailing window
        so operators can see the recent pattern. This is
        diagnostic info, not load-bearing for the alert.
        """
        with caplog.at_level(
            logging.WARNING,
            logger="app.infrastructure.llm.title_fallback",
        ):
            for _ in range(_FALLBACK_RATE_WINDOW):
                inject_h1_fallback("Body without H1.")
        warnings = [
            r for r in caplog.records
            if "fallback rate is" in r.message
        ]
        assert warnings, "expected at least one warning"
        # The most recent warning's message includes the
        # trailing window as a list of 0/1 entries.
        msg = warnings[-1].message
        # Format: includes ``title=[0, 1, 0, ...]`` or similar.
        assert "title=" in msg or "[" in msg, (
            f"warning should include the recent window; "
            f"got: {msg!r}"
        )


class TestHealthEndpoint:
    """The ``/health/title-fallback`` route exposes
    ``get_fallback_stats`` for external monitoring.
    """

    def test_route_is_registered(self):
        """Verify the route is in the FastAPI router."""
        from app.api.routes.health import router

        paths = [r.path for r in router.routes]
        assert "/health/title-fallback" in paths

    def test_route_returns_fallback_stats_dict(self):
        """Calling the endpoint returns the snapshot
        dict from ``get_fallback_stats``.
        """
        from fastapi.testclient import TestClient

        from main import app

        client = TestClient(app)
        response = client.get("/health/title-fallback")
        assert response.status_code == 200
        data = response.json()
        # All keys present.
        for key in (
            "total_calls", "total_fallbacks",
            "rate", "window_size", "current_window",
        ):
            assert key in data, f"missing key: {key}"
