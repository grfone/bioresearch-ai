"""
comparison_mapper.py

Infrastructure mapper that converts an LLM response into a structured
:class:`EvidenceComparison`.

Purpose
-------
LLM providers return natural language text. The domain layer, however,
requires structured entities. This mapper is the anti-corruption layer
between the LLM's output and the deterministic
:class:`EvidenceComparison` schema.

The mapper accepts two response formats:

1. **JSON.** If the response content starts with ``{`` it is parsed
   as JSON. The JSON must follow the schema documented in
   ``app/application/prompts/comparison_prompt.py``.
2. **Markdown.** If parsing fails, the mapper falls back to a
   lightweight markdown parser that extracts sections by heading.

In both cases the produced :class:`EvidenceComparison` is bound to
the input paper set: any paper ID that is not in the closed set is
stripped. The :class:`CitationValidator` (in the application layer)
performs the final enforcement.

The class intentionally contains no:

- LLM communication logic;
- prompt construction;
- persistence logic;
- presentation formatting.

That separation of concerns keeps the mapper small, testable, and
replaceable.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.domain.entities.evidence_comparison import EvidenceComparison
from app.domain.entities.evidence_matrix import EvidenceMatrix, MatrixCell
from app.domain.entities.finding import Contradiction, Finding
from app.domain.entities.paper import Paper
from app.domain.models.llm_response import LLMResponse


logger = logging.getLogger(__name__)


@dataclass
class _ComparisonJSON:
    """Intermediate shape used by the JSON parser."""

    consensus: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]
    research_gaps: list[str]
    future_directions: list[str]
    matrix: dict[str, Any] | None
    confidence: float | None


@dataclass
class EvidenceComparisonMapper:
    """
    Convert LLM responses into EvidenceComparison entities.

    The mapper is a stateless component. It holds no configuration
    and no identity of its own beyond the methods it exposes.
    """

    def map(
        self,
        response: LLMResponse,
        papers: list[Paper],
    ) -> EvidenceComparison:
        """
        Transform an LLM response into an EvidenceComparison.

        Parameters
        ----------
        response : LLMResponse
            Normalized response returned by an LLM provider.

        papers : list[Paper]
            The closed set of papers that were passed to the LLM.
            Used to restrict cited paper IDs to the input set.

        Returns
        -------
        EvidenceComparison
            Structured cross-paper comparison.

        Raises
        ------
        ValueError
            If the response is empty.
        """
        if response is None:
            raise ValueError("LLM response cannot be None.")
        if not response.content or not response.content.strip():
            raise ValueError("LLM response content cannot be empty.")

        allowed_ids = {
            ("pmid", p.pmid) for p in papers if p.pmid
        } | {("doi", p.doi) for p in papers if p.doi}

        parsed = self._parse(response.content)

        consensus = [
            self._finding_from_dict(item, allowed_ids)
            for item in parsed.consensus
        ]
        contradictions = [
            self._contradiction_from_dict(item, allowed_ids)
            for item in parsed.contradictions
        ]
        research_gaps = [
            self._clean_text(g)
            for g in parsed.research_gaps
            if self._clean_text(g)
        ]
        future_directions = [
            self._clean_text(g)
            for g in parsed.future_directions
            if self._clean_text(g)
        ]
        matrix = self._matrix_from_dict(parsed.matrix, allowed_ids)

        used_paper_ids = [p.pmid or p.doi for p in papers if p.pmid or p.doi]

        return EvidenceComparison(
            consensus=consensus,
            contradictions=contradictions,
            research_gaps=research_gaps,
            future_directions=future_directions,
            used_paper_ids=used_paper_ids,
            matrix=matrix,
            confidence=parsed.confidence,
            metadata={
                "model": response.model,
                "finish_reason": response.finish_reason,
                "prompt_tokens": str(response.prompt_tokens),
                "completion_tokens": str(response.completion_tokens),
                "total_tokens": str(response.total_tokens),
            },
        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self, content: str) -> _ComparisonJSON:
        """
        Parse the LLM content into a structured intermediate.

        Tries JSON first, then falls back to a lightweight markdown
        parser. Both code paths produce the same intermediate shape.
        """
        stripped = content.strip()
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
                return self._from_json(obj)
            except json.JSONDecodeError:
                logger.warning(
                    "Comparison response started with '{' but failed "
                    "JSON parsing; falling back to markdown."
                )
        # Try to find a JSON block inside markdown.
        match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(1))
                return self._from_json(obj)
            except json.JSONDecodeError:
                logger.warning(
                    "Found a fenced JSON block but it failed to parse."
                )
        return self._from_markdown(content)

    def _from_json(self, obj: dict[str, Any]) -> _ComparisonJSON:
        return _ComparisonJSON(
            consensus=list(obj.get("consensus") or []),
            contradictions=list(obj.get("contradictions") or []),
            research_gaps=list(obj.get("research_gaps") or []),
            future_directions=list(obj.get("future_directions") or []),
            matrix=obj.get("matrix") if isinstance(obj.get("matrix"), dict) else None,
            confidence=self._safe_float(obj.get("confidence")),
        )

    def _from_markdown(self, content: str) -> _ComparisonJSON:
        sections = self._split_sections(content)
        consensus_raw = sections.get("consensus", [])
        contradictions_raw = sections.get("contradictions", [])
        gaps_raw = sections.get("research gaps", [])
        future_raw = sections.get("future directions", [])
        confidence = self._try_extract_confidence(content)

        return _ComparisonJSON(
            consensus=[
                {"claim": line, "paper_ids": []}
                for line in consensus_raw
            ],
            contradictions=[
                {"topic": line, "description": line, "paper_ids": []}
                for line in contradictions_raw
            ],
            research_gaps=gaps_raw,
            future_directions=future_raw,
            matrix=None,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Coercion helpers
    # ------------------------------------------------------------------

    def _finding_from_dict(
        self,
        item: dict[str, Any],
        allowed_ids: set[tuple[str, str]],
    ) -> Finding:
        claim = self._clean_text(item.get("claim") or item.get("text") or "")
        paper_ids = self._restrict_paper_ids(
            item.get("paper_ids") or item.get("pmids") or item.get("papers") or [],
            allowed_ids,
        )
        return Finding(
            claim=claim or "(unspecified claim)",
            paper_ids=paper_ids,
            evidence_strength=self._clean_text(item.get("evidence_strength")),
            notes=self._clean_text(item.get("notes")),
        )

    def _contradiction_from_dict(
        self,
        item: dict[str, Any],
        allowed_ids: set[tuple[str, str]],
    ) -> Contradiction:
        topic = self._clean_text(item.get("topic") or item.get("title") or "")
        description = self._clean_text(
            item.get("description") or item.get("detail") or ""
        )
        paper_ids = self._restrict_paper_ids(
            item.get("paper_ids") or item.get("pmids") or item.get("papers") or [],
            allowed_ids,
        )
        return Contradiction(
            topic=topic or "(unspecified topic)",
            description=description or "(no description)",
            paper_ids=paper_ids,
            severity=self._clean_text(item.get("severity")),
        )

    def _matrix_from_dict(
        self,
        matrix: dict[str, Any] | None,
        allowed_ids: set[tuple[str, str]],
    ) -> EvidenceMatrix | None:
        if not matrix:
            return None
        columns = [str(c) for c in matrix.get("columns") or []]
        rows = matrix.get("rows") or []
        cells: list[MatrixCell] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            paper_id = str(
                row.get("paper_id") or row.get("pmid") or row.get("doi") or ""
            )
            if not paper_id:
                continue
            if not self._is_allowed(paper_id, allowed_ids):
                continue
            facets = {
                str(k): self._clean_text(v)
                for k, v in row.items()
                if k not in {"paper_id", "pmid", "doi"} and self._clean_text(v)
            }
            cells.append(MatrixCell(paper_id=paper_id, facets=facets))
        if not cells and not columns:
            return None
        used_paper_ids = [cell.paper_id for cell in cells]
        return EvidenceMatrix(
            columns=columns,
            rows=cells,
            used_paper_ids=used_paper_ids,
        )

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        if not 0.0 <= f <= 1.0:
            return None
        return f

    @staticmethod
    def _is_allowed(
        paper_id: str,
        allowed_ids: set[tuple[str, str]],
    ) -> bool:
        pid = paper_id.strip()
        if not pid:
            return False
        kind, _, value = pid.partition(":")
        if kind in ("pmid", "doi") and value:
            return (kind, value) in allowed_ids
        # Bare PMID / DOI accepted.
        if ("pmid", pid) in allowed_ids:
            return True
        if ("doi", pid) in allowed_ids:
            return True
        return False

    def _restrict_paper_ids(
        self,
        raw_ids: Any,
        allowed_ids: set[tuple[str, str]],
    ) -> list[str]:
        if raw_ids is None:
            return []
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        if not isinstance(raw_ids, list):
            return []
        result: list[str] = []
        for x in raw_ids:
            if x is None:
                continue
            pid = str(x).strip()
            if not self._is_allowed(pid, allowed_ids):
                continue
            # Normalise to bare form for storage.
            kind, _, value = pid.partition(":")
            normalised = f"{kind}:{value}" if kind in ("pmid", "doi") and value else pid
            if normalised not in result:
                result.append(normalised)
        return result

    @staticmethod
    def _split_sections(content: str) -> dict[str, list[str]]:
        """Map section heading → list of bullet lines."""
        sections: dict[str, list[str]] = {}
        current: str | None = None
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                current = stripped.lstrip("#").strip().lower()
                sections.setdefault(current, [])
                continue
            if current is None:
                continue
            if stripped.startswith("-") or stripped.startswith("*"):
                value = stripped.lstrip("-*").strip()
                if value:
                    sections.setdefault(current, []).append(value)
        return sections

    @staticmethod
    def _try_extract_confidence(content: str) -> float | None:
        for line in content.splitlines():
            if "confidence" not in line.lower():
                continue
            tokens = (
                line.replace("%", "")
                .replace(":", " ")
                .split()
            )
            for item in tokens:
                try:
                    f = float(item)
                except ValueError:
                    continue
                if f > 1:
                    f /= 100.0
                if 0.0 <= f <= 1.0:
                    return f
        return None
