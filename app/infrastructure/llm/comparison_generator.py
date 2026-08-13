"""
comparison_generator.py

Infrastructure implementation of the ComparisonGenerator interface.

Purpose
-------
This module adapts a Large Language Model provider into the
cross-paper evidence comparison capability required by the
application layer.

The LLMComparisonGenerator is responsible for:

- Building a provider-independent Prompt that includes the
  comparison prompt and the paper corpus.
- Sending the prompt through the configured LLMProvider.
- Delegating response transformation to EvidenceComparisonMapper.

The class does not construct domain entities directly. The
conversion from external AI output into the domain entity is
performed by the mapper, which also strips any paper IDs not in
the input set.

The downstream :class:`CitationValidator` is the final guard
against fabricated citations.

Architecture
------------

CompareEvidenceUseCase
          |
          v
ComparisonGenerator  (interface)
          |
          v
LLMComparisonGenerator
          |
          +----------------------+
          |                      |
          v                      v
    LLMProvider          EvidenceComparisonMapper
          |                      |
          v                      v
     LLMResponse ---> EvidenceComparison


Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.application.prompts.comparison_prompt import COMPARISON_PROMPT
from app.domain.entities.evidence_comparison import EvidenceComparison
from app.domain.entities.paper import Paper
from app.domain.entities.research_question import ResearchQuestion
from app.domain.interfaces.comparison_generator import ComparisonGenerator
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.models.prompt import Prompt
from app.infrastructure.llm.comparison_mapper import EvidenceComparisonMapper


class LLMComparisonGenerator(ComparisonGenerator):
    """
    Generate cross-paper evidence comparisons using an LLM provider.

    This class is an infrastructure adapter implementing the
    :class:`ComparisonGenerator` interface.

    Parameters
    ----------
    llm_provider : LLMProvider
        Provider responsible for communicating with the language
        model.

    comparison_mapper : EvidenceComparisonMapper
        Component responsible for converting LLM responses into
        :class:`EvidenceComparison` domain entities.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        comparison_mapper: EvidenceComparisonMapper,
    ) -> None:
        self._llm_provider = llm_provider
        self._comparison_mapper = comparison_mapper

    def generate(
        self,
        question: ResearchQuestion,
        papers: list[Paper],
    ) -> EvidenceComparison:
        """
        Generate a cross-paper evidence comparison.

        Workflow
        --------
        1. Build a structured prompt that includes the comparison
           prompt and the paper corpus.
        2. Send the prompt to the configured LLM.
        3. Map the response into an EvidenceComparison, restricting
           cited paper IDs to the input set.

        Parameters
        ----------
        question : ResearchQuestion
            Original biomedical research question.

        papers : list[Paper]
            Closed set of papers to compare.

        Returns
        -------
        EvidenceComparison
            Structured cross-paper comparison.
        """
        if question is None:
            raise ValueError("Research question cannot be None.")
        if not papers:
            raise ValueError("Cannot compare an empty paper set.")

        prompt = self._build_prompt(question, papers)
        response = self._llm_provider.generate(prompt)
        return self._comparison_mapper.map(response, papers)

    @staticmethod
    def _build_prompt(
        question: ResearchQuestion,
        papers: list[Paper],
    ) -> Prompt:
        """
        Build the comparison prompt.

        Each paper is rendered as a numbered block with its PMID/DOI
        so the LLM can refer to it deterministically. The LLM is
        asked to cite papers using the ``pmid:<digits>`` or
        ``doi:<doi>`` form so the validator can enforce the
        closed-set contract.
        """
        paper_blocks: list[str] = []
        for idx, paper in enumerate(papers, start=1):
            identifier = (
                f"pmid:{paper.pmid}"
                if paper.pmid
                else f"doi:{paper.doi}"
                if paper.doi
                else f"ref:{idx}"
            )
            paper_blocks.append(
                f"[{identifier}] {paper.title}\n"
                f"Authors: {', '.join(a.full_name for a in paper.authors) or 'N/A'}\n"
                f"Year: {paper.year or 'N/A'}\n"
                f"Journal: {paper.journal.name if paper.journal else 'N/A'}\n"
                f"Abstract: {paper.abstract or 'N/A'}"
            )

        context = "\n\n".join(paper_blocks)

        user = (
            f"Research question:\n{question.question}\n\n"
            f"Papers ({len(papers)}):\n{context}\n\n"
            "Reply with the JSON object as specified in the system "
            "instructions."
        )

        return Prompt(
            system=COMPARISON_PROMPT,
            user=user,
            context=context,
            temperature=0.2,
            max_tokens=4096,
            metadata={"task": "biomedical_evidence_comparison"},
        )
