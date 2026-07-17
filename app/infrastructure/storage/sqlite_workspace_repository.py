"""
sqlite_workspace_repository.py

SQLite implementation of the workspace repository.

Purpose
-------
Provides persistent storage for Research Workspaces using the built‑in
sqlite3 module. This repository replaces the in‑memory version for
development and production use, ensuring workspaces survive server restarts.

The repository handles:

- database initialization (table creation);
- saving (create/update) and retrieving ResearchSession entities;
- serialization of domain entities to/from database rows;
- deletion, existence checks, and listing.

All methods respect the WorkspaceRepository interface and raise
ValueError when expected entities are not found.

Architecture
------------

    WorkspaceRepository (interface)
                │
                ▼
    SqliteWorkspaceRepository
                │
                ▼
          SQLite database

Author
------
Guillermo Ramajo Fernández
"""

import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.research_session import ResearchSession
from app.domain.entities.summary import Summary
from app.domain.interfaces.workspace_repository import WorkspaceRepository


class SqliteWorkspaceRepository(WorkspaceRepository):
    """
    SQLite-based repository for Research Workspaces.

    Attributes
    ----------
    db_path : str
        Path to the SQLite database file. Defaults to 'bioresearch.db'
        in the current working directory.
    """

    def __init__(self, db_path: str = "bioresearch.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """
        Create the workspaces table if it does not already exist.

        The table stores all fields of ResearchSession as serialized JSON
        or simple types. This design allows schema evolution without
        altering the table structure.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    papers TEXT,          -- JSON array of Paper objects
                    summary TEXT,         -- JSON object (Summary) or NULL
                    report TEXT,          -- JSON object (ResearchReport) or NULL
                    notes TEXT,           -- JSON array of strings
                    metadata TEXT,        -- JSON object (dict[str, str])
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    # ----------------------------------------------------------------------
    # Repository interface implementation
    # ----------------------------------------------------------------------

    def create(self, workspace: ResearchSession) -> ResearchSession:
        """
        Persist a newly created research workspace.

        Parameters
        ----------
        workspace
            Research session aggregate to persist.

        Returns
        -------
        ResearchSession
            Persisted research session (same object).

        Raises
        ------
        ValueError
            If a workspace with the same ID already exists.
        """
        if self.exists(workspace.id):
            raise ValueError(f"Workspace '{workspace.id}' already exists.")
        return self._save(workspace)

    def get(self, workspace_id: UUID) -> ResearchSession:
        """
        Retrieve a research workspace by identifier.

        Parameters
        ----------
        workspace_id
            Unique UUID identifying the research session.

        Returns
        -------
        ResearchSession
            Retrieved research session.

        Raises
        ------
        ValueError
            If no workspace exists with the supplied identifier.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workspaces WHERE id = ?", (str(workspace_id),))
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Workspace '{workspace_id}' was not found.")
            return self._row_to_workspace(row)

    def update(self, workspace: ResearchSession) -> ResearchSession:
        """
        Persist modifications made to an existing workspace.

        Parameters
        ----------
        workspace
            Research session containing updated state.

        Returns
        -------
        ResearchSession
            Updated persisted research session.

        Raises
        ------
        ValueError
            If no workspace exists with the supplied identifier.
        """
        if not self.exists(workspace.id):
            raise ValueError(f"Workspace '{workspace.id}' not found for update.")
        return self._save(workspace)

    def delete(self, workspace_id: UUID) -> None:
        """
        Remove a research workspace.

        Parameters
        ----------
        workspace_id
            Unique UUID identifying the workspace to remove.

        Raises
        ------
        ValueError
            If no workspace exists with the supplied identifier.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM workspaces WHERE id = ?", (str(workspace_id),))
            if cursor.rowcount == 0:
                raise ValueError(f"Workspace '{workspace_id}' not found for deletion.")
            conn.commit()

    def exists(self, workspace_id: UUID) -> bool:
        """
        Determine whether a research workspace exists.

        Parameters
        ----------
        workspace_id
            Unique UUID identifying the workspace.

        Returns
        -------
        bool
            True if the workspace exists, otherwise False.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM workspaces WHERE id = ?", (str(workspace_id),))
            return cursor.fetchone() is not None

    def list_workspaces(self) -> List[ResearchSession]:
        """
        Retrieve all stored research workspaces.

        Returns
        -------
        list[ResearchSession]
            Collection of available research sessions.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workspaces")
            rows = cursor.fetchall()
            return [self._row_to_workspace(row) for row in rows]

    # ----------------------------------------------------------------------
    # Internal serialisation helpers
    # ----------------------------------------------------------------------

    def _save(self, workspace: ResearchSession) -> ResearchSession:
        """
        Internal method to insert or replace a workspace row.

        This method is called by both create() and update().

        Parameters
        ----------
        workspace
            Research session to persist.

        Returns
        -------
        ResearchSession
            The same workspace object (for chaining).
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO workspaces (
                    id, question, papers, summary, report, notes,
                    metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(workspace.id),
                workspace.question.question,
                self._serialize_papers(workspace.papers),
                self._serialize_summary(workspace.summary),
                self._serialize_report(workspace.report),
                json.dumps(workspace.notes) if workspace.notes else "[]",
                json.dumps(workspace.metadata) if workspace.metadata else "{}",
                workspace.created_at.isoformat(),
                workspace.updated_at.isoformat(),
            ))
            conn.commit()
        return workspace

    # ----------------------------------------------------------------------
    # Serialisation methods
    # ----------------------------------------------------------------------

    def _serialize_papers(self, papers: List[Paper]) -> str:
        """
        Convert a list of Paper entities to a JSON string.
        """
        if not papers:
            return "[]"
        paper_dicts = []
        for paper in papers:
            paper_dicts.append(self._paper_to_dict(paper))
        return json.dumps(paper_dicts)


    @staticmethod
    def _paper_to_dict(paper: Paper) -> Dict[str, Any]:
        """
        Convert a single Paper entity to a dictionary.
        """
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
        """
        Convert a Summary entity to a JSON string, or 'null' if None.
        """
        if summary is None:
            return "null"
        return json.dumps({
            "text": summary.text,
            "confidence": summary.confidence,
            "papers_used": [self._paper_to_dict(p) for p in summary.papers_used],
        })

    def _serialize_report(self, report: Optional[ResearchReport]) -> str:
        """
        Convert a ResearchReport entity to a JSON string, or 'null' if None.
        """
        if report is None:
            return "null"
        return json.dumps({
            "summary": self._serialize_summary(report.summary),  # nested summary
            "citations": [
                {
                    "paper": self._paper_to_dict(citation.paper),
                    "style": citation.style.value,
                }
                for citation in report.citations
            ],
            "limitations": report.limitations,
            "future_work": report.future_work,
            "confidence": report.confidence,
            "metadata": report.metadata,
        })

    # ----------------------------------------------------------------------
    # Deserialisation methods
    # ----------------------------------------------------------------------

    def _row_to_workspace(self, row: tuple) -> ResearchSession:
        """
        Convert a database row back to a ResearchSession entity.

        Parameters
        ----------
        row
            A tuple from a SELECT * query.

        Returns
        -------
        ResearchSession
            Reconstructed domain entity.
        """
        (
            id_str,
            question_str,
            papers_json,
            summary_json,
            report_json,
            notes_json,
            metadata_json,
            created_at_str,
            updated_at_str,
        ) = row

        # Reconstruct question
        question = ResearchQuestion(question_str)

        # Reconstruct papers
        papers = self._deserialize_papers(papers_json)

        # Reconstruct summary
        summary = self._deserialize_summary(summary_json) if summary_json and summary_json != "null" else None

        # Reconstruct report
        report = self._deserialize_report(report_json) if report_json and report_json != "null" else None

        # Reconstruct notes
        notes = json.loads(notes_json) if notes_json else []

        # Reconstruct metadata
        metadata = json.loads(metadata_json) if metadata_json else {}

        # Reconstruct timestamps
        created_at = datetime.fromisoformat(created_at_str)
        updated_at = datetime.fromisoformat(updated_at_str)

        # Build the ResearchSession
        workspace = ResearchSession(
            id=UUID(id_str),
            question=question,
            papers=papers,
            summary=summary,
            report=report,
            notes=notes,
            created_at=created_at,
            updated_at=updated_at,
            metadata=metadata,
        )
        return workspace

    @staticmethod
    def _deserialize_papers(papers_json: str) -> List[Paper]:
        """
        Convert a JSON array of paper dictionaries back to a list of Paper entities.
        """
        if not papers_json or papers_json == "[]":
            return []
        paper_data = json.loads(papers_json)
        papers = []
        for p in paper_data:
            # Reconstruct Author objects
            authors = [
                Author(
                    first_name=a["first_name"],
                    last_name=a["last_name"],
                    affiliation=a.get("affiliation"),
                )
                for a in p.get("authors", [])
            ]
            # Reconstruct Journal
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
        """
        Convert a JSON summary object back to a Summary entity.
        """
        data = json.loads(summary_json)
        papers_used = self._deserialize_papers(json.dumps(data.get("papers_used", [])))
        return Summary(
            text=data["text"],
            confidence=data.get("confidence"),
            papers_used=papers_used,
        )

    def _deserialize_report(self, report_json: str) -> Optional[ResearchReport]:
        """
        Convert a JSON report object back to a ResearchReport entity.
        """
        data = json.loads(report_json)
        # Reconstruct summary
        summary = None
        if data.get("summary"):
            summary = self._deserialize_summary(data["summary"])
        # Reconstruct citations
        from app.core.enums.citation_style import CitationStyleEnum
        from app.domain.entities.citation import Citation

        citations = []
        for cit in data.get("citations", []):
            paper_dict = cit["paper"]
            # Reconstruct the paper object (simplified)
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
            style = CitationStyleEnum(cit.get("style", "apa").lower())
            citations.append(Citation(paper=paper, style=style))

        return ResearchReport(
            summary=summary,  # type: ignore
            citations=citations,
            limitations=data.get("limitations", []),
            future_work=data.get("future_work", []),
            confidence=data.get("confidence"),
            metadata=data.get("metadata", {}),
        )