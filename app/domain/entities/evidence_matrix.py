"""
evidence_matrix.py

Domain entity representing a side-by-side comparison of papers
organized as a table.

The matrix is the human-readable counterpart of the structured
:class:`EvidenceComparison`. While the comparison is optimised for
synthesis (consensus, contradictions, gaps), the matrix is optimised
for at-a-glance inspection: rows = papers, columns = facets such as
``methods``, ``sample_size``, ``outcome``, ``direction_of_effect``.

The matrix is populated by the LLM in the same step as the
evidence comparison and is validated by the same
:class:`CitationValidator` — every paper ID present in the matrix
must be part of the input set.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class MatrixCell:
    """
    A single cell of the evidence matrix.

    Attributes
    ----------
    paper_id : str
        Paper PMID or DOI this cell refers to.

    facets : dict[str, str]
        Facet name -> short textual value. Empty values are skipped
        during rendering.
    """

    paper_id: str
    facets: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceMatrix:
    """
    Side-by-side comparison table for a workspace's papers.

    Attributes
    ----------
    columns : list[str]
        Ordered list of facet names (column headers). The first
        column is always ``paper_id`` and is implicit.

    rows : list[MatrixCell]
        One cell per paper. The order of ``rows`` is the order in
        which the LLM produced them; the UI is free to re-sort.

    used_paper_ids : list[str]
        Closed set of paper IDs that the matrix describes. Mirrors
        the same field on :class:`EvidenceComparison` so the
        validator can check both structures consistently.
    """

    columns: list[str] = field(default_factory=list)
    rows: list[MatrixCell] = field(default_factory=list)
    used_paper_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Normalise columns: dedupe (case-insensitive), preserve order.
        seen: set[str] = set()
        normalised: list[str] = []
        for col in self.columns:
            key = col.strip()
            if not key or key.lower() in seen:
                continue
            seen.add(key.lower())
            normalised.append(key)
        self.columns = normalised

        # Dedupe and freeze used_paper_ids
        seen_pids: set[str] = set()
        normalised_pids: list[str] = []
        for pid in self.used_paper_ids:
            pid = str(pid).strip()
            if not pid or pid in seen_pids:
                continue
            seen_pids.add(pid)
            normalised_pids.append(pid)
        self.used_paper_ids = normalised_pids

    @property
    def has_rows(self) -> bool:
        """Whether the matrix contains at least one row."""
        return bool(self.rows)
