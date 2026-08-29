"""
Tests for the Prometheus exposition-format helpers
introduced in this commit.

Background
----------
The ``/metrics`` endpoint exposes in-process counters
in the Prometheus exposition format so external
monitoring tools (Prometheus server, Grafana Agent,
alertmanager) can scrape the BioResearch AI service
without log scraping.

The format is documented at
https://prometheus.io/docs/instrumenting/exposition_formats/.
Key invariants this module pins:

  - One metric per line.
  - Each metric is preceded by ``# HELP`` and ``# TYPE``
    comments.
  - Counter names end with ``_total``.
  - Gauge names do NOT end with ``_total``.
  - Label values are escaped (backslash, double-quote,
    newline).
  - The trailing newline is appended so clients that
    require line-terminated input parse correctly.

Tests live alongside the exposition module and reuse
its ``format_*`` / ``render_metrics`` functions.
"""
from __future__ import annotations

import pytest

from app.infrastructure.observability.prometheus_exposition import (
    _escape_label_value,
    format_counter,
    format_gauge,
    render_metrics,
)


class TestEscapeLabelValue:
    """``_escape_label_value`` escapes the three
    characters the Prometheus exposition format requires
    escaping inside label values."""

    def test_plain_value_unchanged(self):
        """No special chars: value passes through."""
        assert _escape_label_value("hello") == "hello"

    def test_backslash_escaped(self):
        """Backslash is escaped to double-backslash."""
        assert _escape_label_value("a\\b") == "a\\\\b"

    def test_double_quote_escaped(self):
        """Double-quote is escaped to backslash-quote."""
        assert _escape_label_value('a"b') == 'a\\"b'

    def test_newline_escaped(self):
        """Newline is escaped to backslash-n."""
        assert _escape_label_value("a\nb") == "a\\nb"

    def test_carriage_return_replaced_with_question_mark(self):
        """Other control characters (CR, etc.) are
        replaced with ``?`` because Prometheus clients
        reject raw control bytes."""
        assert _escape_label_value("a\rb") == "a?b"

    def test_combined_escapes(self):
        """A label value with multiple special characters
        is escaped once per character.
        """
        assert _escape_label_value('"\\x\n') == '\\"\\\\x\\n'


class TestFormatCounter:
    """``format_counter`` produces the standard 3-line
    counter block."""

    def test_counter_without_labels(self):
        out = format_counter("foo_total", "A test counter.", 42)
        # Three lines: HELP, TYPE, value.
        assert out.count("\n") == 2
        # HELP line.
        assert "# HELP foo_total A test counter." in out
        # TYPE line.
        assert "# TYPE foo_total counter" in out
        # Value line.
        assert "foo_total 42" in out

    def test_counter_with_labels(self):
        out = format_counter(
            "foo_total",
            "A test counter.",
            42,
            {"env": "prod"},
        )
        assert "# TYPE foo_total counter" in out
        # Label key + value rendered inside curly braces.
        assert 'env="prod"' in out
        # Value rendered with the labels.
        assert 'foo_total{env="prod"} 42' in out

    def test_counter_name_ends_with_total(self):
        """Per Prometheus convention, counter names
        end with ``_total``. The formatter doesn't enforce
        this -- it's the caller's responsibility -- but
        the integration test in
        ``test_metrics_endpoint_emits_counters`` verifies
        our actual metric names follow the convention.
        """
        out = format_counter("calls_total", "Calls.", 1)
        assert "calls_total" in out

    def test_counter_value_zero(self):
        """Zero is a valid counter value -- it means the
        service has has had no calls since start.
        """
        out = format_counter("calls_total", "Calls.", 0)
        assert "calls_total 0" in out


class TestFormatGauge:
    """``format_gauge`` produces the standard 3-line
    gauge block."""

    def test_gauge_without_labels(self):
        out = format_gauge("foo_gauge", "A test gauge.", 0.5)
        assert "# HELP foo_gauge A test gauge." in out
        assert "# TYPE foo_gauge gauge" in out
        assert "foo_gauge 0.5" in out

    def test_gauge_with_labels(self):
        out = format_gauge(
            "foo_gauge",
            "A test gauge.",
            0.75,
            {"shard": "0"},
        )
        assert '# TYPE foo_gauge gauge' in out
        assert 'shard="0"' in out
        assert 'foo_gauge{shard="0"} 0.75' in out

    def test_gauge_supports_floating_point(self):
        """Gauges commonly have fractional values
        (0.0-1.0 for rates)."""
        out = format_gauge("rate_gauge", "A rate.", 0.5)
        assert "rate_gauge 0.5" in out


class TestRenderMetrics:
    """``render_metrics`` joins multiple blocks into the
    final exposition body."""

    def test_render_empty_list(self):
        """An empty list produces just the trailing
        newline (a valid empty exposition body).
        """
        assert render_metrics([]) == "\n"

    def test_render_single_block(self):
        block = format_counter("foo_total", "Foo.", 1)
        out = render_metrics([block])
        # Trailing newline is appended.
        assert out.endswith("\n")
        # The block content is preserved.
        assert "# HELP foo_total Foo." in out
        assert "foo_total 1" in out

    def test_render_multiple_blocks(self):
        """Multiple blocks are joined with newlines."""
        b1 = format_counter("a_total", "A.", 1)
        b2 = format_gauge("b_gauge", "B.", 0.5)
        out = render_metrics([b1, b2])
        # Both metrics are present.
        assert "a_total 1" in out
        assert "b_gauge 0.5" in out
        # Both TYPE comments are present.
        assert "# TYPE a_total counter" in out
        assert "# TYPE b_gauge gauge" in out

    def test_render_skips_empty_blocks(self):
        """Empty or whitespace-only blocks are skipped
        so the output doesn't have phantom blank lines.
        """
        b1 = format_counter("a_total", "A.", 1)
        out = render_metrics([b1, "", "  ", b1])
        # Two ``a_total`` lines (from the two non-empty
        # blocks).
        assert out.count("a_total 1") == 2
        # No double-blank lines.
        assert "\n\n\n" not in out


class TestMetricsEndpointExposition:
    """Integration: the ``/metrics`` route returns a
    Prometheus-compatible text body containing the live
    telemetry counters."""

    def test_endpoint_returns_200(self):
        from fastapi.testclient import TestClient

        from main import app

        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_endpoint_returns_text_plain_content_type(self):
        """Prometheus clients expect
        ``text/plain; version=0.0.4``.
        """
        from fastapi.testclient import TestClient

        from main import app

        client = TestClient(app)
        response = client.get("/metrics")
        # PlainTextResponse sets ``text/plain`` (the
        # version param is in the body, not the
        # content-type header -- but Prometheus clients
        # accept any text/plain).
        assert response.headers["content-type"].startswith(
            "text/plain"
        )

    def test_endpoint_body_has_help_and_type_lines(self):
        """Every metric in the body has its HELP and TYPE
        comments.
        """
        from fastapi.testclient import TestClient

        from main import app

        client = TestClient(app)
        body = client.get("/metrics").text
        # Count HELP lines and TYPE lines -- they should
        # be equal (one per metric).
        help_count = body.count("# HELP ")
        type_count = body.count("# TYPE ")
        assert help_count == type_count
        assert help_count > 0

    def test_endpoint_emits_expected_metric_names(self):
        """The integration exposes all the telemetry
        counters + gauges from this commit. Names
        follow Prometheus conventions (counters end in
        ``_total``, gauges do not).
        """
        from fastapi.testclient import TestClient

        from main import app

        client = TestClient(app)
        body = client.get("/metrics").text
        # Counters.
        for name in (
            "citation_sanitizer_calls_total",
            "citation_sanitizer_dropped_total",
            "citation_sanitizer_calls_with_drops_total",
            "title_fallback_calls_total",
            "title_fallback_injections_total",
        ):
            assert f"# TYPE {name} counter" in body, (
                f"missing counter metric: {name}"
            )
        # Gauges.
        for name in (
            "title_fallback_rate",
            "title_fallback_window_size",
        ):
            assert f"# TYPE {name} gauge" in body, (
                f"missing gauge metric: {name}"
            )

    def test_endpoint_values_reflect_live_state(self):
        """The endpoint reads the in-process counters
        dynamically. After calling
        ``inject_h1_fallback`` 3 times (all without an
        H1), the title-fallback counter goes up.
        """
        from app.infrastructure.llm.title_fallback import (
            inject_h1_fallback,
            reset_fallback_stats,
        )
        from fastapi.testclient import TestClient

        from main import app

        reset_fallback_stats()
        # Drive the counter up.
        for _ in range(3):
            inject_h1_fallback("Body without H1.")
        client = TestClient(app)
        body = client.get("/metrics").text
        # ``title_fallback_calls_total`` should be 3.
        for line in body.split("\n"):
            if line.startswith("title_fallback_calls_total"):
                assert line.endswith(" 3"), (
                    f"expected calls_total=3, got: {line!r}"
                )
        # ``title_fallback_injections_total`` should be 3
        # (all 3 calls needed the fallback).
        for line in body.split("\n"):
            if line.startswith("title_fallback_injections_total"):
                assert line.endswith(" 3"), (
                    f"expected injections_total=3, got: {line!r}"
                )
        # ``title_fallback_rate`` should be 1.0 (all 3
        # were injections).
        for line in body.split("\n"):
            if line.startswith("title_fallback_rate "):
                assert line.endswith(" 1.0"), (
                    f"expected rate=1.0, got: {line!r}"
                )
        # Clean up.
        reset_fallback_stats()