"""
test_fsm_behaviour_snapshot.py

Enforces the FSM's observable behaviour against a committed baseline.

The LangGraph migration had to preserve the workspace FSM's behaviour
exactly. ``scripts/fsm_behaviour_snapshot.py`` records that behaviour
as a deterministic JSON report; this test regenerates the report and
compares it with the committed baseline.

If this test fails, the FSM's observable behaviour changed. That may
be legitimate — in which case regenerate the baseline deliberately and
review the diff:

    PYTHONPATH=. .venv/bin/python \\
        scripts/fsm_behaviour_snapshot.py --out runtime/fsm-baseline.json

Never regenerate it just to make the test green: the diff is the
review artefact.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "runtime" / "fsm-baseline.json"
SNAPSHOT_SCRIPT = REPO_ROOT / "scripts" / "fsm_behaviour_snapshot.py"


def _env() -> dict[str, str]:
    """Environment for the snapshot subprocess.

    The script needs the repo on ``PYTHONPATH``; everything else is
    inherited so the subprocess sees the same interpreter setup the
    test run does.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env


def _run_snapshot() -> dict:
    """Run the snapshot script and return the parsed report."""
    result = subprocess.run(
        [
            sys.executable,
            str(SNAPSHOT_SCRIPT),
            "--out",
            str(BASELINE.with_suffix(".regen.json")),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert result.returncode == 0, (
        f"snapshot script failed:\n{result.stdout}\n{result.stderr}"
    )
    try:
        return json.loads(BASELINE.with_suffix(".regen.json").read_text())
    finally:
        BASELINE.with_suffix(".regen.json").unlink(missing_ok=True)


@pytest.mark.skipif(
    not BASELINE.exists(),
    reason="no committed behaviour baseline (runtime/fsm-baseline.json)",
)
def test_fsm_behaviour_matches_the_committed_baseline() -> None:
    """The FSM behaves exactly as the recorded baseline says it does."""
    baseline = json.loads(BASELINE.read_text())
    current = _run_snapshot()

    assert current == baseline, (
        "the workspace FSM's observable behaviour changed.\n"
        "If the change is intended, regenerate the baseline and review "
        "the diff:\n"
        "  PYTHONPATH=. .venv/bin/python "
        "scripts/fsm_behaviour_snapshot.py --out runtime/fsm-baseline.json"
    )


def test_snapshot_is_deterministic() -> None:
    """Two consecutive runs produce byte-identical reports.

    A non-deterministic snapshot would make the baseline comparison
    above flaky, so this is checked separately.
    """
    first = subprocess.run(
        [sys.executable, str(SNAPSHOT_SCRIPT), "--out", "/tmp/_fsm_a.json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=_env(),
    )
    second = subprocess.run(
        [sys.executable, str(SNAPSHOT_SCRIPT), "--out", "/tmp/_fsm_b.json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    try:
        assert Path("/tmp/_fsm_a.json").read_bytes() == (
            Path("/tmp/_fsm_b.json").read_bytes()
        )
    finally:
        Path("/tmp/_fsm_a.json").unlink(missing_ok=True)
        Path("/tmp/_fsm_b.json").unlink(missing_ok=True)
