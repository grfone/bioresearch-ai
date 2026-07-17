"""
report_mapper.py

Infrastructure mapper responsible for converting LLM-generated content
into a ResearchReport domain entity.

Purpose
-------
Large Language Models return unstructured natural language responses.
The domain layer, however, requires structured entities.

This module provides the translation boundary between those two worlds.

The mapper belongs to the Infrastructure layer because it deals with
external representation formats and generated model output.

Responsibilities
----------------
- Convert LLM text responses into ResearchReport entities.
- Extract structured sections when possible.
- Preserve generation metadata.
- Keep parsing logic outside the domain model.

The mapper intentionally contains no:
- LLM communication logic;
- prompt construction;
- persistence logic;
- presentation formatting.

Architecture
------------

              LLMResponse
                    |
                    |
                    v
             ReportMapper
                    |
                    |
                    v
            ResearchReport
                    |
                    |
                    v
              Presentation


Future versions may support:

- JSON schema extraction;
- citation parsing;
- confidence estimation;
- section validation;
- structured output models;
- human review workflows.


Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.domain.entities.research_report import ResearchReport
from app.domain.entities.summary import Summary
from app.domain.models.llm_response import LLMResponse


class ReportMapper:
    """
    Convert LLM responses into ResearchReport domain entities.

    This class acts as an anti-corruption layer between external AI
    responses and the internal domain model.

    Parameters
    ----------
    There are no parameters

    Notes
    -----
    The mapper does not call LLM providers and does not generate prompts.
    It only transforms already generated responses.
    """

    def map(
        self,
        response: LLMResponse,
        summary: Summary,
    ) -> ResearchReport:
        """
        Transform an LLM response into a ResearchReport.

        Parameters
        ----------
        response : LLMResponse
            Normalized response returned by an LLM provider.

        summary : Summary
            Evidence synthesis used as the foundation of the report.

        Returns
        -------
        ResearchReport
            Structured biomedical research report.

        Raises
        ------
        ValueError
            If the response is empty or invalid.
        """

        if response is None:
            raise ValueError(
                "LLM response cannot be None."
            )

        if not response.content.strip():
            raise ValueError(
                "LLM response content cannot be empty."
            )

        if summary is None:
            raise ValueError(
                "Summary cannot be None."
            )

        return ResearchReport(
            summary=summary,
            limitations=self._extract_section(
                response.content,
                "Limitations",
            ),
            future_work=self._extract_section(
                response.content,
                "Future Work",
            ),
            confidence=self._extract_confidence(
                response.content,
            ),
            metadata={
                "model": response.model,
                "finish_reason": response.finish_reason,
                "prompt_tokens": str(
                    response.prompt_tokens
                ),
                "completion_tokens": str(
                    response.completion_tokens
                ),
                "total_tokens": str(
                    response.total_tokens
                ),
            },
        )

    @staticmethod
    def _extract_section(
        text: str,
        heading: str,
    ) -> list[str]:
        """
        Extract bullet points from a markdown-style section.

        Parameters
        ----------
        text : str
            Generated LLM response.

        heading : str
            Section heading to search for.

        Returns
        -------
        list[str]
            Extracted section items.

        Notes
        -----
        This is intentionally a lightweight parser.

        Future versions should replace this implementation with
        structured JSON generation from the LLM.
        """

        lines = text.splitlines()

        collecting = False

        results: list[str] = []

        for line in lines:

            stripped = line.strip()

            if stripped.lower().startswith(
                heading.lower()
            ):
                collecting = True
                continue

            if collecting:

                if stripped.startswith("#"):
                    break

                if stripped.startswith("-"):
                    results.append(
                        stripped.removeprefix("-").strip()
                    )

        return results

    @staticmethod
    def _extract_confidence(
        text: str,
    ) -> float | None:
        """
        Extract a confidence score from generated text.

        Parameters
        ----------
        text : str
            Generated LLM response.

        Returns
        -------
        float | None
            Confidence score if detected.

        Notes
        -----
        Expected formats include:

        - Confidence: 0.85
        - Confidence score: 85%

        Invalid values are ignored.
        """

        for line in text.splitlines():

            if "confidence" not in line.lower():
                continue

            value = (
                line
                .replace("%", "")
                .replace(":", " ")
                .split()
            )

            for item in value:

                try:

                    score = float(item)

                    if score > 1:
                        score /= 100

                    if 0 <= score <= 1:
                        return score

                except ValueError:
                    continue

        return None