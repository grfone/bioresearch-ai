"""
research_session.py

Domain entity representing a biomedical research session.

A ResearchSession is the central aggregate of the BioResearch AI domain.
It encapsulates the complete lifecycle of a scientific investigation,
from the initial research question to the generation of evidence
summaries and final reports.

Rather than treating literature search, summarization, and report
generation as isolated operations, the system models them as successive
steps that enrich a single research session.

This design naturally supports future capabilities such as:

- Multi-agent collaboration
- Human-in-the-loop review
- Research history
- Workspace persistence
- Exportable reports
- Knowledge graph integration
- MCP tool orchestration
- A2A communication
- Biological database enrichment

The ResearchSession intentionally contains no infrastructure-specific
logic. It does not know how papers are retrieved, how LLMs operate,
or how reports are rendered.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from uuid import UUID, uuid4

from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.summary import Summary


@dataclass(slots=True)
class ResearchSession:
    """
    Represents a complete biomedical research investigation.

    A ResearchSession serves as the aggregate root of the BioResearch AI
    domain model. Every artifact generated during the investigation
    belongs to this session.

    Typical lifecycle
    -----------------

        Create session
                │
                ▼
        Define research question
                │
                ▼
        Retrieve scientific papers
                │
                ▼
        Generate evidence summary
                │
                ▼
        Produce research report
                │
                ▼
           Export / Save / Share

    Attributes
    ----------
    id : UUID
        Unique identifier of the research session.

    question : ResearchQuestion
        Original scientific question posed by the researcher.

    papers : list[Paper]
        Scientific publications retrieved during literature search.

    summary : Summary | None
        Synthesized evidence generated from the retrieved papers.

    report : ResearchReport | None
        Final structured report generated from the evidence summary.

    notes : list[str]
        Optional researcher annotations.

    created_at : datetime
        Session creation timestamp (UTC).

    updated_at : datetime
        Timestamp of the latest modification (UTC).

    metadata : dict[str, str]
        Optional metadata describing execution details such as
        model version, search provider, workflow version, etc.

    Notes
    -----
    This entity intentionally remains independent of any presentation
    layer.

    It can therefore be rendered as:

    - Web workspace
    - REST API response
    - Markdown
    - PDF
    - Jupyter notebook
    - CLI output

    without requiring changes to the domain model.
    """

    question: ResearchQuestion

    id: UUID = field(default_factory=uuid4)

    papers: list[Paper] = field(default_factory=list)

    summary: Summary | None = None

    report: ResearchReport | None = None

    notes: list[str] = field(default_factory=list)

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def has_papers(self) -> bool:
        """
        Whether the session contains retrieved literature.

        Returns
        -------
        bool
            True if at least one paper has been retrieved.
        """
        return bool(self.papers)

    @property
    def has_summary(self) -> bool:
        """
        Whether an evidence summary has been generated.

        Returns
        -------
        bool
            True if a summary is available.
        """
        return self.summary is not None

    @property
    def has_report(self) -> bool:
        """
        Whether a final research report has been generated.

        Returns
        -------
        bool
            True if a report is available.
        """
        return self.report is not None

    def touch(self) -> None:
        """
        Update the session modification timestamp.

        This method should be invoked whenever the session is modified
        (e.g., after retrieving literature, generating summaries,
        adding notes, or producing reports).
        """
        self.updated_at = datetime.now(UTC)

    def add_papers(self, papers: list[Paper]) -> None:
        """
        Add retrieved scientific publications to the session.

        Parameters
        ----------
        papers : list[Paper]
            Publications retrieved during literature search.
        """
        self.papers.extend(papers)
        self.touch()

    def set_summary(self, summary: Summary) -> None:
        """
        Store the synthesized evidence for this session.

        Parameters
        ----------
        summary : Summary
            AI-generated synthesis of the retrieved literature.
        """
        self.summary = summary
        self.touch()

    def set_report(self, report: ResearchReport) -> None:
        """
        Store the final research report.

        Parameters
        ----------
        report : ResearchReport
            Structured biomedical research report.
        """
        self.report = report
        self.touch()

    def add_note(self, note: str) -> None:
        """
        Append a researcher annotation to the session.

        Parameters
        ----------
        note : str
            Free-text note recorded during the investigation.
        """
        if note.strip():
            self.notes.append(note)
            self.touch()