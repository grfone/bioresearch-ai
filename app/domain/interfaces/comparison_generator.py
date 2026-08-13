"""
comparison_generator.py

Domain interface for producing a cross-paper evidence comparison.

Purpose
-------
The infrastructure layer provides concrete implementations of this
interface (e.g. an LLM-based generator). The application layer
consumes the interface via :class:`CompareEvidenceUseCase` and is
therefore independent of the LLM provider.

This mirrors the design of :class:`ReportGenerator` (see
``app/domain/interfaces/report_generator.py``).

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.evidence_comparison import EvidenceComparison
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion


class ComparisonGenerator(ABC):
    """
    Cross-paper evidence comparison generator.

    Implementations take a research question and a closed set of
    papers and return an :class:`EvidenceComparison`. They are
    responsible for:

    - Building the comparison prompt.
    - Communicating with the underlying model.
    - Transforming the model response into the domain entity.

    Implementations are NOT responsible for validating citations
    against the input set. The orchestrator pairs the generator
    with a :class:`CitationValidator` (in the application layer) so
    that concern is enforced deterministically.
    """

    @abstractmethod
    def generate(
        self,
        question: ResearchQuestion,
        papers: list[Paper],
    ) -> EvidenceComparison:
        """
        Generate a cross-paper evidence comparison.

        Parameters
        ----------
        question : ResearchQuestion
            Original research question.

        papers : list[Paper]
            Closed set of papers to compare. The generator must
            treat this as the only allowed citation pool.

        Returns
        -------
        EvidenceComparison
            Structured comparison of the input papers.
        """
        raise NotImplementedError
