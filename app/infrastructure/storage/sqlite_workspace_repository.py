"""
sqlite_workspace_repository.py

SQLite implementation of the workspace repository.

Purpose
-------
Provides persistent storage for Research Workspaces using the
built-in ``sqlite3`` module. This is the production repository
that ensures workspaces survive server restarts.

The repository handles:

- Database initialisation (idempotent schema creation and additive
  migration from the pre-FSM schema).
- Saving (create/update) and retrieving ResearchSession entities.
- Serialization of domain entities to/from database rows.
- Migration of legacy rows that pre-date the FSM fields.

All methods respect the WorkspaceRepository interface and raise
ValueError when expected entities are not found.

Additive migration
------------------
The schema introduced by the FSM refactor adds three columns:

- ``state``: the FSM state of the workspace (text).
- ``state_history``: ordered list of state transitions (JSON).
- ``published_report``: serialised PDF bytes (JSON, v3+).
- ``last_error``: human-readable error string for ERROR-state
  workspaces (v4+).
- ``last_error_at``: UTC timestamp paired with ``last_error`` (v5+).

The v7 migration (2026-08-30) DROPs the previously-added
``evidence_comparison`` column because the cross-paper
comparison state was removed from the FSM (see ADR for details).

Existing rows are upgraded on read by the ``_row_to_workspace``
helper: the inferred state is computed from the row's existing
fields (workspaces with a report are REPORTED, with a summary are
SUMMARIZED, with papers are PAPERS_RETRIEVED, otherwise CREATED).
This keeps the migration fully backward compatible.


Architecture
------------

    WorkspaceRepository (interface)
                |
                v
    SqliteWorkspaceRepository
                |
                v
          SQLite database

Author
------
Guillermo Ramajo Fernández
"""

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.enums.workspace_state import WorkspaceState
from app.core.enums.citation_style import CitationStyleEnum
from app.domain.entities.author import Author
from app.domain.entities.citation import Citation
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.research_session import ResearchSession, StateTransition
from app.domain.entities.summary import Summary
from app.domain.interfaces.workspace_repository import WorkspaceRepository
from app.core.enums.workspace_state import WorkspaceAction


logger = logging.getLogger(__name__)


def _rewrite_legacy_summary_in_blob(blob: dict) -> bool:
    """
    Rewrite ``{"text": ...}`` to ``{"body": ...}`` in a Summary
    blob if the legacy shape is detected.

    Handles three on-disk shapes:

      1. A standalone Summary JSON (in the ``summary`` column):
         ``{"text": "...", "papers_used": [...]}``.

      2. A nested Summary inside a ResearchReport, serialised
         as a dict (newer shape): ``{"summary": {"text": "...",
         "papers_used": [...]}, "citations": [...], ...}``.

      3. A nested Summary inside a ResearchReport, serialised
         as a stringified JSON blob (legacy shape):
         ``{"summary": "{\"text\": \"...\", \"papers_used\": [...]}",
         "citations": [...], ...}``. The legacy
         ``_serialize_report`` wrote the Summary blob to JSON
         once for the inner object and again for the outer
         envelope, producing this double-encoded shape.

    The function walks the dict and rewrites every Summary it
    finds in-place. Returns True if any rewrite happened.

    Parameters
    ----------
    blob : dict
        Deserialised JSON from a single column. Mutated in
        place when the legacy shape is detected.

    Returns
    -------
    bool
        True if any ``text`` -> ``body`` rewrite happened
        (signalling the caller to persist the blob).
    """
    changed = False

    # Case 1: the blob IS a Summary (the ``summary`` column).
    if isinstance(blob.get("text"), str) and "body" not in blob:
        blob["body"] = blob.pop("text")
        changed = True

    # Case 2 & 3: the blob contains a nested Summary under
    # ``report.summary`` (the ``report`` column) -- either as
    # a dict (newer shape) or as a stringified JSON blob
    # (legacy shape).
    nested = blob.get("summary")
    if isinstance(nested, dict):
        # Case 2: nested dict.
        if (
            isinstance(nested.get("text"), str)
            and "body" not in nested
        ):
            nested["body"] = nested.pop("text")
            changed = True
    elif isinstance(nested, str):
        # Case 3: nested stringified JSON. Parse, rewrite, and
        # re-serialise back to a string. The legacy
        # ``_serialize_report`` produced this double-encoded
        # shape; the newer ``_serialize_report`` writes the
        # inner Summary as a real dict, but the on-disk data
        # has not been migrated yet.
        try:
            inner = json.loads(nested)
        except (json.JSONDecodeError, TypeError):
            # Malformed inner payload -- leave it alone so the
            # operator can inspect the broken row.
            return changed
        if isinstance(inner, dict) and _rewrite_legacy_summary_in_blob(inner):
            blob["summary"] = json.dumps(inner, separators=(",", ":"))
            changed = True

    return changed


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

LATEST_SCHEMA_VERSION = 8


# Columns that were added in each schema version. The repository
# performs an additive migration on initialisation to bring older
# databases up to the latest schema.
_V2_COLUMNS = (
    ("state", "TEXT NOT NULL DEFAULT 'CREATED'"),
    ("state_history", "TEXT"),
    ("evidence_comparison", "TEXT"),
)
# v3: PUBLISH action support. We persist the rendered PDF bytes
# on the workspace so the ``GET /workspaces/{id}/published-report.pdf``
# endpoint can serve them after a process restart. The bytes are
# stored as a JSON-serialised blob (base64-encoded so the JSON
# layer doesn't choke on raw PDF binary). See
# ``_serialize_published_report`` / ``_deserialize_published_report``.
_V3_COLUMNS = (
    ("published_report", "TEXT"),
)
# v4: ``last_error`` persistence.
#
# Before this migration, the orchestrator's ``_fail()`` set
# ``session.last_error`` on the in-memory ``ResearchSession`` and
# the API surface (``WorkspaceResponse.last_error``) read it back
# via ``getattr`` -- but the field was NEVER written to SQLite.
# After a container restart, the value was gone even though the
# ``state_history`` JSON still had the reason in
# ``transition.reason``. Users landing on an ERROR-state
# workspace after a restart had no actionable information.
#
# v4 closes that gap: we add a nullable ``last_error TEXT``
# column, write the entity field on every ``_save()``, and
# restore it on ``_dict_to_workspace()``. The key invariant is
# that ``session.last_error`` is preserved across process
# restarts -- so a user who wakes up to an ERROR-state
# workspace still sees the actionable error message.
#
# Plain ``TEXT`` is sufficient -- no JSON encoding, no base64.
# The string is bounded (~500 chars max in practice -- an
# exception message and its embedded traceback frames if the
# orchestrator chose to include them) and SQLite stores
# arbitrary-length TEXT natively.
_V4_COLUMNS = (
    ("last_error", "TEXT"),
)
# v5: ``last_error_at`` -- the UTC timestamp of when ``last_error``
# was set. Pairs with v4's ``last_error`` to give the UI a
# "fresh vs stale" signal for the diagnostic. Stored as ISO-8601
# text (the same format ``created_at`` / ``updated_at`` use --
# ``datetime.fromisoformat()`` round-trips cleanly for any
# value that ``datetime.isoformat()`` produces).
#
# Plain ``TEXT`` is sufficient. The column is nullable so
# non-ERROR workspaces (and pre-v5 rows) get ``NULL``.
_V5_COLUMNS = (
    ("last_error_at", "TEXT"),
)
# v6: ``Summary.text`` -> ``Summary.body`` data migration.
#
# Unlike v2-v5 (which are additive ``ALTER TABLE`` migrations),
# v6 is an in-place data rewrite -- the on-disk Summary JSON
# changed shape from ``{"text": "...", "papers_used": [...]}``
# to ``{"body": "...", "papers_used": [...]}``. The column
# itself (``summary TEXT``) is unchanged. The migration walks
# every workspace row and rewrites legacy data via the
# ``_rewrite_legacy_summary_in_blob`` helper, which handles
# three on-disk shapes:
#
#   1. Standalone Summary (the ``summary`` column).
#   2. Nested Summary as a dict (the ``report`` column).
#   3. Nested Summary as a stringified JSON blob (the legacy
#      ``report`` column shape -- the legacy serializer
#      double-encoded the inner Summary as a string).
#
# Idempotency: the helper returns ``False`` for already-
# migrated rows, so a v6 migration running on a v6 DB is a
# no-op. The deserializer in ``_deserialize_summary`` still
# accepts the legacy ``text`` key with a warning -- that
# path serves the "operator restored a v5 backup after v6 is
# deployed" case where the data needs to be re-migrated on
# the next instantiation.
_V6_DATA_MIGRATION = (
    "summary_text_to_body",
)
# v7: drop ``evidence_comparison`` column.
#
# The COMPARING/COMPARED FSM states and the cross-paper
# ``EvidenceComparison`` entity were removed on 2026-08-30.
# The persisted column is now dead weight. SQLite supports
# ``ALTER TABLE ... DROP COLUMN`` since 3.35 (2021); the
# Docker image (Debian Bookworm, libsqlite3 3.40+) supports
# it. The migration is idempotent: if the column is already
# gone (fresh installs on this version, or operator-removed
# by hand), the ``PRAGMA table_info`` check below skips the
# DROP. Existing rows simply lose the JSON blob, which is
# content we no longer read.
_V7_DROP_COLUMNS = (
    "evidence_comparison",
)
# v8: add ``last_known_state`` column.
#
# The 2026-08-31 FSM refactor (ADR-017) collapsed the workspace
# lifecycle to four states (INITIAL / INTERMEDIATE / FINAL /
# ERROR). When ERROR is entered we record the state the
# workspace was in immediately before, so a subsequent RETRY
# action can restore it (INITIAL for a failed search,
# INTERMEDIATE for a failed generation). The column is
# nullable: ``NULL`` for workspaces that have never been in
# ERROR, or that were in ERROR with no recoverable previous
# state (corrupted rows).
_V8_COLUMNS = (
    ("last_known_state", "TEXT"),
)


# v8 in-place state-elevation: rewrite every legacy
# ``state`` string from the previous nine-state linear FSM
# to its equivalent in the new four-state FSM (ADR-017).
#
# The mapping mirrors what ``_infer_state`` would apply on
# read -- doing it here as a SQL UPDATE keeps the
# ``/admin/orchestrator-stats`` endpoint honest (it
# GROUP BY ``state`` without consulting ``_infer_state``)
# and lets ``last_known_state`` rewrites operate on already
# upgraded data.
#
# Rows whose state is already one of the new four values
# (``INITIAL``, ``INTERMEDIATE``, ``FINAL``, ``ERROR``) are
# left untouched; only legacy enum strings are rewritten.
#
# ``state`` -> ``last_known_state`` migration: when an
# ERROR-state workspace is upgraded, we have no record of
# the state it was in *before* it entered ERROR -- the old
# state string in the column tells us only that it WAS in
# ERROR. So ``last_known_state`` stays ``NULL`` for
# pre-v8 ERROR rows; ``retry`` from ERROR for such rows
# goes to ``INITIAL`` (the safe default -- the user can
# always re-search).
_V8_STATE_ELEVATION: list[tuple[str, str]] = [
    # Initial cluster -- before any papers exist.
    ("CREATED", "INITIAL"),
    ("SEARCHING", "INITIAL"),
    # Intermediate cluster -- papers exist, no report yet.
    # Transient in-flight markers collapse to their post-state
    # because the v8 design has no transients; a workspace
    # that was mid-summarise at v7 is logically "has papers,
    # no report" == INTERMEDIATE.
    ("PAPERS_RETRIEVED", "INTERMEDIATE"),
    ("SUMMARIZING", "INTERMEDIATE"),
    ("SUMMARIZED", "INTERMEDIATE"),
    ("COMPARING", "INTERMEDIATE"),
    ("COMPARED", "INTERMEDIATE"),
    ("REPORTING", "INTERMEDIATE"),
    # Final cluster -- report exists (or was being published).
    ("REPORTED", "FINAL"),
    ("PUBLISHING", "FINAL"),
    ("COMPLETED", "FINAL"),
]


class SqliteWorkspaceRepository(WorkspaceRepository):
    """
    SQLite-based repository for Research Workspaces.

    The repository is intentionally simple: it stores the complete
    session as JSON blobs. This is appropriate for the current
    scale of a single-user research workstation. Phase 6 of the
    roadmap (long-term memory) will introduce a structured storage
    engine alongside this one.

    Attributes
    ----------
    db_path : str
        Path to the SQLite database file. Defaults to ``bioresearch.db``
        in the current working directory.
    """

    def __init__(self, db_path: str = "bioresearch.db") -> None:
        # SQLite ``:memory:`` databases are per-connection --
        # every ``sqlite3.connect(":memory:")`` call returns a
        # fresh private DB. CI tests use
        # ``DATABASE_URL=sqlite:///:memory:`` so the schema
        # created in ``_init_db`` would be invisible to
        # subsequent per-call methods like
        # ``workspace_state_counts``.
        #
        # Workaround: rewrite ``:memory:`` to a per-process
        # temporary file path. The file is created on first
        # access and lives for the duration of the process.
        # All ``sqlite3.connect`` calls against the same path
        # share the database -- unlike ``:memory:``, where
        # each call gets a fresh private DB. Using a temp
        # file (rather than a shared-cache URI) avoids the
        # SQLite quirk that the in-memory database is only
        # visible while the originating connection is open.
        #
        # File-backed paths are passed through unchanged.
        if db_path == ":memory:":
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                prefix="bioresearch-",
                suffix=".db",
                delete=False,
            )
            tmp.close()
            self.db_path = tmp.name
        else:
            self.db_path = db_path
        self._init_db()
        # v6 in-place data migration: rewrite every legacy
        # Summary blob (``{"text": ...}``) to the new
        # ``{"body": ...}`` shape. This is wired into the
        # schema-version flow (``LATEST_SCHEMA_VERSION = 8``)
        # so the schema-version pragma tracks whether data
        # migration has run, not just whether columns are
        # up to date.
        #
        # The legacy deserializer (``_deserialize_summary``)
        # still tolerates the old shape with a warning, so a
        # future rollback -- restoring a v5 backup after v6
        # is deployed -- loads cleanly. The next repository
        # instantiation re-runs the data migration and
        # normalises the restored data.
        #
        # NOTE: the v6 data migration runs INSIDE the
        # ``_init_db`` connection (not in a separate
        # connection) so it sees the schema. SQLite in-memory
        # databases (used in CI tests with
        # ``DATABASE_URL=sqlite:///:memory:``) are per-
        # connection -- a second ``sqlite3.connect(...)`` on
        # the same path would get a brand-new empty database
        # with no schema. Running the migration in the same
        # connection as the schema init avoids that
        # regression. For file-backed databases the two-
        # connection approach was fine (both connections
        # share the file), but consolidating to one
        # connection is simpler and works in both cases.
        migrated_count = self._init_db()
        if migrated_count > 0:
            logger.info(
                "workspace_repository: migrated %d legacy Summary "
                "rows from 'text' to 'body'.",
                migrated_count,
            )

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def _init_db(self) -> int:
        """
        Create the workspaces table if it does not already
        exist and apply any pending additive migrations.

        Returns
        -------
        int
            Number of legacy Summary rows rewritten by
            the v6 data migration (always 0 on a fresh
            database; 0 if the data was already in the
            ``body`` shape).

        The migration is idempotent: running it on a
        fresh database creates the latest schema; running
        it on an existing database only adds the columns
        that are missing. The v6 data rewrite runs in
        the same connection as the schema creation so
        SQLite in-memory databases (used in CI tests)
        work correctly -- see the comment in ``__init__``
        for the rationale.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
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
                    published_report TEXT,
                    last_error TEXT,
                    last_error_at TEXT,
                    last_known_state TEXT
                )
                """
            )

            # Apply additive migrations.
            self._migrate(cursor)

            # Apply v6 in-place data migration in the same
            # connection -- see __init__ docstring.
            migrated_count = self._migrate_v6_data(conn)

            # Apply v8 in-place state-elevation: rewrite every
            # legacy ``state`` string to its ADR-017 equivalent
            # so ``GROUP BY state`` queries (notably
            # ``/admin/orchestrator-stats``) see the four new
            # values. Runs in the same connection as the schema
            # migration -- ``v8`` is the data-update version,
            # not the schema version.
            migrated_count += self._migrate_v8_state_elevate(conn)

            conn.commit()
        return migrated_count

    def _connect(self) -> sqlite3.Connection:
        """
        Open a SQLite connection. For ``:memory:`` databases
        ``__init__`` rewrites the path to a per-process
        temporary file, so every call here opens against
        the same file. File-backed paths open the
        conventional way.
        """
        return sqlite3.connect(self.db_path)

    def _migrate(self, cursor: sqlite3.Cursor) -> None:
        """Apply pending schema migrations idempotently."""
        cursor.execute("PRAGMA user_version")
        current = cursor.fetchone()[0]
        if current >= LATEST_SCHEMA_VERSION:
            return

        # ``table_info`` is queried once -- used by both the v2
        # and v3 column loops to skip already-present columns
        # (idempotent migration).
        existing = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(workspaces)").fetchall()
        }

        # v2: FSM additions.
        for column_name, column_def in _V2_COLUMNS:
            if column_name not in existing:
                cursor.execute(
                    f"ALTER TABLE workspaces ADD COLUMN {column_name} {column_def}"
                )

        # v3: PUBLISH action support (see ADR-009).
        for column_name, column_def in _V3_COLUMNS:
            if column_name not in existing:
                cursor.execute(
                    f"ALTER TABLE workspaces ADD COLUMN {column_name} {column_def}"
                )

        # v4: ``last_error`` persistence so ERROR-state
        # workspaces remain debuggable across container
        # restarts. See ``_V4_COLUMNS`` docstring above for
        # the full rationale.
        for column_name, column_def in _V4_COLUMNS:
            if column_name not in existing:
                cursor.execute(
                    f"ALTER TABLE workspaces ADD COLUMN {column_name} {column_def}"
                )

        # v5: ``last_error_at`` -- the UTC timestamp paired with
        # ``last_error`` so the UI can distinguish fresh vs
        # stale errors. ``ALTER TABLE`` is idempotent here
        # because the ``existing`` set was captured once at
        # the top of this method (so a v4 -> v5 -> v4 -> v5
        # migration sequence still leaves a single column).
        # ``existing`` doesn't get re-checked because the
        # earlier loops may have just added columns to it;
        # capturing before the loop is the right pattern.
        for column_name, column_def in _V5_COLUMNS:
            if column_name not in existing:
                cursor.execute(
                    f"ALTER TABLE workspaces ADD COLUMN {column_name} {column_def}"
                )

        # v7: drop the ``evidence_comparison`` column. See
        # ``_V7_DROP_COLUMNS`` for the rationale. We re-read
        # ``table_info`` here because we want a fresh view
        # after the earlier ALTER TABLE calls. The
        # ``IF EXISTS`` clause keeps this idempotent for
        # databases that started life on v7.
        #
        # We run the DROP for ``current < 8`` (not
        # ``current < 7``) because the v8 data migration
        # upgrades existing v7-schema databases -- they
        # still need their ``evidence_comparison`` column
        # dropped before we can call this a v8 database.
        if current < 8:
            current_columns = {
                row[1]
                for row in cursor.execute(
                    "PRAGMA table_info(workspaces)"
                ).fetchall()
            }
            for column_name in _V7_DROP_COLUMNS:
                if column_name in current_columns:
                    cursor.execute(
                        f"ALTER TABLE workspaces DROP COLUMN {column_name}"
                    )

        # v8: add the ``last_known_state`` column. ADR-017
        # (linear 4-state FSM) needs to remember the
        # pre-ERROR state so RETRY can restore it.
        for column_name, column_def in _V8_COLUMNS:
            if column_name not in existing:
                cursor.execute(
                    f"ALTER TABLE workspaces ADD COLUMN {column_name} {column_def}"
                )

        # Bump the schema version -- this happens BEFORE v6
        # because v6 is a (potentially slow) data rewrite
        # that could fail mid-loop. If the data migration
        # raises, we'd rather the operator see ``user_version =
        # 6`` with partial migration than get stuck on v5 with
        # a half-rewritten database.
        cursor.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION}")

    def _migrate_v6_data(self, db_or_conn) -> int:
        """
        v6 in-place data migration: rewrite every legacy
        ``Summary`` blob to the new ``body`` shape.

        Runs in the same connection as ``_init_db`` so
        SQLite in-memory databases (used in CI tests)
        see the schema. Accepts either an open
        ``sqlite3.Connection`` (preferred -- lets the caller
        control connection lifetime) or a ``db_path``
        string (legacy two-connection pattern, kept for
        any external callers that still pass a path).

        See ``_V6_DATA_MIGRATION`` docstring above for the
        three on-disk shapes this helper handles.

        Returns
        -------
        int
            Number of rows rewritten. Zero on an already-v6
            database.
        """
        if isinstance(db_or_conn, str):
            # Legacy single-call pattern: open our own
            # connection. Works for file-backed DBs but
            # NOT for ``:memory:`` (a fresh per-connection
            # database with no schema). Kept for any
            # external caller that passes a path string.
            conn = sqlite3.connect(db_or_conn)
            should_close = True
        else:
            conn = db_or_conn
            should_close = False
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, summary, report FROM workspaces"
            )
            rows = cursor.fetchall()
            migrated_count = 0
            for workspace_id, summary_json, report_json in rows:
                for column, raw in (
                    ("summary", summary_json),
                    ("report", report_json),
                ):
                    if not raw or raw == "null":
                        continue
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not _rewrite_legacy_summary_in_blob(data):
                        continue
                    new_raw = json.dumps(data, separators=(",", ":"))
                    cursor.execute(
                        f"UPDATE workspaces SET {column} = ? WHERE id = ?",
                        (new_raw, workspace_id),
                    )
                    migrated_count += 1
            conn.commit()
            return migrated_count
        finally:
            if should_close:
                conn.close()

    def _migrate_v8_state_elevate(self, db_or_conn) -> int:
        """
        v8 in-place data migration: rewrite every legacy
        ``state`` string to its ADR-017 equivalent.

        Runs in the same connection as ``_init_db`` so
        SQLite in-memory databases (used in CI tests)
        see the data. Accepts either an open
        ``sqlite3.Connection`` (preferred) or a
        ``db_path`` string (legacy pattern, kept for
        symmetry with ``_migrate_v6_data``).

        The legacy enum values that may appear in the
        ``state`` column are listed in
        ``_V8_STATE_ELEVATION`` along with their target
        value. Rows whose ``state`` is already one of the
        four new FSM values (``INITIAL``, ``INTERMEDIATE``,
        ``FINAL``, ``ERROR``) are left untouched, so
        already-v8 databases skip this migration entirely.

        Returns
        -------
        int
            Number of rows rewritten. Zero on a fresh
            install or an already-upgraded v8 database.
        """
        if isinstance(db_or_conn, str):
            conn = sqlite3.connect(db_or_conn)
            should_close = True
        else:
            conn = db_or_conn
            should_close = False
        try:
            cursor = conn.cursor()
            migrated_count = 0
            for legacy_state, new_state in _V8_STATE_ELEVATION:
                cursor.execute(
                    "UPDATE workspaces SET state = ? WHERE state = ?",
                    (new_state, legacy_state),
                )
                migrated_count += cursor.rowcount
            # SQLite is in autocommit-style within the
            # transaction here; ``_init_db`` commits at the
            # end so we don't need to commit explicitly.
        finally:
            if should_close:
                conn.close()
        return migrated_count

    # ------------------------------------------------------------------
    # Repository interface
    # ------------------------------------------------------------------

    def create(self, workspace: ResearchSession) -> ResearchSession:
        if self.exists(workspace.id):
            raise ValueError(f"Workspace '{workspace.id}' already exists.")
        return self._save(workspace)

    def get(self, workspace_id: UUID) -> ResearchSession:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM workspaces WHERE id = ?",
                (str(workspace_id),),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Workspace '{workspace_id}' was not found.")
            return self._row_to_workspace(row)

    def update(self, workspace: ResearchSession) -> ResearchSession:
        if not self.exists(workspace.id):
            raise ValueError(
                f"Workspace '{workspace.id}' not found for update."
            )
        return self._save(workspace)

    def delete(self, workspace_id: UUID) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM workspaces WHERE id = ?",
                (str(workspace_id),),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Workspace '{workspace_id}' not found for deletion."
                )
            conn.commit()

    def exists(self, workspace_id: UUID) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM workspaces WHERE id = ?",
                (str(workspace_id),),
            )
            return cursor.fetchone() is not None

    def list_workspaces(self) -> List[ResearchSession]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workspaces")
            rows = cursor.fetchall()
            return [self._row_to_workspace(row) for row in rows]

    def workspace_state_counts(self) -> dict[str, int]:
        """Count workspaces per FSM state, zero-filling every state.

        Uses SQL ``GROUP BY state`` for efficiency -- one
        pass over the table instead of fetching every row.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT state, COUNT(*) FROM workspaces GROUP BY state"
            )
            rows = cursor.fetchall()
        # Zero-fill every state so the caller can rely on
        # every WorkspaceState value being present in the
        # returned dict (even with count=0).
        counts = {state.value: 0 for state in WorkspaceState}
        for state_value, count in rows:
            counts[state_value] = count
        return counts

    # ------------------------------------------------------------------
    # Internal serialisation helpers
    # ------------------------------------------------------------------

    def _save(self, workspace: ResearchSession) -> ResearchSession:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO workspaces (
                    id, question, papers, summary, report, notes,
                    metadata, created_at, updated_at,
                    state, state_history,
                    published_report, last_error, last_error_at,
                    last_known_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(workspace.id),
                    workspace.question.question,
                    self._serialize_papers(workspace.papers),
                    self._serialize_summary(workspace.summary),
                    self._serialize_report(workspace.report),
                    json.dumps(workspace.notes) if workspace.notes else "[]",
                    json.dumps(workspace.metadata) if workspace.metadata else "{}",
                    workspace.created_at.isoformat(),
                    workspace.updated_at.isoformat(),
                    workspace.state.value,
                    self._serialize_state_history(workspace.state_history),
                    self._serialize_published_report(
                        workspace.published_report
                    ),
                    # v4: persist the in-memory ``last_error``
                    # so ERROR-state workspaces remain
                    # debuggable after a restart. We store
                    # ``None`` for non-error workspaces (the
                    # column is nullable; using the literal
                    # ``None`` maps to SQL NULL, which is what
                    # we want -- the field is meaningless
                    # outside of ERROR state).
                    workspace.last_error,
                    # v5: ``last_error_at`` -- the UTC
                    # timestamp paired with ``last_error``.
                    # Stored as ISO-8601 text (the same
                    # format ``created_at`` / ``updated_at``
                    # use). ``None`` for non-error workspaces
                    # matches the ``last_error`` semantics --
                    # the timestamp is meaningless outside
                    # of ERROR state.
                    workspace.last_error_at.isoformat()
                    if workspace.last_error_at is not None
                    else None,
                    # v8: ``last_known_state`` -- the state the
                    # workspace was in immediately before
                    # ERROR was entered. ``None`` for
                    # workspaces that have never been in
                    # ERROR. RETRY reads this column to
                    # restore the right page (INITIAL for a
                    # failed search, INTERMEDIATE for a failed
                    # generation). See ADR-017.
                    workspace.last_known_state.value
                    if workspace.last_known_state is not None
                    else None,
                ),
            )
            conn.commit()
        return workspace

    @staticmethod
    def _serialize_papers(papers: List[Paper]) -> str:
        if not papers:
            return "[]"
        return json.dumps([SqliteWorkspaceRepository._paper_to_dict(p) for p in papers])

    @staticmethod
    def _paper_to_dict(paper: Paper) -> Dict[str, Any]:
        return {
            "title": paper.title,
            "authors": [
                {
                    "first_name": a.first_name,
                    "last_name": a.last_name,
                    "affiliation": a.affiliation,
                }
                for a in paper.authors
            ],
            "journal": {
                "name": paper.journal.name,
                "issn": paper.journal.issn,
                "publisher": paper.journal.publisher,
            } if paper.journal else None,
            "year": paper.year,
            "abstract": paper.abstract,
            "doi": paper.doi,
            "pmid": paper.pmid,
            "keywords": paper.keywords,
            "url": paper.url,
        }

    def _serialize_summary(self, summary: Optional[Summary]) -> str:
        if summary is None:
            return "null"
        return json.dumps(
            {
                "body": summary.body,
                "papers_used": [self._paper_to_dict(p) for p in summary.papers_used],
            }
        )

    def _serialize_report(self, report: Optional[ResearchReport]) -> str:
        if report is None:
            return "null"
        return json.dumps(
            {
                "summary": self._serialize_summary(report.summary),
                "citations": [
                    {
                        "paper": self._paper_to_dict(citation.paper),
                        "style": citation.style.value,
                    }
                    for citation in report.citations
                ],
                "limitations": report.limitations,
                "future_work": report.future_work,
                "metadata": report.metadata,
            }
        )

    def _serialize_published_report(
        self,
        published_report: Optional["PublishedReport"],
    ) -> str:
        """Serialise a PublishedReport to a JSON blob.

        The PDF bytes are base64-encoded so the JSON layer
        doesn't choke on raw binary. ``PublishedReport`` is
        typed as ``Optional[...]`` because the workspace may
        not have been published yet.

        Returns ``"null"`` (not the empty string) when the
        workspace has no published report -- matches the
        ``_serialize_report`` convention so the deserialiser
        can distinguish "no value" from "empty value".
        """
        if published_report is None:
            return "null"
        import base64 as _base64
        return json.dumps(
            {
                # ``base64`` gives us ASCII-safe bytes for the
                # JSON wrapper. The deserialiser decodes the
                # same way.
                "pdf_bytes": _base64.b64encode(
                    published_report.pdf_bytes
                ).decode("ascii"),
                "byte_size": published_report.byte_size,
                "workspace_id": published_report.workspace_id,
                # The entity field is named ``created_at`` (per
                # the dataclass). We serialise it under the
                # same key to keep the round-trip trivial.
                "created_at": published_report.created_at.isoformat(),
            }
        )

    def _deserialize_published_report(
        self,
        published_report_json: Optional[str],
    ) -> Optional["PublishedReport"]:
        """Deserialise a JSON blob back into a ``PublishedReport``.

        Returns ``None`` for ``"null"`` or empty input -- the
        column is nullable so a workspace that hasn't been
        published yet has ``published_report IS NULL``.

        Imports ``PublishedReport`` and ``base64`` lazily to
        avoid a circular dependency with the entity module
        (sqlite_workspace_repository.py is imported by the
        container at startup, before the entity is necessarily
        loaded).
        """
        if not published_report_json or published_report_json == "null":
            return None
        import base64 as _base64
        from app.domain.entities.published_report import (
            PublishedReport,
        )
        from datetime import datetime as _datetime

        data = json.loads(published_report_json)
        return PublishedReport(
            pdf_bytes=_base64.b64decode(data["pdf_bytes"]),
            byte_size=data["byte_size"],
            workspace_id=data["workspace_id"],
            created_at=_datetime.fromisoformat(data["created_at"]),
        )

    def _serialize_state_history(self, history: List[StateTransition]) -> str:
        items = [
            {
                "from_state": t.from_state.value,
                "to_state": t.to_state.value,
                "action": t.action.value if t.action is not None else None,
                "at": t.at.isoformat(),
                "reason": t.reason,
            }
            for t in history
        ]
        return json.dumps(items)

    # ------------------------------------------------------------------
    # Deserialisation
    # ------------------------------------------------------------------

    def _row_to_workspace(self, row: tuple) -> ResearchSession:
        # Row column order (after v3 migration):
        #   0 id, 1 question, 2 papers, 3 summary, 4 report, 5 notes,
        #   6 metadata, 7 created_at, 8 updated_at,
        #   9 state, 10 state_history, 11 evidence_comparison,
        #   12 published_report
        # (The schema does NOT have an evidence_matrix column --
        # it's a deserialiser-only concept the legacy code
        # sometimes pretended was a column. The padding in
        # ``_row_to_dict`` is what kept that illusion alive.)
        row_dict = self._row_to_dict(row)
        return self._dict_to_workspace(row_dict)

    def _row_to_dict(self, row: tuple) -> Dict[str, Any]:
        # Some columns may be missing in older database files; pad
        # the row defensively so the deserialiser is forward
        # compatible. The current schema has 14 columns
        # (after the v7 ``DROP evidence_comparison`` migration);
        # we pad to 15 so a database that started life on v5
        # (no last_error_at, 13 columns) still deserialises.
        #
        # Index map (after v7 migration):
        #   0  id
        #   1  question
        #   2  papers
        #   3  summary
        #   4  report
        #   5  notes
        #   6  metadata
        #   7  created_at
        #   8  updated_at
        #   9  state
        #   10 state_history
        #   11 published_report       (v3 column)
        #   12 last_error             (v4 column)
        #   13 last_error_at          (v5 column)
        #
        # Pre-v4 databases have 12 columns (no last_error); the
        # Index map (after v8 migration):
        #   0  id
        #   1  question
        #   2  papers
        #   3  summary
        #   4  report
        #   5  notes
        #   6  metadata
        #   7  created_at
        #   8  updated_at
        #   9  state
        #   10 state_history
        #   11 published_report       (v3 column)
        #   12 last_error             (v4 column)
        #   13 last_error_at          (v5 column)
        #   14 last_known_state       (v8 column)
        #
        # Pre-v4 databases have 13 columns (no last_error); the
        # padding fills ``padded[12]`` and ``padded[13]`` with
        # ``None`` -- both map to "no error".
        # Pre-v5 databases have 13 columns so only ``padded[13]``
        # resolves to the padding ``None``.
        # Pre-v7 databases had an ``evidence_comparison`` column
        # at index 11 which the v7 migration drops on connect;
        # after the drop the indices shift left by one.
        # Pre-v8 databases have 14 columns so ``padded[14]``
        # resolves to the padding ``None``.
        padded: list[Any] = list(row) + [None] * (16 - len(row))
        return {
            "id": padded[0],
            "question": padded[1],
            "papers": padded[2],
            "summary": padded[3],
            "report": padded[4],
            "notes": padded[5],
            "metadata": padded[6],
            "created_at": padded[7],
            "updated_at": padded[8],
            "state": padded[9],
            "state_history": padded[10],
            # v3: PUBLISH action support. The PDF blob is at
            # index 11 (post-v7). Pre-v7 databases had
            # ``evidence_comparison`` here -- the v7 DROP
            # COLUMN migration shifted published_report from
            # index 12 to index 11 on connect.
            "published_report": padded[11],
            # v4: ``last_error`` persistence. Index 12, so
            # pre-v4 databases (no column here) read as
            # ``None`` -- the existing behaviour (no
            # ``last_error`` exposed in the API response).
            "last_error": padded[12],
            # v5: ``last_error_at`` (ISO-8601 text or None).
            # Index 13, so pre-v5 databases (no column here)
            # read as ``None`` -- matching the v4 padding
            # behaviour for the error string itself.
            "last_error_at": padded[13],
            # v8: ``last_known_state``. The state the workspace
            # was in immediately before ERROR was entered.
            # ``None`` for workspaces that have never been in
            # ERROR (or pre-v8 rows).
            "last_known_state": padded[14],
        }

    def _dict_to_workspace(self, row_dict: Dict[str, Any]) -> ResearchSession:
        question = ResearchQuestion(row_dict["question"])
        papers = self._deserialize_papers(row_dict["papers"])
        summary = (
            self._deserialize_summary(row_dict["summary"])
            if row_dict["summary"]
            else None
        )
        report = (
            self._deserialize_report(row_dict["report"])
            if row_dict["report"]
            else None
        )
        notes = (
            json.loads(row_dict["notes"]) if row_dict["notes"] else []
        )
        metadata = (
            json.loads(row_dict["metadata"]) if row_dict["metadata"] else {}
        )
        created_at = datetime.fromisoformat(row_dict["created_at"])
        updated_at = datetime.fromisoformat(row_dict["updated_at"])

        # FSM fields.
        state = self._infer_state(row_dict, papers, summary, report)
        state_history = self._deserialize_state_history(
            row_dict.get("state_history"), state
        )

        # v3: PublishedReport. The column is nullable so we
        # only call the deserialiser when there's a value.
        published_report = (
            self._deserialize_published_report(
                row_dict.get("published_report")
            )
            if row_dict.get("published_report")
            else None
        )

        # v4: ``last_error``. The entity has ``last_error`` as a
        # regular field so we restore it directly in the
        # constructor below. ``row_dict["last_error"]`` may
        # be ``None`` for pre-v4 databases (the padding fills
        # the missing column with ``None``) or for workspaces
        # whose state isn't ERROR -- both are the right
        # default value because ``last_error`` is only
        # meaningful on ERROR-state workspaces.
        last_error = row_dict.get("last_error")

        # v5: ``last_error_at``. Parsed from the ISO-8601
        # text the column stores (``datetime.isoformat()``
        # round-trips cleanly with ``datetime.fromisoformat()``).
        # ``None`` for pre-v5 databases (the padding fills the
        # missing column with ``None``) or for non-ERROR
        # workspaces (the field is cleared alongside
        # ``last_error`` whenever the state machine leaves
        # ERROR).
        last_error_at_raw = row_dict.get("last_error_at")
        last_error_at = (
            datetime.fromisoformat(last_error_at_raw)
            if last_error_at_raw is not None
            else None
        )

        # v8: ``last_known_state`` -- the state the workspace was
        # in immediately before ERROR was entered. The raw
        # value is a string (or None); we parse it back into
        # a ``WorkspaceState`` enum value.
        last_known_state_raw = row_dict.get("last_known_state")
        last_known_state: WorkspaceState | None = None
        if last_known_state_raw:
            try:
                last_known_state = WorkspaceState(last_known_state_raw)
            except ValueError:
                # Pre-ADR-017 rows may have state values like
                # "CREATED" that no longer exist. Treat them
                # as None -- RETRY will fall back to a default.
                last_known_state = None

        workspace = ResearchSession(
            id=UUID(row_dict["id"]),
            question=question,
            state=state,
            papers=papers,
            summary=summary,
            report=report,
            notes=notes,
            state_history=state_history,
            last_error=last_error,
            last_error_at=last_error_at,
            last_known_state=last_known_state,
            created_at=created_at,
            updated_at=updated_at,
            metadata=metadata,
        )
        # ``published_report`` is set after construction
        # because it's an optional slot that bypasses the
        # constructor (matches the pattern used by
        # ``set_report`` for the analogous ``report`` field).
        if published_report is not None:
            workspace.set_published_report(published_report)
        return workspace

    # ------------------------------------------------------------------
    # Field-level deserialization
    # ------------------------------------------------------------------

    @staticmethod
    def _deserialize_papers(papers_json: Optional[str]) -> List[Paper]:
        if not papers_json or papers_json == "[]":
            return []
        paper_data = json.loads(papers_json)
        papers: List[Paper] = []
        for p in paper_data:
            authors = [
                Author(
                    first_name=a["first_name"],
                    last_name=a["last_name"],
                    affiliation=a.get("affiliation"),
                )
                for a in p.get("authors", [])
            ]
            journal = None
            if p.get("journal"):
                journal = Journal(
                    name=p["journal"]["name"],
                    issn=p["journal"].get("issn"),
                    publisher=p["journal"].get("publisher"),
                )
            paper = Paper(
                title=p["title"],
                authors=authors,
                journal=journal,
                year=p.get("year"),
                abstract=p.get("abstract", ""),
                doi=p.get("doi"),
                pmid=p.get("pmid"),
                keywords=p.get("keywords", []),
                url=p.get("url"),
            )
            papers.append(paper)
        return papers

    def _deserialize_summary(self, summary_json: str) -> Optional[Summary]:
        if not summary_json or summary_json == "null":
            return None
        data = json.loads(summary_json)
        papers_used = self._deserialize_papers(
            json.dumps(data.get("papers_used", []))
        )
        # Forward-compatibility: accept the new ``body`` key, fall
        # back to the legacy ``text`` key if ``body`` is absent.
        # Existing workspaces (created before the field rename)
        # have ``text``; new workspaces write ``body``. We log a
        # warning the first time we see the legacy shape so the
        # operator knows the migration hasn't run yet (or that
        # the migration helper should be invoked).
        if "body" in data:
            body_value = data["body"]
        elif "text" in data:
            logger.warning(
                "workspace_repository: loading Summary with legacy "
                "'text' key -- this shape was renamed to 'body' "
                "in the v6 schema migration. The legacy "
                "deserializer still works for backwards "
                "compatibility, but the v6 data migration "
                "(_migrate_v6_data) should be re-run by "
                "instantiating the repository to normalise "
                "the on-disk data."
            )
            body_value = data["text"]
        else:
            raise KeyError(
                "Summary JSON contains neither 'body' nor legacy "
                "'text' key. The on-disk shape is unrecognised."
            )
        return Summary(
            body=body_value,
            papers_used=papers_used,
        )

    def _deserialize_report(self, report_json: str) -> Optional[ResearchReport]:
        if not report_json or report_json == "null":
            return None
        data = json.loads(report_json)
        summary = None
        if data.get("summary"):
            summary = self._deserialize_summary(data["summary"])
        citations: List[Citation] = []
        for cit in data.get("citations", []):
            paper_dict = cit["paper"]
            authors = [
                Author(
                    first_name=a["first_name"],
                    last_name=a["last_name"],
                    affiliation=a.get("affiliation"),
                )
                for a in paper_dict.get("authors", [])
            ]
            journal = None
            if paper_dict.get("journal"):
                journal = Journal(
                    name=paper_dict["journal"]["name"],
                    issn=paper_dict["journal"].get("issn"),
                    publisher=paper_dict["journal"].get("publisher"),
                )
            paper = Paper(
                title=paper_dict["title"],
                authors=authors,
                journal=journal,
                year=paper_dict.get("year"),
                abstract=paper_dict.get("abstract", ""),
                doi=paper_dict.get("doi"),
                pmid=paper_dict.get("pmid"),
                keywords=paper_dict.get("keywords", []),
                url=paper_dict.get("url"),
            )
            style = CitationStyleEnum(cit.get("style", "APA"))
            citations.append(Citation(paper=paper, style=style))

        return ResearchReport(
            summary=summary,
            citations=citations,
            limitations=data.get("limitations", []),
            future_work=data.get("future_work", []),
            metadata=data.get("metadata", {}),
        )

    def _deserialize_state_history(
        self,
        history_json: Optional[str],
        current_state: WorkspaceState,
    ) -> List[StateTransition]:
        if not history_json:
            return [
                StateTransition(
                    from_state=WorkspaceState.INITIAL,
                    to_state=current_state,
                    action=None,
                )
            ]
        raw = json.loads(history_json)
        history: List[StateTransition] = []
        for entry in raw:
            try:
                from_state = WorkspaceState(entry["from_state"])
                to_state = WorkspaceState(entry["to_state"])
            except (KeyError, ValueError):
                continue
            action = None
            if entry.get("action"):
                try:
                    action = WorkspaceAction(entry["action"])
                except ValueError:
                    action = None
            at = (
                datetime.fromisoformat(entry["at"])
                if entry.get("at")
                else datetime.now()
            )
            history.append(
                StateTransition(
                    from_state=from_state,
                    to_state=to_state,
                    action=action,
                    at=at,
                    reason=entry.get("reason"),
                )
            )
        if not history:
            return [
                StateTransition(
                    from_state=WorkspaceState.INITIAL,
                    to_state=current_state,
                    action=None,
                )
            ]
        return history

    # ------------------------------------------------------------------
    # State inference for legacy rows
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_state(
        row_dict: Dict[str, Any],
        papers: List[Paper],
        summary: Optional[Summary],
        report: Optional[ResearchReport],
    ) -> WorkspaceState:
        """
        Compute the FSM state for a row that may have been written
        before the FSM was introduced.

        The mapping is purely additive — existing rows are
        "elevated" to the most advanced state their data supports
        so the FSM stays consistent with the user's actual progress.
        """
        raw_state = row_dict.get("state")
        if raw_state:
            try:
                return WorkspaceState(raw_state)
            except ValueError:
                pass
        if report is not None:
            return WorkspaceState.FINAL
        if summary is not None:
            return WorkspaceState.INTERMEDIATE
        if papers:
            return WorkspaceState.INTERMEDIATE
        return WorkspaceState.INITIAL
