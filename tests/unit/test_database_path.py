"""
Regression tests for the SQLite database path bug.

A previous version of the bootstrap had three bugs that caused
HTTP 500 errors when running in Docker:

1. ``docker-compose.yml`` mounted ``./bioresearch.db:/app/bioresearch.db``
   as a bind mount. If the host path was missing or was a
   directory (which happened because the bootstrap previously
   created a directory at that path), the container tried to open
   the path as a SQLite file and got ``unable to open database
   file``.

2. ``SqliteWorkspaceRepository`` did not respect ``DATABASE_URL``.
   It hardcoded ``db_path="bioresearch.db"`` regardless of what
   the user had configured.

3. ``_sqlite_path_from_settings()`` had an off-by-one error:
   ``url[len("sqlite:////") - 1]`` returns the single character at
   index 10 (the leading slash) instead of the substring from
   index 10 onwards. Python's slice syntax ``[n]`` returns a
   single character; ``[n:]`` returns the substring.

These tests enforce the fixes so the bug can't regress.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_YML = REPO_ROOT / "docker-compose.yml"
CONTAINER_PY = REPO_ROOT / "app" / "config" / "container.py"


# ---------------------------------------------------------------------------
# docker-compose.yml
# ---------------------------------------------------------------------------


def test_compose_mounts_parent_directory_not_database_file() -> None:
    """The compose file must mount the parent directory of the
    database, not the file itself. Mounting the file is fragile:
    if the host path is missing or is a directory (which happens
    when something creates it before SQLite does), the container
    fails with ``unable to open database file``.

    The accepted pattern is to mount the directory and let SQLite
    create its files inside. The compose must therefore NOT
    have a ``./bioresearch.db:/app/bioresearch.db`` style mount.
    """
    text = COMPOSE_YML.read_text()
    assert "./bioresearch.db:/app/bioresearch.db" not in text, (
        "docker-compose.yml must not bind-mount the .db file "
        "directly. Bind-mount the parent directory instead."
    )


def test_compose_pins_database_url() -> None:
    """The compose file must pin ``DATABASE_URL`` so the container
    opens the database at the absolute path inside the mounted
    parent directory. Without this, ``SqliteWorkspaceRepository``
    opens a relative path and may fail when the working directory
    is wrong.
    """
    text = COMPOSE_YML.read_text()
    assert "DATABASE_URL" in text, (
        "docker-compose.yml must set DATABASE_URL so the container "
        "uses an absolute path inside the bind-mounted directory"
    )


# ---------------------------------------------------------------------------
# app/config/container.py — _sqlite_path_from_settings
# ---------------------------------------------------------------------------


def test_helper_does_not_use_off_by_one_substring_bug() -> None:
    """``_sqlite_path_from_settings()`` must NOT contain
    ``url[len(\"sqlite:////\") - 1]``.

    That expression evaluates to ``url[10]`` which returns a
    single character (the leading slash), not the substring
    starting at index 10. Python's slice syntax ``[n]`` returns
    a single character; ``[n:]`` returns the substring.
    """
    text = CONTAINER_PY.read_text()
    assert 'url[len("sqlite:////") - 1]' not in text, (
        "_sqlite_path_from_settings uses the off-by-one bug "
        "url[len(prefix) - 1] which returns a single character "
        "instead of the substring url[len(prefix):]. Use "
        "url[len(\"sqlite://\"):] (or url[len(\"sqlite:///\"):]) "
        "instead."
    )


def test_helper_uses_colon_slice_not_bracket_slice() -> None:
    """The fix must use ``url[len(\"sqlite://\"):]`` (with the
    trailing colon) so the leading slash is preserved for
    absolute paths.
    """
    text = CONTAINER_PY.read_text()
    assert 'url[len("sqlite://"):]' in text, (
        "_sqlite_path_from_settings must use "
        "url[len(\"sqlite://\"):] to preserve the leading slash "
        "for absolute paths"
    )


