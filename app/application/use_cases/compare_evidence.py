"""
compare_evidence.py

Application use case for cross-paper evidence synthesis.

Purpose
-------
This use case is the entry point for the FSM ``COMPARE`` action. It
consumes a research question and a closed set of papers, delegates
the actual comparison to a :class:`ComparisonGenerator`, and validates
the resulting :class:`EvidenceComparison` against the paper set using
:class:`CitationValidator`.

The pairing of generator + validator is the anti-fabrication guard.
The generator may produce any structured output; the validator
ensures that only papers in the input set are cited.

Following Clean Architecture, this use case is unaware of concrete
LLM providers (OpenAI, Anthropic, Ollama, etc.). It depends only on
the abstractions declared in the domain layer.

Workflow
--------

Research Question + Papers
    │
    ▼
ComparisonGenerator
    │
    ▼
EvidenceComparison
    │
    ▼
CitationValidator
    │
    ▼
Validated EvidenceComparison

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.application.validation.citation_validator import CitationValidator
from app.domain.entities.evidence_comparison import EvidenceComparison
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.interfaces.comparison_generator import ComparisonGenerator


class CompareEvidenceUseCase:
    """
    Cross-paper evidence synthesis.

    This use case produces a structured :class:`EvidenceComparison`
    from the workspace's current papers. The output is validated
    against the input set so that the LLM cannot cite papers that
    were not part of the workspace.

    Parameters
    ----------
    comparison_generator : ComparisonGenerator
        Concrete implementation responsible for prompting the
        language model and parsing the response.

    Notes
    -----
    The use case is intentionally lightweight. The heavy lifting
    (prompting, response parsing, citation validation) is delegated
    to the interfaces it depends on.

    This class is provider-independent: any implementation of
    ``ComparisonGenerator`` can be used without modification.
    """

    def __init__(
        self,
        comparison_generator: ComparisonGenerator,
    ) -> None:
        """
        Initialize the use case.

        Parameters
        ----------
        comparison_generator : ComparisonGenerator
            Configured generator responsible for the comparison.
        """
        self._comparison_generator = comparison_generator

    def execute(
        self,
        question: ResearchQuestion,
        papers: list[Paper],
    ) -> EvidenceComparison:
        """
        Generate a cross-paper evidence comparison.

        Parameters
        ----------
        question : ResearchQuestion
            The research question driving the comparison.

        papers : list[Paper]
            The closed set of papers retrieved for the workspace.

        Returns
        -------
        EvidenceComparison
            Structured cross-paper comparison, validated against the
            input paper set.

        Raises
        ------
        ValueError
            If no papers are provided.

        CitationValidationError
            If the generator produced a comparison that cites papers
            not in the input set.
        """
        if not papers:
            raise ValueError(
                "Cannot compare an empty collection of papers."
            )

        comparison = self._comparison_generator.generate(
            question,
            papers,
        )

        CitationValidator(papers).validate_evidence_comparison(comparison)

        return comparison
