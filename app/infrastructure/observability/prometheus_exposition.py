"""
prometheus_exposition.py

Hand-rolled Prometheus exposition format emitter for
the in-process telemetry counters.

Background
----------
We need a `/metrics` endpoint that Prometheus / Grafana /
Alertmanager can scrape. The Prometheus exposition format
is a simple text format:

    # HELP metric_name description
    # TYPE metric_name counter
    metric_name{label="value"} 42

We don't pull in the ``prometheus_client`` library because
the only metrics we currently need are a handful of
counters and gauges, all already maintained in process
memory by the existing telemetry modules
(``citation_sanitizer``, ``title_fallback``). Adding a
dependency for ~50 lines of formatting isn't worth it.

Exposition format reference
----------------------------
https://prometheus.io/docs/instrumenting/exposition_formats/

Key rules this module follows:
- One metric per line.
- ``# HELP`` and ``# TYPE`` comments precede each metric.
- Label values are escaped (backslash, double-quote,
  newline).
- Counters end with ``_total`` (Prometheus convention);
  gauges do not.
- Metric names match ``[a-zA-Z_:][a-zA-Z0-9_:]*`` --
  underscores, colons, alphanumeric.

Author
------
Guillermo Ramajo Fernández
"""
from __future__ import annotations


def _escape_label_value(value: str) -> str:
    """
    Escape a label value for the Prometheus exposition
    format.

    The format requires backslash, double-quote, and
    newline to be escaped inside label values. We also
    strip other control characters because Prometheus
    clients reject them.
    """
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 0x20:
            # Other control characters: replace with ?
            # (Prometheus tolerates this).
            out.append("?")
        else:
            out.append(ch)
    return "".join(out)


def format_counter(
    name: str,
    help_text: str,
    value: float,
    labels: dict[str, str] | None = None,
) -> str:
    """
    Format a single counter metric.

    Counters are monotonically-increasing values. By
    Prometheus convention, the name ends with ``_total``
    (e.g. ``calls_total``, ``errors_total``).

    The output is the standard 3-line block:

        # HELP <name> <help_text>
        # TYPE <name> counter
        <name>{labels} <value>
    """
    lines = [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} counter",
    ]
    if labels:
        label_str = ",".join(
            f'{k}="{_escape_label_value(v)}"'
            for k, v in labels.items()
        )
        lines.append(f"{name}{{{label_str}}} {value}")
    else:
        lines.append(f"{name} {value}")
    return "\n".join(lines)


def format_gauge(
    name: str,
    help_text: str,
    value: float,
    labels: dict[str, str] | None = None,
) -> str:
    """
    Format a single gauge metric.

    Gauges are point-in-time readings (can go up OR down).
    No ``_total`` suffix.
    """
    lines = [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} gauge",
    ]
    if labels:
        label_str = ",".join(
            f'{k}="{_escape_label_value(v)}"'
            for k, v in labels.items()
        )
        lines.append(f"{name}{{{label_str}}} {value}")
    else:
        lines.append(f"{name} {value}")
    return "\n".join(lines)


def render_metrics(blocks: list[str]) -> str:
    """
    Join a list of formatted metric blocks into the final
    Prometheus text format. Each block is the output of
    ``format_counter`` or ``format_gauge`` (a multi-line
    string with HELP/TYPE/value).

    A trailing newline is appended so Prometheus clients
    that require line-terminated output parse correctly.
    """
    # Strip leading/trailing whitespace per block to
    # avoid blank lines, then join with single newlines
    # so the final file has the right structure.
    cleaned = [b.strip() for b in blocks if b.strip()]
    return "\n".join(cleaned) + "\n"