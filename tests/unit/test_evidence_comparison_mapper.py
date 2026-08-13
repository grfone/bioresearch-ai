"""
Unit tests for the EvidenceComparisonMapper.

The mapper is the anti-corruption layer between the LLM's
unstructured JSON/markdown output and the deterministic
``EvidenceComparison`` schema. These tests verify that:

- JSON responses are parsed correctly.
- Markdown fallback works when the LLM does not return JSON.
- Paper IDs that are not in the input set are stripped.
- Both forms are bound to the workspace's paper IDs.

Author: project tests
"""

from __future__ import annotations

import json

from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.domain.models.llm_response import LLMResponse
from app.infrastructure.llm.comparison_mapper import (
    EvidenceComparisonMapper,
)


def _paper(pmid: str) -> Paper:
    return Paper(
        title=f"Paper {pmid}",
        pmid=pmid,
        authors=[Author(first_name="A", last_name="B")],
        journal=Journal(name="J"),
        abstract="abs",
    )


def _resp(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        finish_reason="stop",
    )


def test_parses_full_json_response() -> None:
    papers = [_paper("111"), _paper("222")]
    payload = json.dumps(
        {
            "consensus": [
                {
                    "claim": "Both papers find X.",
                    "paper_ids": ["pmid:111", "pmid:222"],
                    "evidence_strength": "strong",
                }
            ],
            "contradictions": [
                {
                    "topic": "Efficacy",
                    "description": "Mixed results.",
                    "paper_ids": ["pmid:111", "pmid:222"],
                    "severity": "minor",
                }
            ],
            "research_gaps": ["Long-term outcomes"],
            "future_directions": ["RCT with longer follow-up"],
            "matrix": {
                "columns": ["Methods", "Outcome"],
                "rows": [
                    {
                        "paper_id": "pmid:111",
                        "Methods": "RCT",
                        "Outcome": "Reduced progression",
                    },
                    {
                        "paper_id": "pmid:222",
                        "Methods": "Cohort",
                        "Outcome": "No effect",
                    },
                ],
            },
            "confidence": 0.85,
        }
    )
    mapper = EvidenceComparisonMapper()
    result = mapper.map(_resp(payload), papers)
    assert len(result.consensus) == 1
    assert result.consensus[0].claim == "Both papers find X."
    assert result.consensus[0].paper_ids == ["pmid:111", "pmid:222"]
    assert result.consensus[0].evidence_strength == "strong"
    assert len(result.contradictions) == 1
    assert result.research_gaps == ["Long-term outcomes"]
    assert result.future_directions == ["RCT with longer follow-up"]
    assert result.matrix is not None
    assert result.matrix.columns == ["Methods", "Outcome"]
    assert len(result.matrix.rows) == 2
    assert result.confidence == 0.85
    assert result.used_paper_ids == ["111", "222"]


def test_strips_fabricated_paper_ids() -> None:
    papers = [_paper("111")]
    payload = json.dumps(
        {
            "consensus": [
                {
                    "claim": "x",
                    "paper_ids": ["pmid:111", "pmid:99999"],
                }
            ],
            "research_gaps": [],
            "future_directions": [],
            "matrix": None,
            "confidence": None,
        }
    )
    mapper = EvidenceComparisonMapper()
    result = mapper.map(_resp(payload), papers)
    assert result.consensus[0].paper_ids == ["pmid:111"]


def test_falls_back_to_markdown() -> None:
    papers = [_paper("111")]
    markdown = """
# Consensus
- Finding A supported by the cohort.
- Finding B consistent across studies.

# Contradictions
- Disagreement on patient subgroups.

# Research Gaps
- Long-term follow-up is missing.

# Future Directions
- Run a multi-centre RCT.

Confidence: 0.7
"""
    mapper = EvidenceComparisonMapper()
    result = mapper.map(_resp(markdown), papers)
    assert len(result.consensus) == 2
    assert result.consensus[0].claim == "Finding A supported by the cohort."
    assert len(result.contradictions) == 1
    assert result.research_gaps == ["Long-term follow-up is missing."]
    assert result.future_directions == ["Run a multi-centre RCT."]
    assert result.confidence == 0.7


def test_empty_response_raises() -> None:
    papers = [_paper("111")]
    mapper = EvidenceComparisonMapper()
    try:
        mapper.map(_resp(""), papers)
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty response")


def test_confidence_in_valid_range() -> None:
    papers = [_paper("111")]
    payload = json.dumps(
        {
            "consensus": [],
            "research_gaps": [],
            "future_directions": [],
            "matrix": None,
            "confidence": 1.5,  # out of range, should be ignored
        }
    )
    mapper = EvidenceComparisonMapper()
    result = mapper.map(_resp(payload), papers)
    assert result.confidence is None
