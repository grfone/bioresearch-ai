"""
evidence_comparison_response.py

API response schema for the cross-paper evidence comparison.

The schema serialises the :class:`EvidenceComparison` domain
entity into HTTP-friendly JSON. It is returned by the comparison
endpoints and embedded in the workspace response.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FindingResponse(BaseModel):
    """A single consensus finding."""

    model_config = ConfigDict(from_attributes=True)

    claim: str
    paper_ids: list[str] = Field(default_factory=list)
    evidence_strength: str | None = None
    notes: str | None = None


class ContradictionResponse(BaseModel):
    """A single contradiction between papers."""

    model_config = ConfigDict(from_attributes=True)

    topic: str
    description: str
    paper_ids: list[str] = Field(default_factory=list)
    severity: str | None = None


class MatrixCellResponse(BaseModel):
    """A single row of the evidence matrix."""

    model_config = ConfigDict(from_attributes=True)

    paper_id: str
    facets: dict[str, str] = Field(default_factory=dict)


class EvidenceMatrixResponse(BaseModel):
    """Side-by-side comparison table."""

    model_config = ConfigDict(from_attributes=True)

    columns: list[str] = Field(default_factory=list)
    rows: list[MatrixCellResponse] = Field(default_factory=list)
    used_paper_ids: list[str] = Field(default_factory=list)


class EvidenceComparisonResponse(BaseModel):
    """Full cross-paper evidence comparison."""

    model_config = ConfigDict(from_attributes=True)

    consensus: list[FindingResponse] = Field(default_factory=list)
    contradictions: list[ContradictionResponse] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)
    future_directions: list[str] = Field(default_factory=list)
    used_paper_ids: list[str] = Field(default_factory=list)
    matrix: EvidenceMatrixResponse | None = None
    confidence: float | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, comparison: Any) -> "EvidenceComparisonResponse":
        from app.domain.entities.evidence_comparison import (
            EvidenceComparison,
        )
        from app.domain.entities.evidence_matrix import EvidenceMatrix

        if not isinstance(comparison, EvidenceComparison):
            raise TypeError(
                "EvidenceComparisonResponse.from_domain requires an "
                "EvidenceComparison instance."
            )

        matrix_resp = None
        if comparison.matrix is not None and isinstance(
            comparison.matrix, EvidenceMatrix
        ):
            matrix_resp = EvidenceMatrixResponse(
                columns=list(comparison.matrix.columns),
                rows=[
                    MatrixCellResponse(
                        paper_id=cell.paper_id,
                        facets=dict(cell.facets),
                    )
                    for cell in comparison.matrix.rows
                ],
                used_paper_ids=list(comparison.matrix.used_paper_ids),
            )

        return cls(
            consensus=[
                FindingResponse(
                    claim=f.claim,
                    paper_ids=list(f.paper_ids),
                    evidence_strength=f.evidence_strength,
                    notes=f.notes,
                )
                for f in comparison.consensus
            ],
            contradictions=[
                ContradictionResponse(
                    topic=c.topic,
                    description=c.description,
                    paper_ids=list(c.paper_ids),
                    severity=c.severity,
                )
                for c in comparison.contradictions
            ],
            research_gaps=list(comparison.research_gaps),
            future_directions=list(comparison.future_directions),
            used_paper_ids=list(comparison.used_paper_ids),
            matrix=matrix_resp,
            confidence=comparison.confidence,
            metadata=dict(comparison.metadata),
        )
