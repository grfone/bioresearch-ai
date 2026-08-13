"""
evidence_comparison.py

Domain entity representing the cross-paper evidence comparison
produced by the COMPARED workspace state.

This entity is the structured outcome of the LLM-as-judge step that
reads the entire workspace paper set and produces a synthesis that
goes beyond a single-paper summary. It captures:

- **Consensus** (list[Finding]): findings supported by multiple papers.
- **Contradictions** (list[Contradiction]): disagreements between papers.
- **Research gaps**: open questions not addressed by the corpus.
- **Future directions**: research suggestions grounded in the corpus.
- **Used paper IDs**: the closed set of paper IDs that contributed.

The ``used_paper_ids`` field is the anti-fabrication handle. The
``CitationValidator`` (in application/validation) checks that every
paper_id referenced anywhere in the comparison is a member of this
set. Because the comparison is produced from the workspace's own
papers, this set is the ground truth for "what the LLM was allowed
to cite".

The :class:`EvidenceMatrix` is a complementary view that arranges the
same data as a table (rows = papers, columns = facets) so the
researcher can compare papers side-by-side at a glance.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities.evidence_matrix import EvidenceMatrix
from app.domain.entities.finding import Contradiction, Finding


@dataclass(slots=True)
class EvidenceComparison:
    """
    Cross-paper evidence synthesis produced by the workspace.

    The comparison is the workspace's authoritative answer to the
    question "what does the literature actually say?". It is built
    once and stored on the session alongside the summary. Regenerating
    the summary does not invalidate the comparison — the orchestrator
    handles the lifecycle (see ``TRANSITIONS`` in
    ``app.core.enums.workspace_state``).

    Attributes
    ----------
    consensus : list[Finding]
        Findings supported by multiple papers.

    contradictions : list[Contradiction]
        Documented disagreements between papers.

    research_gaps : list[str]
        Open questions the corpus does not address.

    future_directions : list[str]
        Suggested follow-up research grounded in the corpus.

    used_paper_ids : list[str]
        Closed set of paper IDs that contributed to the comparison.
        Always equals the workspace's paper IDs at the time of
        generation. The validator uses this set to reject any
        fabricated citation.

    matrix : EvidenceMatrix | None
        Optional side-by-side comparison table. Generated when the
        LLM is asked to also produce a structured matrix.

    confidence : float | None
        Optional overall confidence score in the comparison
        (range [0.0, 1.0]).

    metadata : dict[str, str]
        Generator metadata (model, temperature, etc.).
    """

    consensus: list[Finding] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    research_gaps: list[str] = field(default_factory=list)
    future_directions: list[str] = field(default_factory=list)
    used_paper_ids: list[str] = field(default_factory=list)
    matrix: EvidenceMatrix | None = None
    confidence: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def has_consensus(self) -> bool:
        """Whether the comparison contains consensus findings."""
        return bool(self.consensus)

    @property
    def has_contradictions(self) -> bool:
        """Whether the comparison contains contradictions."""
        return bool(self.contradictions)

    @property
    def has_matrix(self) -> bool:
        """Whether a structured comparison matrix is available."""
        return self.matrix is not None and bool(self.matrix.rows)

    def __post_init__(self) -> None:
        if self.confidence is not None:
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError(
                    "EvidenceComparison.confidence must be in [0.0, 1.0]."
                )

        # Dedupe and freeze used_paper_ids
        seen: set[str] = set()
        normalised: list[str] = []
        for pid in self.used_paper_ids:
            pid = str(pid).strip()
            if not pid or pid in seen:
                continue
            seen.add(pid)
            normalised.append(pid)
        self.used_paper_ids = normalised
