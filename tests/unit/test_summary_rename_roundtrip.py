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
     (``_migrate_legacy_summaries``) runs at repository
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
