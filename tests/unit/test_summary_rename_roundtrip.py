"""
tests/unit/test_summary_rename_roundtrip.py

Round-trip tests for the Summary ``text`` -> ``body`` rename refactor.

Background
----------
The ``Summary`` domain entity's primary field was renamed
``text`` -> ``body`` because the value actually contains the
LLM's full report body (with inline ``[paper:N]`` citation
markers), not a short text snippet. The previous name was
misleading.

This refactor affects:

  - Domain entity: ``Summary.text`` -> ``Summary.body``
  - SQLite storage: column value is now
    ``{"body": "...", "papers_used": [...]}`` instead of
    ``{"text": "...", "papers_used": [...]}``
  - In-memory shape: same as on-disk

Migration
---------
Existing workspaces stored before the rename have the legacy
``text`` key. Backwards compatibility is handled by:

  1. The deserializer accepts BOTH ``body`` and ``text`` keys
     and logs a warning when the legacy shape is loaded.

  2. A one-shot migration helper
     (``_migrate_v6_data``) runs at repository
     instantiation and rewrites the on-disk JSON in place.

  3. The migration helper handles three on-disk shapes:
     a. Standalone Summary JSON (the ``summary`` column).
     b. Nested Summary as a dict (newer ``report`` shape).
     c. Nested Summary as a stringified JSON blob (legacy
        ``report`` shape -- the legacy serializer produced a
        double-encoded JSON).

This file covers all three shapes plus the deserializer
warning path.

Test database
-------------
The tests use a fresh on-disk SQLite database in a temp
directory so they don't touch the project's live
``bioresearch.db``. Each test gets its own DB file via
the ``tmp_path`` pytest fixture.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.summary import Summary
from app.infrastructure.storage.sqlite_workspace_repository import (
    SqliteWorkspaceRepository,
    _rewrite_legacy_summary_in_blob,
)


def _paper(title: str = "Paper") -> Paper:
    return Paper(
        title=title,
        authors=[Author(first_name="A", last_name="B")],
        journal=Journal(name="J"),
        year=2026,
        abstract="abstract",
    )


def _seed_legacy_summary(db_path: str) -> None:
    """Write a workspace row whose ``summary`` column uses the
    legacy ``{"text": ...}`` shape, mimicking what a workspace
    created BEFORE the rename would look like on disk.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO workspaces (
            id, question, papers, state, created_at,
            updated_at, summary, report, state_history
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ws-legacy-1",
            "test?",
            json.dumps(
                [
                    {
                        "title": "Paper",
                        "authors": [
                            {
                                "first_name": "A",
                                "last_name": "B",
                                "affiliation": None,
                            }
                        ],
                        "journal": {"name": "J", "issn": None, "publisher": None},
                        "year": 2026,
                        "abstract": "abstract",
                        "doi": None,
                        "pmid": None,
                        "keywords": [],
                        "url": None,
                    }
                ]
            ),
            "REPORTED",
            "2026-08-28T00:00:00+00:00",
            "2026-08-28T00:00:00+00:00",
            json.dumps({"text": "legacy synthesis body", "papers_used": []}),
            "null",
            "[]",
        ),
    )
    conn.commit()
    conn.close()


def _seed_legacy_report_with_stringified_summary(db_path: str) -> None:
    """Write a workspace row whose ``report`` column contains a
    ResearchReport with a stringified (double-encoded) Summary
    blob using the legacy ``text`` key.

    This is the actual on-disk shape produced by the legacy
    ``_serialize_report`` method: it called
    ``json.dumps(report.summary)`` to serialise the inner
    Summary, then ``json.dumps`` again for the outer envelope,
    producing a double-encoded shape.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    legacy_inner = json.dumps({"text": "legacy report body", "papers_used": []})
    report_blob = json.dumps(
        {
            "summary": legacy_inner,
            "citations": [],
            "limitations": [],
            "future_work": [],
            "metadata": {},
        }
    )
    cursor.execute(
        """
        INSERT INTO workspaces (
            id, question, papers, state, created_at,
            updated_at, summary, report, state_history
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ws-legacy-report-1",
            "test?",
            json.dumps(
                [
                    {
                        "title": "Paper",
                        "authors": [
                            {
                                "first_name": "A",
                                "last_name": "B",
                                "affiliation": None,
                            }
                        ],
                        "journal": {"name": "J", "issn": None, "publisher": None},
                        "year": 2026,
                        "abstract": "abstract",
                        "doi": None,
                        "pmid": None,
                        "keywords": [],
                        "url": None,
                    }
                ]
            ),
            "REPORTED",
            "2026-08-28T00:00:00+00:00",
            "2026-08-28T00:00:00+00:00",
            "null",
            report_blob,
            "[]",
        ),
    )
    conn.commit()
    conn.close()


class TestSummaryEntityRename:
    """Pin the new field name on the domain entity."""

    def test_summary_constructor_uses_body_keyword(self):
        """Constructing a Summary with the new ``body=`` kwarg
        must work; the legacy ``text=`` must NOT.
        """
        s = Summary(body="the body", papers_used=[_paper()])
        assert s.body == "the body"
        assert s.papers_used == [_paper()]

    def test_summary_rejects_legacy_text_keyword(self):
        """Passing ``text=`` (the legacy kwarg) raises
        ``TypeError`` because the field has been removed. This
        guards against an accidental regression where someone
        re-adds ``text`` as an alias.
        """
        with pytest.raises(TypeError):
            Summary(text="legacy", papers_used=[])  # type: ignore[call-arg]


class TestLegacySummaryMigration:
    """Pin the migration helper rewrites all three on-disk
    shapes (standalone, nested dict, nested string)."""

    def test_rewrites_standalone_summary_blob(self):
        blob = {"text": "synthesis body", "papers_used": []}
        changed = _rewrite_legacy_summary_in_blob(blob)
        assert changed is True
        assert blob == {"body": "synthesis body", "papers_used": []}

    def test_rewrites_nested_dict_summary(self):
        blob = {
            "summary": {"text": "report body", "papers_used": []},
            "citations": [],
        }
        changed = _rewrite_legacy_summary_in_blob(blob)
        assert changed is True
        assert blob["summary"] == {"body": "report body", "papers_used": []}

    def test_rewrites_nested_stringified_summary(self):
        """The legacy ``_serialize_report`` double-encoded the
        Summary as a stringified JSON blob inside the report
        envelope. The helper must parse, rewrite, and
        re-serialise.
        """
        blob = {
            "summary": json.dumps({"text": "report body", "papers_used": []}),
            "citations": [],
        }
        changed = _rewrite_legacy_summary_in_blob(blob)
        assert changed is True
        # ``blob['summary']`` is now a (rewritten) string
        inner = json.loads(blob["summary"])
        assert "body" in inner
        assert "text" not in inner
        assert inner["body"] == "report body"

    def test_no_op_when_no_legacy_shape(self):
        """Already-migrated blobs return False (no rewrite)."""
        blob = {"body": "new shape", "papers_used": []}
        changed = _rewrite_legacy_summary_in_blob(blob)
        assert changed is False
        assert blob == {"body": "new shape", "papers_used": []}

    def test_idempotent_on_repeated_calls(self):
        """Calling the helper twice in a row is a no-op the
        second time -- once a row is in the new shape, the
        helper skips it.
        """
        blob = {"text": "first call", "papers_used": []}
        _rewrite_legacy_summary_in_blob(blob)
        second = _rewrite_legacy_summary_in_blob(blob)
        assert second is False
        assert blob == {"body": "first call", "papers_used": []}

    def test_unrelated_blob_passes_through(self):
        """Random data with no Summary shape is left alone."""
        blob = {"random_key": "value", "count": 42}
        changed = _rewrite_legacy_summary_in_blob(blob)
        assert changed is False
        assert blob == {"random_key": "value", "count": 42}

    def test_blob_with_null_summary_passes_through(self):
        """``report.summary`` is the JSON string ``\"null\"``
        when the report has no embedded summary. The helper
        must skip this case.
        """
        blob = {"summary": "null", "citations": []}
        changed = _rewrite_legacy_summary_in_blob(blob)
        assert changed is False


class TestRepositoryMigrationOnStartup:
    """Pin that the repository's ``__init__`` migrates legacy
    rows in place."""

    def test_legacy_summary_column_is_migrated(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        # Initialise the schema (creates empty workspaces table)
        SqliteWorkspaceRepository(db_path=db_path)
        # Now seed a legacy row, close, and re-instantiate
        # (this simulates a restart with a legacy DB).
        _seed_legacy_summary(db_path)

        # Re-instantiate -> __init__ -> migration runs.
        SqliteWorkspaceRepository(db_path=db_path)

        # Verify on-disk state: the legacy ``text`` key is
        # gone, the new ``body`` key is present.
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT summary FROM workspaces WHERE id = ?",
            ("ws-legacy-1",),
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        data = json.loads(row[0])
        assert "body" in data
        assert "text" not in data
        assert data["body"] == "legacy synthesis body"

    def test_legacy_stringified_report_summary_is_migrated(
        self, tmp_path
    ):
        """The legacy double-encoded shape in the ``report``
        column must be rewritten to the new shape on startup.
        """
        db_path = str(tmp_path / "test.db")
        SqliteWorkspaceRepository(db_path=db_path)
        _seed_legacy_report_with_stringified_summary(db_path)

        SqliteWorkspaceRepository(db_path=db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT report FROM workspaces WHERE id = ?",
            ("ws-legacy-report-1",),
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        envelope = json.loads(row[0])
        # After migration, the inner string still encodes a
        # Summary, but with ``body`` not ``text``.
        inner = json.loads(envelope["summary"])
        assert "body" in inner
        assert "text" not in inner
        assert inner["body"] == "legacy report body"

    def test_migration_is_idempotent(self, tmp_path):
        """Calling the migration twice in a row (via two
        repository instantiations) must be a no-op the second
        time -- no rows get rewritten.
        """
        db_path = str(tmp_path / "test.db")
        SqliteWorkspaceRepository(db_path=db_path)
        _seed_legacy_summary(db_path)

        SqliteWorkspaceRepository(db_path=db_path)
        # Second instantiation -- migration runs but finds
        # nothing to do.
        SqliteWorkspaceRepository(db_path=db_path)

        # Verify the row is still in the new shape.
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT summary FROM workspaces WHERE id = ?",
            ("ws-legacy-1",),
        )
        row = cursor.fetchone()
        conn.close()
        data = json.loads(row[0])
        assert "body" in data
        assert "text" not in data


class TestLegacyDeserializerWarning:
    """Pin the warning emitted when the legacy shape is loaded."""

    def test_warning_when_loading_legacy_shape(
        self, tmp_path, caplog
    ):
        """If the migration helper fails for any reason (e.g.
        a row is added AFTER the migration ran), the legacy
        deserializer should still load the data and emit a
        warning so the operator sees the data-quality issue.
        """
        db_path = str(tmp_path / "test.db")
        repo = SqliteWorkspaceRepository(db_path=db_path)

        # Inject a legacy row AFTER the migration has run, so
        # the migration helper won't catch it.
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO workspaces (
                id, question, papers, state, created_at,
                updated_at, summary, report, state_history
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ws-post-migration",
                "test?",
                json.dumps(
                    [
                        {
                            "title": "Paper",
                            "authors": [
                                {
                                    "first_name": "A",
                                    "last_name": "B",
                                    "affiliation": None,
                                }
                            ],
                            "journal": {
                                "name": "J",
                                "issn": None,
                                "publisher": None,
                            },
                            "year": 2026,
                            "abstract": "abstract",
                            "doi": None,
                            "pmid": None,
                            "keywords": [],
                            "url": None,
                        }
                    ]
                ),
                "REPORTED",
                "2026-08-28T00:00:00+00:00",
                "2026-08-28T00:00:00+00:00",
                json.dumps(
                    {"text": "post-migration legacy", "papers_used": []}
                ),
                "null",
                "[]",
            ),
        )
        conn.commit()
        conn.close()

        # Trigger a load -- the deserializer should emit the
        # warning AND still return a valid Summary object.
        with caplog.at_level(
            logging.WARNING,
            logger="app.infrastructure.storage.sqlite_workspace_repository",
        ):
            summary = repo._deserialize_summary(
                json.dumps(
                    {"text": "post-migration legacy", "papers_used": []}
                )
            )

        assert summary is not None
        assert summary.body == "post-migration legacy"
        assert any(
            "legacy" in record.message for record in caplog.records
        ), (
            "deserializer should emit a warning when loading the "
            "legacy 'text' shape"
        )
class TestRepositoryV6SchemaMigration:
    """Pin the contract that the v6 schema bump formalises the
    Summary ``text`` -> ``body`` data migration.

    The schema-version mechanism (``PRAGMA user_version``,
    ``LATEST_SCHEMA_VERSION = 6``) was previously used only
    for additive ``ALTER TABLE`` migrations (v2-v5). The v6
    bump extends it to cover the Summary rename, so:

      1. The schema version integer reflects BOTH the column
         state AND the on-disk JSON shape.
      2. A future operator looking at ``PRAGMA user_version``
         can tell whether the data migration has run.
      3. A future schema change follows the same template:
         add a v(N+1) ``_V(N+1)_DATA_MIGRATION`` (or
         ``_V(N+1)_COLUMNS``) tuple, bump ``LATEST_SCHEMA_VERSION``,
         and add a step to ``_migrate``.
    """

    def test_latest_schema_version_is_six(self):
        """Pin the schema-version integer. A future bump to 7
        must update both this constant and the migration
        block; this test fails if either is forgotten.
        """
        from app.infrastructure.storage.sqlite_workspace_repository import (
            LATEST_SCHEMA_VERSION,
        )
        assert LATEST_SCHEMA_VERSION == 8

    def test_fresh_database_has_user_version_six(self, tmp_path):
        """A brand-new database (no legacy rows) should have
        ``PRAGMA user_version = 8`` after the repository is
        instantiated. The migration walks zero rows but still
        bumps the version pragma via the v6 data step.
        """
        db_path = str(tmp_path / "fresh.db")
        SqliteWorkspaceRepository(db_path=db_path)
        conn = sqlite3.connect(db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert version == 8

    def test_v5_database_with_legacy_rows_upgrades_to_v6(
        self, tmp_path
    ):
        """End-to-end v5 -> v6: a v5-shape database (legacy
        ``text`` rows, no user_version bump above 5) gets
        the column additions skipped (already present) but
        the v6 data migration still runs and rewrites the
        rows.

        This is the integration test that pins the new
        schema-version flow end to end -- no v6 migration
        would silently no-op if this test broke.
        """
        db_path = str(tmp_path / "v5_legacy.db")
        # Step 1: create a v5-shape database with legacy
        # ``text`` rows. We bypass the live repository's
        # __init__ to simulate a database that was created
        # before the v6 bump was deployed.
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        v5_create = """
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
                published_report TEXT,
                last_error TEXT,
                last_error_at TEXT
            )
        """
        cursor.execute(v5_create)
        cursor.execute(
            """
            INSERT INTO workspaces (id, question, papers, state,
                created_at, updated_at, summary, report, state_history)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ws-v5-legacy-1",
                "v5 test?",
                _serialize_papers_for_migration(),
                "REPORTED",
                "2026-08-28T00:00:00+00:00",
                "2026-08-28T00:00:00+00:00",
                json.dumps({"text": "v5 legacy body", "papers_used": []}),
                "null",
                "[]",
            ),
        )
        conn.commit()
        conn.close()

        # Step 2: instantiate the repository. __init__ runs
        # _migrate (no-op for v5-schema columns that already
        # exist) and then _migrate_v6_data, which walks every
        # row and rewrites legacy "text" -> "body".
        SqliteWorkspaceRepository(db_path=db_path)

        # Step 3: verify the on-disk shape and the version
        # pragma.
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        version = cursor.execute("PRAGMA user_version").fetchone()[0]
        cursor.execute(
            "SELECT summary FROM workspaces WHERE id = ?",
            ("ws-v5-legacy-1",),
        )
        row = cursor.fetchone()
        conn.close()
        assert version == 8
        assert row is not None
        data = json.loads(row[0])
        assert "body" in data
        assert "text" not in data
        assert data["body"] == "v5 legacy body"

    def test_v6_migration_is_idempotent(self, tmp_path):
        """A v6-shape database (already migrated) instantiates
        cleanly without re-rewriting anything. The helper
        returns False for already-migrated rows so the
        migration loop is a no-op.
        """
        db_path = str(tmp_path / "v6.db")
        # First instantiation: runs the v6 data migration.
        repo1 = SqliteWorkspaceRepository(db_path=db_path)
        # Confirm the on-disk shape is canonical.
        _seed_v6_row(db_path)
        # Second instantiation: must NOT see anything to
        # migrate (the helper is idempotent).
        repo2 = SqliteWorkspaceRepository(db_path=db_path)
        assert repo1 is not repo2  # different instances
        # Verify the row is still in v6 shape and the
        # version pragma is still 6.
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        version = cursor.execute("PRAGMA user_version").fetchone()[0]
        cursor.execute(
            "SELECT summary FROM workspaces WHERE id = ?",
            ("ws-v6-canonical",),
        )
        row = cursor.fetchone()
        conn.close()
        assert version == 8
        data = json.loads(row[0])
        assert "body" in data
        assert "text" not in data

    def test_v8_version_constant_module_attribute(self):
        """The version constant must be importable as a
        module attribute (not a class attribute) so other
        modules can read it without instantiating the
        repository. This was the convention for v2-v5 and
        v6 follows it.
        """
        from app.infrastructure.storage import (
            sqlite_workspace_repository,
        )
        assert hasattr(sqlite_workspace_repository, "LATEST_SCHEMA_VERSION")
        assert sqlite_workspace_repository.LATEST_SCHEMA_VERSION == 8


def _serialize_papers_for_migration() -> str:
    """Minimal papers JSON for seeding test rows."""
    return json.dumps(
        [
            {
                "title": "Paper",
                "authors": [{"first_name": "A", "last_name": "B", "affiliation": None}],
                "journal": {"name": "J", "issn": None, "publisher": None},
                "year": 2026,
                "abstract": "abstract",
                "doi": None,
                "pmid": None,
                "keywords": [],
                "url": None,
            }
        ]
    )


def _seed_v6_row(db_path: str) -> None:
    """Seed a v6-shape (canonical) row directly into the DB."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO workspaces (id, question, papers, state,
            created_at, updated_at, summary, report, state_history)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ws-v6-canonical",
            "v6 test?",
            _serialize_papers_for_migration(),
            "REPORTED",
            "2026-08-28T00:00:00+00:00",
            "2026-08-28T00:00:00+00:00",
            json.dumps({"body": "v6 canonical body", "papers_used": []}),
            "null",
            "[]",
        ),
    )
    conn.commit()
    conn.close()


class TestRepositoryV8StateElevation:
    """Pin the contract that the v8 migration rewrites every
    legacy ``state`` string to its ADR-017 equivalent.

    The v8 schema bump (added 2026-08-31 alongside the FSM
    collapse from nine states to four) introduced the
    ``last_known_state`` column AND a one-shot SQL
    ``UPDATE`` that rewrites pre-v8 ``state`` values. Without
    that data migration the ``/admin/orchestrator-stats``
    endpoint would expose a mix of legacy and new state
    names in its response, breaking the smoke-test contract.

    The migration is **idempotent** -- running it twice is a
    no-op because the WHERE clause only matches legacy state
    strings, not the four new ones.
    """

    def test_v8_state_elevation_rewrites_legacy_states(self, tmp_path):
        """A pre-v8 database with the full legacy FSM enum set
        is migrated to the four new values in one instantiation.
        """
        db_path = str(tmp_path / "v7.db")
        # Step 1: create a v7-schema database and seed every
        # legacy state (including ERROR, which is still valid
        # under v8). We use ``SELECT DISTINCT state`` to
        # confirm the migration didn't drop or duplicate rows.
        conn = sqlite3.connect(db_path)
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
                last_error TEXT,
                last_error_at TEXT
            )
        """
        )
        cursor.execute("PRAGMA user_version = 7")
        legacy_states = [
            "CREATED",
            "SEARCHING",
            "PAPERS_RETRIEVED",
            "SUMMARIZING",
            "SUMMARIZED",
            "COMPARING",
            "COMPARED",
            "REPORTING",
            "REPORTED",
            "PUBLISHING",
            "COMPLETED",
            "ERROR",
        ]
        for i, legacy_state in enumerate(legacy_states):
            cursor.execute(
                "INSERT INTO workspaces ("
                "id, question, papers, summary, report, notes, "
                "metadata, created_at, updated_at, state, "
                "state_history, published_report, last_error, "
                "last_error_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"ws-{i:03d}",
                    "q",
                    "[]",
                    "null",
                    "null",
                    "null",
                    "{}",
                    "2026-08-28T00:00:00+00:00",
                    "2026-08-28T00:00:00+00:00",
                    legacy_state,
                    "[]",
                    "null",
                    "null",
                    "null",
                ),
            )
        conn.commit()
        conn.close()

        # Step 2: instantiate the repo. ``__init__`` runs the
        # v8 data migration (rewriting ``state``) AND the v7
        # schema migration (dropping ``evidence_comparison``)
        # AND the v8 schema migration (adding
        # ``last_known_state``). All three are idempotent.
        SqliteWorkspaceRepository(db_path=db_path)

        # Step 3: verify the data was rewritten and the
        # columns match the v8 schema.
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        version = cursor.execute("PRAGMA user_version").fetchone()[0]
        assert version == 8

        # No legacy state strings should remain. ERROR
        # survives because it's also a v8 state value.
        cursor.execute(
            "SELECT DISTINCT state FROM workspaces WHERE state IN ("
            "'CREATED', 'SEARCHING', 'PAPERS_RETRIEVED', 'SUMMARIZING', "
            "'SUMMARIZED', 'COMPARING', 'COMPARED', 'REPORTING', "
            "'REPORTED', 'PUBLISHING', 'COMPLETED'"
            ")"
        )
        leftover = cursor.fetchall()
        assert leftover == [], f"legacy states remain: {leftover}"

        # The four-state distribution must equal the count
        # of rows we seeded (12). CREATED + SEARCHING -> 2
        # INITIAL; PAPERS_RETRIEVED + SUMMARIZING +
        # SUMMARIZED + COMPARING + COMPARED + REPORTING -> 6
        # INTERMEDIATE; REPORTED + PUBLISHING + COMPLETED ->
        # 3 FINAL; ERROR -> 1 ERROR.
        cursor.execute(
            "SELECT state, COUNT(*) FROM workspaces GROUP BY state"
        )
        distribution = dict(cursor.fetchall())
        assert distribution == {
            "INITIAL": 2,
            "INTERMEDIATE": 6,
            "FINAL": 3,
            "ERROR": 1,
        }, distribution

        # The ``last_known_state`` column should exist (v8
        # schema migration).
        cursor.execute("PRAGMA table_info(workspaces)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "last_known_state" in cols
        # And ``evidence_comparison`` should be gone (v7
        # schema migration).
        assert "evidence_comparison" not in cols

        # And ``last_known_state`` should be NULL for every
        # row -- the upgrade path can't infer the pre-ERROR
        # state from the legacy enum value alone.
        cursor.execute(
            "SELECT COUNT(*) FROM workspaces WHERE last_known_state IS NOT NULL"
        )
        nonzero = cursor.fetchone()[0]
        assert nonzero == 0, (
            "last_known_state should be NULL for upgraded rows"
        )

        conn.close()

    def test_v8_state_elevation_is_idempotent(self, tmp_path):
        """Running the migration twice is a no-op. Already-v8
        databases skip the rewrite.
        """
        db_path = str(tmp_path / "v8-fresh.db")

        # First instantiation: fresh DB, no legacy states to
        # rewrite, migration is a no-op.
        repo1 = SqliteWorkspaceRepository(db_path=db_path)
        counts_before = repo1.workspace_state_counts()
        assert set(counts_before.keys()) == {
            "INITIAL",
            "INTERMEDIATE",
            "FINAL",
            "ERROR",
        }

        # Second instantiation: re-opens the same DB. The
        # UPDATE WHERE state IN (...) doesn't match any rows
        # (they're all in the new four-state set), so the
        # migration is again a no-op. Verify by re-reading
        # counts.
        repo2 = SqliteWorkspaceRepository(db_path=db_path)
        counts_after = repo2.workspace_state_counts()
        assert counts_after == counts_before
