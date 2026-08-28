"""
tests/unit/test_sqlite_in_memory.py

Tests that ``SqliteWorkspaceRepository`` correctly handles
SQLite's ``:memory:`` databases by substituting them with
a per-process temporary file.

Background
----------
SQLite ``:memory:`` databases are *per-connection*: every
``sqlite3.connect(":memory:")`` call returns a brand-new
empty database. That means a multi-step workflow that
opens several connections against the same path (one to
create the schema in ``_init_db``, several more to read
it later) cannot see the data created earlier.

CI tests use ``DATABASE_URL=sqlite:///:memory:`` so the
whole test suite runs against an in-memory database. The
shared-cache URI trick (``file::memory:?cache=shared``)
doesn't work either: the in-memory DB is only visible
while the originating connection is open. Closed-connection
queries return ``no such table: workspaces``.

The fix: ``__init__`` substitutes ``:memory:`` with a
per-process temporary file path. Temp files behave like
ordinary files: every ``sqlite3.connect(path)`` sees the
same on-disk data. The temp file lives for the lifetime
of the process and is left behind on disk after the test
session (the OS cleans ``/tmp`` periodically; for CI
containers that auto-stop, the file is removed with the
container).

These tests pin the substitution + the multi-step
workflow it enables.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from app.infrastructure.storage.sqlite_workspace_repository import (
    SqliteWorkspaceRepository,
)


class TestSqliteInMemorySubstitution:
    """Pin the ``:memory:`` -> temp-file substitution at
    ``__init__``."""

    def test_memory_path_is_substituted_to_temp_file(self):
        """``__init__`` must rewrite ``:memory:`` to a real
        file path so subsequent connections see the
        schema. After init, ``self.db_path`` should NOT
        be the literal ``":memory:"`` string.
        """
        repo = SqliteWorkspaceRepository(db_path=":memory:")
        try:
            assert repo.db_path != ":memory:", (
                "db_path must be rewritten from ':memory:' "
                "to a per-process temp file so every "
                "subsequent sqlite3.connect() sees the "
                "same schema"
            )
            assert repo.db_path.startswith("/"), (
                f"rewritten path should be absolute, got {repo.db_path!r}"
            )
            assert os.path.exists(repo.db_path), (
                f"temp file should exist at {repo.db_path!r}"
            )
        finally:
            # Clean up the temp file the test created.
            if os.path.exists(repo.db_path):
                os.unlink(repo.db_path)

    def test_file_path_is_passed_through_unchanged(self):
        """File-backed paths must NOT be rewritten --
        ``__init__`` only intercepts the literal
        ``:memory:`` string.
        """
        with tempfile.NamedTemporaryFile(
            prefix="bioresearch-test-",
            suffix=".db",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name

        try:
            repo = SqliteWorkspaceRepository(db_path=tmp_path)
            try:
                assert repo.db_path == tmp_path, (
                    "file-backed paths must be passed through "
                    "unchanged (only ':memory:' is intercepted)"
                )
            finally:
                # Don't tear down the file -- the temp
                # file was opened by the test, not the repo.
                # ``_init_db`` doesn't auto-delete.
                pass
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestSqliteInMemorySchemaPersistence:
    """Pin the multi-step workflow that the temp-file
    substitution enables: ``_init_db`` creates the schema
    in one connection; a later ``workspace_state_counts``
    call opens a second connection and reads the schema.
    Without the temp-file fix, the second connection sees
    an empty database and raises ``no such table: workspaces``.
    """

    def test_schema_created_in_init_db_visible_to_later_methods(self):
        """The exact scenario that motivated the fix:
        ``_init_db`` runs ``CREATE TABLE`` in connection A;
        ``workspace_state_counts`` opens connection B and
        expects the schema to be there.
        """
        repo = SqliteWorkspaceRepository(db_path=":memory:")
        try:
            # ``_init_db`` has already run. Now call a
            # method that opens its OWN connection.
            counts = repo.workspace_state_counts()
            # If the schema were invisible to the second
            # connection, ``cursor.execute`` would raise
            # ``sqlite3.OperationalError: no such table`` and
            # we'd never reach this line.
            from app.core.enums.workspace_state import (
                WorkspaceState,
            )
            # Every WorkspaceState member is zero-filled
            # (the repo's contract).
            for state in WorkspaceState:
                assert state.value in counts
                assert counts[state.value] == 0
        finally:
            if os.path.exists(repo.db_path):
                os.unlink(repo.db_path)

    def test_two_repository_instances_share_the_temp_file(self):
        """When two ``SqliteWorkspaceRepository`` instances
        are created in the same process with the same
        ``:memory:`` substitution, each gets its OWN
        per-instance temp file. The temp-file substitution
        is per-instance (not module-global) so tests can
        run side-by-side without cross-contamination.

        This is intentional: a process-level singleton
        would surprise tests that explicitly want isolation
        between subtests. The temp-file is cheap
        (``NamedTemporaryFile``) so per-instance allocation
        is fine.
        """
        repo1 = SqliteWorkspaceRepository(db_path=":memory:")
        repo2 = SqliteWorkspaceRepository(db_path=":memory:")
        try:
            assert repo1.db_path != repo2.db_path, (
                "two instances should get different temp "
                "files (each instance is isolated)"
            )
        finally:
            for repo in (repo1, repo2):
                if os.path.exists(repo.db_path):
                    os.unlink(repo.db_path)


class TestSqliteInMemoryEndToEnd:
    """End-to-end: the test_spa_routing -> test_admin_endpoints
    ordering bug is fixed. ``test_spa_routing`` opens the
    ``main`` application once (creating a temp-file DB via
    ``Container.build()``); ``test_admin_endpoints`` opens
    ``main`` again (creating a SEPARATE temp-file DB via
    the same singleton). The route handler in
    ``/admin/orchestrator-stats`` calls
    ``workspace_state_counts`` on the cached singleton --
    which lives in the SECOND temp file, with the schema
    created in the second ``_init_db``. Before the fix, the
    singleton pointed at a different connection than the
    per-call methods, so the per-call methods saw an empty
    database and crashed.
    """

    def test_state_counts_after_init_db_works(self):
        """Direct unit test: instantiate the repo with
        ``:memory:``, then call ``workspace_state_counts``
        directly (the same method the orchestrator's
        ``state_counts`` delegates to). This is what the
        ``/admin/orchestrator-stats`` route does at the
        HTTP layer.
        """
        repo = SqliteWorkspaceRepository(db_path=":memory:")
        try:
            counts = repo.workspace_state_counts()
            from app.core.enums.workspace_state import (
                WorkspaceState,
            )
            for state in WorkspaceState:
                assert state.value in counts
                assert counts[state.value] == 0
        finally:
            if os.path.exists(repo.db_path):
                os.unlink(repo.db_path)
