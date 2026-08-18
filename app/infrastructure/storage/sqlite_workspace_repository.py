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
The schema introduced by the FSM refactor adds four columns:

- ``state``: the FSM state of the workspace (text).
- ``state_history``: ordered list of state transitions (JSON).
- ``evidence_comparison``: serialised EvidenceComparison (JSON).
- ``evidence_matrix``: serialised EvidenceMatrix (JSON).

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
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.enums.workspace_state import WorkspaceState
from app.core.enums.citation_style import CitationStyleEnum
from app.domain.entities.evidence_comparison import EvidenceComparison
from app.domain.entities.evidence_matrix import EvidenceMatrix, MatrixCell
from app.domain.entities.finding import Contradiction, Finding
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


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

LATEST_SCHEMA_VERSION = 2


# Columns that were added in each schema version. The repository
# performs an additive migration on initialisation to bring older
# databases up to the latest schema.
_V2_COLUMNS = (
    ("state", "TEXT NOT NULL DEFAULT 'CREATED'"),
    ("state_history", "TEXT"),
    ("evidence_comparison", "TEXT"),
)


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
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """
        Create the workspaces table if it does not already exist and
        apply any pending additive migrations.

        The migration is idempotent: running it on a fresh database
        creates the latest schema; running it on an existing
        database only adds the columns that are missing.
        """
        with sqlite3.connect(self.db_path) as conn:
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
                    updated_at TEXT NOT NULL
                )
                """
            )

            # Apply additive migrations.
            self._migrate(cursor)

            conn.commit()

    def _migrate(self, cursor: sqlite3.Cursor) -> None:
        """Apply pending schema migrations idempotently."""
        cursor.execute("PRAGMA user_version")
        current = cursor.fetchone()[0]
        if current >= LATEST_SCHEMA_VERSION:
            return

        # v2: FSM additions.
        existing = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(workspaces)").fetchall()
        }
        for column_name, column_def in _V2_COLUMNS:
            if column_name not in existing:
                cursor.execute(
                    f"ALTER TABLE workspaces ADD COLUMN {column_name} {column_def}"
                )

        # Bump the schema version.
        cursor.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION}")

    # ------------------------------------------------------------------
    # Repository interface
    # ------------------------------------------------------------------

    def create(self, workspace: ResearchSession) -> ResearchSession:
        if self.exists(workspace.id):
            raise ValueError(f"Workspace '{workspace.id}' already exists.")
        return self._save(workspace)

    def get(self, workspace_id: UUID) -> ResearchSession:
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM workspaces WHERE id = ?",
                (str(workspace_id),),
            )
            return cursor.fetchone() is not None

    def list_workspaces(self) -> List[ResearchSession]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workspaces")
            rows = cursor.fetchall()
            return [self._row_to_workspace(row) for row in rows]

    def workspace_state_counts(self) -> dict[str, int]:
        """Count workspaces per FSM state, zero-filling every state.

        Uses SQL ``GROUP BY state`` for efficiency -- one
        pass over the table instead of fetching every row.
        """
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO workspaces (
                    id, question, papers, summary, report, notes,
                    metadata, created_at, updated_at,
                    state, state_history, evidence_comparison
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    self._serialize_evidence_comparison(workspace.evidence_comparison),
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
                "text": summary.text,
                "confidence": summary.confidence,
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
                "confidence": report.confidence,
                "metadata": report.metadata,
            }
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

    def _serialize_evidence_comparison(
        self,
        comparison: Optional[EvidenceComparison],
    ) -> Optional[str]:
        if comparison is None:
            return "null"
        return json.dumps(
            {
                "consensus": [
                    {
                        "claim": f.claim,
                        "paper_ids": f.paper_ids,
                        "evidence_strength": f.evidence_strength,
                        "notes": f.notes,
                    }
                    for f in comparison.consensus
                ],
                "contradictions": [
                    {
                        "topic": c.topic,
                        "description": c.description,
                        "paper_ids": c.paper_ids,
                        "severity": c.severity,
                    }
                    for c in comparison.contradictions
                ],
                "research_gaps": comparison.research_gaps,
                "future_directions": comparison.future_directions,
                "used_paper_ids": comparison.used_paper_ids,
                "matrix": self._matrix_to_dict(comparison.matrix),
                "confidence": comparison.confidence,
                "metadata": comparison.metadata,
            }
        )

    def _serialize_evidence_matrix(
        self,
        matrix: Optional[EvidenceMatrix],
    ) -> Optional[str]:
        if matrix is None:
            return "null"
        return json.dumps(self._matrix_to_dict(matrix))

    @staticmethod
    def _matrix_to_dict(matrix: Optional[EvidenceMatrix]) -> Optional[Dict[str, Any]]:
        if matrix is None:
            return None
        return {
            "columns": matrix.columns,
            "rows": [
                {
                    "paper_id": cell.paper_id,
                    **cell.facets,
                }
                for cell in matrix.rows
            ],
            "used_paper_ids": matrix.used_paper_ids,
        }

    # ------------------------------------------------------------------
    # Deserialisation
    # ------------------------------------------------------------------

    def _row_to_workspace(self, row: tuple) -> ResearchSession:
        # Row column order:
        # 0 id, 1 question, 2 papers, 3 summary, 4 report, 5 notes,
        # 6 metadata, 7 created_at, 8 updated_at,
        # 9 state, 10 state_history, 11 evidence_comparison, 12 evidence_matrix
        row_dict = self._row_to_dict(row)
        return self._dict_to_workspace(row_dict)

    def _row_to_dict(self, row: tuple) -> Dict[str, Any]:
        # Some columns may be missing in older database files; pad
        # the row defensively so the deserialiser is forward
        # compatible.
        padded: list[Any] = list(row) + [None] * (13 - len(row))
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
            "evidence_comparison": padded[11],
            "evidence_matrix": padded[12],
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
        evidence_comparison = self._deserialize_evidence_comparison(
            row_dict.get("evidence_comparison"),
            row_dict.get("evidence_matrix"),
        )

        workspace = ResearchSession(
            id=UUID(row_dict["id"]),
            question=question,
            state=state,
            papers=papers,
            summary=summary,
            evidence_comparison=evidence_comparison,
            report=report,
            notes=notes,
            state_history=state_history,
            created_at=created_at,
            updated_at=updated_at,
            metadata=metadata,
        )
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
        return Summary(
            text=data["text"],
            confidence=data.get("confidence"),
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
            style = CitationStyleEnum(cit.get("style", "apa").lower())
            citations.append(Citation(paper=paper, style=style))

        return ResearchReport(
            summary=summary,
            citations=citations,
            limitations=data.get("limitations", []),
            future_work=data.get("future_work", []),
            confidence=data.get("confidence"),
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
                    from_state=WorkspaceState.CREATED,
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
                    from_state=WorkspaceState.CREATED,
                    to_state=current_state,
                    action=None,
                )
            ]
        return history

    def _deserialize_evidence_comparison(
        self,
        comparison_json: Optional[str],
        matrix_json: Optional[str],
    ) -> Optional[EvidenceComparison]:
        if not comparison_json or comparison_json == "null":
            return None
        data = json.loads(comparison_json)
        consensus = [
            Finding(
                claim=f["claim"],
                paper_ids=f.get("paper_ids", []),
                evidence_strength=f.get("evidence_strength"),
                notes=f.get("notes"),
            )
            for f in data.get("consensus", [])
        ]
        contradictions = [
            Contradiction(
                topic=c["topic"],
                description=c["description"],
                paper_ids=c.get("paper_ids", []),
                severity=c.get("severity"),
            )
            for c in data.get("contradictions", [])
        ]
        matrix = self._deserialize_matrix(
            data.get("matrix") if data.get("matrix") else matrix_json
        )
        return EvidenceComparison(
            consensus=consensus,
            contradictions=contradictions,
            research_gaps=data.get("research_gaps", []),
            future_directions=data.get("future_directions", []),
            used_paper_ids=data.get("used_paper_ids", []),
            matrix=matrix,
            confidence=data.get("confidence"),
            metadata=data.get("metadata", {}),
        )

    def _deserialize_matrix(
        self,
        matrix_payload: Optional[Any],
    ) -> Optional[EvidenceMatrix]:
        if not matrix_payload:
            return None
        if isinstance(matrix_payload, str):
            if matrix_payload == "null":
                return None
            matrix_payload = json.loads(matrix_payload)
        if not isinstance(matrix_payload, dict):
            return None
        columns = [str(c) for c in matrix_payload.get("columns", [])]
        rows: List[MatrixCell] = []
        for row in matrix_payload.get("rows", []):
            if not isinstance(row, dict):
                continue
            paper_id = str(
                row.get("paper_id") or row.get("pmid") or row.get("doi") or ""
            )
            if not paper_id:
                continue
            facets = {
                str(k): str(v)
                for k, v in row.items()
                if k not in {"paper_id", "pmid", "doi"} and v is not None
            }
            rows.append(MatrixCell(paper_id=paper_id, facets=facets))
        if not rows and not columns:
            return None
        return EvidenceMatrix(
            columns=columns,
            rows=rows,
            used_paper_ids=[cell.paper_id for cell in rows],
        )

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
            return WorkspaceState.REPORTED
        if summary is not None:
            return WorkspaceState.SUMMARIZED
        if papers:
            return WorkspaceState.PAPERS_RETRIEVED
        return WorkspaceState.CREATED
