"""
Round-trip tests for the v4 schema migration: ``last_error`` persistence.

Background
----------
Before this migration, the orchestrator's ``_fail()`` set
``session.last_error`` on the in-memory ``ResearchSession`` and
the API surface (``WorkspaceResponse.last_error``) read it back
via ``getattr`` -- but the field was NEVER written to SQLite.
After a container restart, the value was gone even though the
``state_history`` JSON still had the reason in
``transition.reason``. Users landing on an ERROR-state workspace
after a restart had no actionable information.

v4 closes that gap: a nullable ``last_error TEXT`` column is
added to ``workspaces``. The ``SqliteWorkspaceRepository`` now
writes the entity's ``last_error`` on every ``_save()`` and
restores it in ``_dict_to_workspace()``. Re-running the migration
on a v4 database is a no-op (idempotent ALTER detection).

These tests exercise the migration end-to-end with a real
SQLite file in a temp directory, no mocks for the persistence
layer. They pin:

  1. Positive -- a fresh v4 database round-trips ``last_error``
     through create -> get -> reload. The ``OR REPLACE`` +
     column-indexed read works correctly.
  2. Clearing -- a non-ERROR workspace's ``last_error`` resets
     to NULL on round-trip. The ``force_state`` path clears it
     on every successful transition.
  3. Migration idempotency -- calling ``_migrate()`` twice on a
     v3 database upgrades to v4 cleanly; running it on a v4
     database is a no-op.
  4. Forward compatibility -- a pre-v4 SQLite file (no
     ``last_error`` column) is read with ``last_error = None``
     thanks to the defensive padding in ``_row_to_dict``.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from datetime import datetime
from typing import Iterator
from uuid import UUID

import pytest

from app.core.enums.workspace_state import (
    WorkspaceAction,
    WorkspaceState,
)
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_session import ResearchSession
from app.infrastructure.storage.sqlite_workspace_repository import (
    SqliteWorkspaceRepository,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db_path() -> Iterator[str]:
    """Yield a unique tempfile path for the SQLite DB.

    The file is removed on teardown so each test starts with an
    empty filesystem. We use a real filesystem path (not an
    in-memory DB) because the repository's connection logic
    treats the path opaquely and an in-memory ``:memory:``
    connection wouldn't survive the repository's separate
    ``sqlite3.connect()`` calls.
    """
    fd, path = tempfile.mkstemp(suffix=".db", prefix="bioresearch_test_")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _make_workspace(
    state: WorkspaceState = WorkspaceState.CREATED,
    last_error: str | None = None,
) -> ResearchSession:
    """Construct a minimal valid ResearchSession for round-trip tests."""
    return ResearchSession(
        id=uuid.uuid4(),
        question=ResearchQuestion(
            question="What is the role of last_error persistence?"
        ),
        state=state,
        last_error=last_error,
        # ``state_history`` defaults to [] which is fine.
    )


# ---------------------------------------------------------------------------
# Fresh v4 database
# ---------------------------------------------------------------------------


def test_v4_fresh_database_creates_last_error_column(temp_db_path) -> None:
    """A fresh v4 database has the ``last_error`` column.

    Pins the contract that the ``_init_db`` CREATE TABLE
    statement (and the v4 migration add-column loop on
    re-init) leaves a v4-shaped schema in place.
    """
    repo = SqliteWorkspaceRepository(db_path=temp_db_path)
    # Trigger migration by hitting any repo method.
    repo.create(_make_workspace())
    with sqlite3.connect(temp_db_path) as c:
        cols = [row[1] for row in c.execute("PRAGMA table_info(workspaces)").fetchall()]
    assert "last_error" in cols, (
        f"v4 schema missing last_error column; got: {cols}"
    )


def test_v4_round_trip_preserves_last_error(temp_db_path) -> None:
    """create(workspace_with_error) -> get(error) -> reload.

    The key contract: an ERROR-state workspace's ``last_error``
    string survives the SQLite round-trip. Without this,
    after a container restart the API would return
    ``last_error: null`` and the frontend's
    ``report-error-detail`` block would be empty -- the user
    would have no actionable information about why their
    workspace is broken.
    """
    repo = SqliteWorkspaceRepository(db_path=temp_db_path)
    err_message = "RuntimeError: provider unreachable"
    ws = _make_workspace(
        state=WorkspaceState.ERROR,
        last_error=err_message,
    )
    repo.create(ws)

    reloaded = repo.get(ws.id)
    assert reloaded.last_error == err_message, (
        f"last_error did not round-trip; expected {err_message!r} "
        f"got {reloaded.last_error!r}"
    )
    assert reloaded.state is WorkspaceState.ERROR


def test_v4_round_trip_clears_last_error_on_successful_update(
    temp_db_path,
) -> None:
    """A successful update (non-ERROR state) clears ``last_error``.

    Mirrors the real orchestrator path: when ``transition_to``
    moves a workspace back to CREATED (via RETRY), the
    entity's ``last_error`` is set to ``None`` (per the
    ``transition_to`` docstring: "Clears ``last_error`` on a
    successful transition"). We persist that ``None`` so a
    later refetch doesn't show stale error context from a
    previous failed attempt.
    """
    repo = SqliteWorkspaceRepository(db_path=temp_db_path)
    err_message = "RuntimeError: previous failure"
    ws = _make_workspace(
        state=WorkspaceState.ERROR,
        last_error=err_message,
    )
    repo.create(ws)
    assert repo.get(ws.id).last_error == err_message

    # Simulate a successful RETRY: move to CREATED with
    # ``last_error`` cleared (transition_to does this).
    ws.state = WorkspaceState.CREATED
    ws.last_error = None
    ws.state_history.clear()  # don't include stale history
    repo.update(ws)

    reloaded = repo.get(ws.id)
    assert reloaded.state is WorkspaceState.CREATED
    # After RETRY, ``last_error`` should be None -- the
    # recovery cleared it.
    assert reloaded.last_error is None, (
        f"last_error should have been cleared on successful "
        f"transition; got {reloaded.last_error!r}"
    )


# ---------------------------------------------------------------------------
# Migration mechanics
# ---------------------------------------------------------------------------


def _set_user_version(db_path: str, version: int) -> None:
    """Set the SQLite user_version pragma directly.

    Used to construct synthetic pre-v3 / pre-v4 databases for
    the migration tests without having to roll back the
    migration code itself.
    """
    with sqlite3.connect(db_path) as c:
        c.execute(f"PRAGMA user_version = {version}")
        c.commit()


def test_v3_database_upgrades_to_v4_via_migration(temp_db_path) -> None:
    """A v3 database (13 columns, no last_error) upgrades to v4.

    Pins the migration's idempotent ALTER TABLE behaviour:
    the v4 column loop sees ``last_error`` is missing from
    the existing column set, runs ``ALTER TABLE ... ADD
    COLUMN last_error TEXT``, then bumps the user_version
    pragma to 4. A second ``_init_db()`` call sees the
    column is already present (no-op) and the pragma is at
    the target (no-op).
    """
    # Step 1: create a v3 database by reading the source code's
    # old-schema CREATE TABLE statement and applying it via
    # raw SQL. Then hand-bump the schema version to 3 via the
    # `user_version` pragma so `_migrate` thinks the DB is
    # already at v3.
    v3_create = """
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            papers TEXT,
            summary TEXT,
            report TEXT,
            notes TEXT,
            metadata TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'CREATED',
            state_history TEXT,
            evidence_comparison TEXT,
            published_report TEXT
        )
    """
    with sqlite3.connect(temp_db_path) as c:
        c.execute(v3_create)
        c.execute("PRAGMA user_version = 3")
        c.commit()

    # Verify the column set is v3-shaped.
    with sqlite3.connect(temp_db_path) as c:
        cols = [row[1] for row in c.execute("PRAGMA table_info(workspaces)").fetchall()]
    assert "last_error" not in cols
    assert "published_report" in cols

    # Step 2: opening the repo runs ``_init_db()``, which runs
    # ``_migrate()``. The v4 loop will detect the missing
    # ``last_error`` column and add it. A second open is a
    # no-op (the column is already present, pragma is at v4).
    repo = SqliteWorkspaceRepository(db_path=temp_db_path)
    # Trigger migration by creating a workspace.
    ws = _make_workspace()
    repo.create(ws)

    with sqlite3.connect(temp_db_path) as c:
        version = c.execute("PRAGMA user_version").fetchone()[0]
        cols = [row[1] for row in c.execute("PRAGMA table_info(workspaces)").fetchall()]

    # A v3 database upgrades all the way to v5 (the latest)
    # in a single ``_init_db()`` call -- the migration is
    # additive, so v4 and v5 columns are added back-to-back.
    # We assert >= 4 here rather than == 4 so the test still
    # passes when v6 / v7 / ... land. Pinning ``user_version``
    # exactly to 4 would over-couple the test to LATEST_SCHEMA_VERSION.
    assert version >= 4, f"expected user_version>=4, got {version}"
    assert "last_error" in cols, (
        f"v4 migration didn't add last_error; cols={cols}"
    )
    assert "last_error_at" in cols, (
        f"v5 migration didn't add last_error_at; cols={cols}"
    )

    # Step 3: idempotency. A second ``SqliteWorkspaceRepository``
    # open should not re-add or drop the column.
    SqliteWorkspaceRepository(db_path=temp_db_path)
    with sqlite3.connect(temp_db_path) as c:
        version2 = c.execute("PRAGMA user_version").fetchone()[0]
        cols2 = [row[1] for row in c.execute("PRAGMA table_info(workspaces)").fetchall()]
    assert version2 == version
    assert cols == cols2, (
        f"second migration changed schema: before={cols} after={cols2}"
    )


def test_v4_database_handles_pre_v4_row_gracefully(temp_db_path) -> None:
    """A pre-v4 row (no last_error column) reads as ``last_error=None``.

    Pins the forward-compatibility contract: even if a user
    somehow has a row from before the migration ran (e.g.
    from a partial upgrade that copied data without recreating
    the schema), the repository must not crash with
    IndexError. The defensive padding in ``_row_to_dict``
    fills the missing column position with ``None``, which is
    exactly the right default because a pre-v4 workspace
    never had a ``last_error`` recorded.
    """
    # Step 1: write a row that exactly matches the pre-v4
    # schema (no ``last_error`` column). Use raw SQL to bypass
    # the repository's JSON serialisers.
    pre_v4_id = str(uuid.uuid4())
    with sqlite3.connect(temp_db_path) as c:
        # Use the v3 CREATE TABLE for consistency with the
        # migrate-up test.
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                papers TEXT,
                summary TEXT,
                report TEXT,
                notes TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'CREATED',
                state_history TEXT,
                evidence_comparison TEXT,
                published_report TEXT
            )
        """
        )
        c.execute(
            """
            INSERT INTO workspaces (
                id, question, papers, summary, report, notes,
                metadata, created_at, updated_at,
                state, state_history, evidence_comparison,
                published_report
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                pre_v4_id,
                "Legacy pre-v4 workspace",
                "[]",
                "null",
                "null",
                "[]",
                "{}",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "ERROR",  # a pre-v4 ERROR-state workspace; we'd expect last_error to be NONE for these
                "[]",
                "null",
                "null",
            ),
        )
        c.commit()

    # Step 2: repo opens the DB, runs the v4 migration to add
    # last_error, but the existing row has NULL in the new column.
    repo = SqliteWorkspaceRepository(db_path=temp_db_path)
    # Force migration. ``_init_db`` runs automatically on
    # construction but only if we hit a repo method.
    repo.list_workspaces()

    # Step 3: read the pre-v4 row via the repository. It must
    # NOT raise IndexError -- the defensive padding fills the
    # missing last_error with None.
    reloaded = repo.get(uuid.UUID(pre_v4_id))
    assert reloaded.state is WorkspaceState.ERROR
    # The pre-v4 row has no ``last_error`` recorded -- the
    # defensive padding fills it with None, which is the
    # right default for a pre-migration workspace.
    assert reloaded.last_error is None


# ---------------------------------------------------------------------------
# Entity-level: the entity field round-trips through the wire format
# ---------------------------------------------------------------------------


def test_v4_last_error_survives_state_history_correlation(temp_db_path) -> None:
    """last_error matches the most recent ERROR transition's reason.

    The orchestrator sets ``last_error`` via ``force_state``
    with a reason like ``"RemoteProtocolError: ... connection
    closed"``. We assert the column value matches what we
    wrote -- so a future contributor who accidentally changes
    the persistence layer to write a different field (e.g.
    a generic "see logs" placeholder) gets caught.
    """
    repo = SqliteWorkspaceRepository(db_path=temp_db_path)
    # A long, realistic-looking error message -- the kind the
    # orchestrator's ``_fail`` writes via ``force_state``.
    realistic_error = (
        "RemoteProtocolError: peer closed connection without response "
        "(provider=api.minimax.chat; timeout=30s; attempt=1/3)"
    )
    ws = _make_workspace(
        state=WorkspaceState.ERROR,
        last_error=realistic_error,
    )
    repo.create(ws)

    # The state_history in this fixture is empty -- there's no
    # transition history to compare against. We just pin the
    # raw round-trip here. The state-history correlation is
    # covered by the orchestrator-level integration tests.
    reloaded = repo.get(ws.id)
    assert reloaded.last_error == realistic_error
# ---------------------------------------------------------------------------
# v5 schema: ``last_error_at`` round-trip
# ---------------------------------------------------------------------------
#
# The v5 migration adds a ``last_error_at TEXT`` column to track
# when the workspace entered its current ERROR state. Pairs with
# the v4 ``last_error`` string so the UI can show "X seconds ago"
# / "at HH:MM:SS" for diagnostic clarity. These tests pin the
# round-trip behaviour and the forward-compat path (pre-v5 rows
# read as ``last_error_at = None``).


def _force_error_state(ws):
    """Move a workspace to ERROR with a real ``last_error_at``
    timestamp via the entity's ``force_state`` (mirrors what
    ``WorkspaceOrchestrator._fail`` does in production).
    """
    ws.force_state(
        WorkspaceState.ERROR,
        reason="fixture failure for v5 round-trip test",
    )


def _retry_to_created(ws):
    """Move a workspace out of ERROR via the FSM RETRY action.

    Mirrors ``WorkspaceOrchestrator.retry`` -- calls
    ``session.transition_to(WorkspaceAction.RETRY)`` which the
    FSM table maps ERROR -> CREATED. The transition clears
    both ``last_error`` and ``last_error_at``.
    """
    ws.transition_to(WorkspaceAction.RETRY)


def test_last_error_at_round_trip_via_get(tmp_path) -> None:
    """Positive: ERROR-state workspace's ``last_error_at`` survives
    ``_save() -> get()`` via SQLite.

    Mirrors ``test_last_error_round_trip_via_get`` (the v4
    positive pin) but for the v5 timestamp field. We force the
    workspace into ERROR so ``last_error_at`` is non-null;
    then save + get + assert the timestamp round-trips
    losslessly.
    """
    db = str(tmp_path / "v5_at.db")
    repo = SqliteWorkspaceRepository(db_path=db)
    ws = _make_workspace()
    _force_error_state(ws)
    # Capture the timestamp BEFORE save() so we can compare
    # against the reloaded value. ``force_state`` sets
    # ``last_error_at = self.updated_at`` -- the updated_at
    # the entity stamped in the same call.
    original_at = ws.last_error_at
    repo.create(ws)

    reloaded = repo.get(ws.id)
    assert reloaded.last_error_at == original_at, (
        f"last_error_at round-trip mismatch: original={original_at!r} "
        f"reloaded={reloaded.last_error_at!r}"
    )
    # ISO-8601 round-trip preserves the ``tzinfo``. The
    # original is tz-aware (UTC); the deserialised one must
    # be too. Catches a regression where ``fromisoformat``
    # returns a naive datetime (Python 3.10 -- pre-3.11 --
    # did this for the "Z" suffix).
    assert reloaded.last_error_at is not None
    assert reloaded.last_error_at.tzinfo is not None, (
        f"last_error_at lost its tzinfo after round-trip: "
        f"{reloaded.last_error_at!r}"
    )


def test_last_error_at_cleared_on_successful_update(tmp_path) -> None:
    """Audit-trail: leaving ERROR via a successful update
    clears ``last_error_at`` to None (mirrors ``last_error``).

    Pinning this so a future contributor doesn't accidentally
    decouple the two fields -- they're a pair. If a workspace
    leaves ERROR (RETRY or any other transition), both fields
    must clear in lockstep.
    """
    db = str(tmp_path / "v5_at_clear.db")
    repo = SqliteWorkspaceRepository(db_path=db)
    ws = _make_workspace()
    _force_error_state(ws)
    assert ws.last_error_at is not None  # precondition
    repo.create(ws)

    # Successful transition away from ERROR (RETRY -> CREATED).
    # ``WorkspaceOrchestrator.retry`` calls this in production.
    _retry_to_created(ws)
    repo.update(ws)

    reloaded = repo.get(ws.id)
    assert reloaded.last_error is None
    assert reloaded.last_error_at is None, (
        f"last_error_at not cleared after retry: "
        f"last_error_at={reloaded.last_error_at!r}"
    )


def test_last_error_at_iso_string_round_trip(tmp_path) -> None:
    """Wire-format pin: the SQLite column stores the timestamp
    as ISO-8601 text, NOT as a Unix epoch or as JSON.

    The same wire format ``created_at`` / ``updated_at`` use.
    Reading directly from SQLite (``sqlite3.connect``) lets us
    assert on the raw column value, catching a regression where
    someone changes ``_save`` to write a different format.
    """
    db = str(tmp_path / "v5_at_iso.db")
    repo = SqliteWorkspaceRepository(db_path=db)
    ws = _make_workspace()
    _force_error_state(ws)
    original_at = ws.last_error_at
    repo.create(ws)

    with sqlite3.connect(db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_error_at FROM workspaces WHERE id = ?",
            (str(ws.id),),
        )
        row = cursor.fetchone()
    raw = row[0]
    assert raw is not None
    # ``datetime.isoformat()`` produces strings starting with
    # a 4-digit year and a ``T`` separator (e.g.
    # ``"2026-08-26T15:30:00+00:00"``). Pinning the prefix is
    # enough to catch a regression where someone writes a
    # different format (Unix epoch int, JSON, RFC 2822, etc.).
    assert raw.startswith("20") and "T" in raw, (
        f"last_error_at column has unexpected wire format: {raw!r}"
    )
    # Round-trip via ``datetime.fromisoformat`` must reproduce
    # the original timestamp exactly (the same call the
    # deserialiser uses).
    assert datetime.fromisoformat(raw) == original_at


def test_pre_v5_database_reads_as_no_last_error_at(tmp_path) -> None:
    """Forward compat: a v4-schema database (no ``last_error_at``
    column) loads with ``last_error_at=None``.

    Mirrors the v4 forward-compat test (``test_pre_v4_database_*``)
    for the new column. We hand-roll the v4 schema (no
    ``last_error_at`` column) and confirm the repo reads the
    padded ``None`` instead of raising IndexError.
    """
    db = str(tmp_path / "v5_pre.db")
    # Hand-roll the v4 schema: same as the production v4
    # CREATE TABLE but without the ``last_error_at`` column.
    with sqlite3.connect(db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE workspaces (
                id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                papers TEXT,
                summary TEXT,
                report TEXT,
                notes TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'CREATED',
                state_history TEXT,
                evidence_comparison TEXT,
                published_report TEXT,
                last_error TEXT
            )
            """
        )
        # Insert a row with last_error set but no
        # last_error_at. The migration should add the column
        # on first ``_init_db()`` and back-fill it as NULL.
        ws_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO workspaces (
                id, question, created_at, updated_at,
                state, last_error
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ws_id,
                "pre-v5 test",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "ERROR",
                "Pre-v5 error message",
            ),
        )

    # Open the repo. ``_init_db`` runs the v5 migration:
    # ``last_error_at`` is added as a NULL column.
    repo = SqliteWorkspaceRepository(db_path=db)

    # Read the row back. ``last_error_at`` should be None
    # (the pre-v5 row's column was NULL by default; the
    # migration didn't back-fill it -- that's correct
    # behaviour because we don't know when the error
    # actually happened for legacy rows).
    reloaded = repo.get(UUID(ws_id))
    assert reloaded.state == WorkspaceState.ERROR
    assert reloaded.last_error == "Pre-v5 error message"
    assert reloaded.last_error_at is None, (
        f"pre-v5 row should have last_error_at=None, got "
        f"{reloaded.last_error_at!r}"
    )

    # Schema upgraded cleanly.
    with sqlite3.connect(db) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        cols = [
            row[1]
            for row in conn.execute("PRAGMA table_info(workspaces)").fetchall()
        ]
    assert version == 6
    assert "last_error_at" in cols