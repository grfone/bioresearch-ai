"""
report_generator.py

Infrastructure implementation of the ReportGenerator interface.

Purpose
-------
This module adapts a Large Language Model provider into the biomedical
report generation capability required by the application layer.

The LLMReportGenerator is responsible for:

- Building a provider-independent Prompt.
- Sending the prompt through the configured LLMProvider.
- Delegating response transformation to ReportMapper.

The class does not construct domain entities directly. The conversion from
external AI output into domain objects belongs to ReportMapper.

This keeps responsibilities separated:

- LLMProvider handles model communication.
- LLMReportGenerator handles report generation workflow.
- ReportMapper handles response transformation.
- ResearchReport remains a pure domain entity.

Architecture
------------

GenerateReportUseCase
          |
          |
          v
ReportGenerator
(interface)
          |
          |
          v
LLMReportGenerator
          |
          +----------------+
          |                |
          v                v
    LLMProvider      ReportMapper
          |                |
          v                v
     LLMResponse ---> ResearchReport


Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations


from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.summary import Summary
from app.domain.entities.research_report import ResearchReport

from app.domain.interfaces.report_generator import (
    ReportGenerator,
)

from app.domain.interfaces.llm_provider import (
    LLMProvider,
)

from app.domain.models.prompt import Prompt

from app.infrastructure.llm.report_mapper import (
    ReportMapper,
)


class LLMReportGenerator(ReportGenerator):
    """
    Generate biomedical research reports using an LLM provider.

    This class is an infrastructure adapter implementing the domain
    ReportGenerator interface.

    It coordinates the report generation workflow but delegates:

    - model communication to LLMProvider;
    - response interpretation to ReportMapper.

    Parameters
    ----------
    llm_provider : LLMProvider
        Provider responsible for communicating with the language model.

    report_mapper : ReportMapper
        Component responsible for converting generated responses into
        ResearchReport domain entities.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        report_mapper: ReportMapper,
    ) -> None:
        """
        Initialize the LLM report generator.

        Parameters
        ----------
        llm_provider
            Configured language model provider.

        report_mapper
            Mapper responsible for transforming LLM responses.
        """

        self._llm_provider = llm_provider
        self._report_mapper = report_mapper

    def generate(
        self,
        question: ResearchQuestion,
        summary: Summary,
    ) -> ResearchReport:
        """
        Generate a biomedical research report.

        Workflow
        --------
        1. Build a structured prompt.
        2. Send the prompt to the configured LLM.
        3. Map the generated response into a ResearchReport.

        Parameters
        ----------
        question : ResearchQuestion
            Original biomedical research question.

        summary : Summary
            Evidence synthesis generated from scientific literature.

        Returns
        -------
        ResearchReport
            Structured biomedical research report.

        Raises
        ------
        ValueError
            If the supplied question or summary is invalid.
        """

        if question is None:
            raise ValueError(
                "Research question cannot be None."
            )

        if summary is None:
            raise ValueError(
                "Summary cannot be None."
            )

        prompt = self._build_prompt(
            question,
            summary,
        )

        response = self._llm_provider.generate(
            prompt
        )

        return self._report_mapper.map(
            response,
            summary,
        )

    @staticmethod
    def _build_prompt(
        question: ResearchQuestion,
        summary: Summary,
    ) -> Prompt:
        """
        Build the report generation prompt.

        Parameters
        ----------
        question : ResearchQuestion
            Research question being investigated.

        summary : Summary
            Evidence synthesis used as report input.

        Returns
        -------
        Prompt
            Provider-independent prompt model.

        Notes
        -----
        Prompt construction intentionally remains here because report
        generation is the responsibility of this adapter.

        Future versions may extract prompts into dedicated prompt builders.
        """

        # The summary text contains ``[paper:N]`` markers (one per
        # cited paper; index ``N`` is the position in
        # ``summary.papers_used``). We mirror that convention
        # in the report -- the LLM should use the same markers
        # when it cites a paper, so the citation pipeline can
        # match the LLM's mentions back to the bibliography
        # we build in ``ReportMapper``.
        #
        # We ask for four sections the report UI already renders:
        # Title, Executive Summary, Limitations, Future Work.
        # We deliberately do NOT ask for a confidence score: the LLM
        # is generating the report FROM the papers the user supplied,
        # so any self-evaluation ("I'm 85% confident") would be
        # tautological. We surface the supporting papers and their
        # bibliography instead -- that's the real evidence of
        # credibility. See ADR-009 (planned) for the rationale.
        summary_text = str(summary)
        user_prompt = (
            "Create a structured biomedical research report "
            "for this research question:\n\n"
            f"{question.question}\n\n"
            "Use the following evidence summary as the report's "
            "foundation. Every paper cited in the summary is "
            "marked with ``[paper:N]`` -- preserve those markers "
            "in your output so downstream tools can build the "
            "bibliography. The summary text itself is:\n\n"
            f"{summary_text}\n\n"
            "Output structure (use exactly these section headings):\n\n"
            "# <report title>\n\n"
            "## Executive Summary\n"
            "<2-4 paragraphs synthesising the evidence; reference "
            "papers by their ``[paper:N]`` markers>\n\n"
            "## Limitations\n"
            "- <limitation 1>\n"
            "- <limitation 2>\n\n"
            "## Future Work\n"
            "- <future research direction 1>\n"
            "- <future research direction 2>"
        )

        return Prompt(
            system=(
                "You are a biomedical research assistant. "
                "Generate a rigorous scientific report based on "
                "available scientific evidence. Every factual "
                "claim must reference the source paper using its "
                "``[paper:N]`` marker (e.g. ``[paper:1]`` for the "
                "first cited paper). Do NOT include any confidence "
                "or uncertainty score -- the supporting papers and "
                "the bibliography are the evidence of credibility."
            ),
            user=user_prompt,
            context=summary_text,
            temperature=0.2,
            max_tokens=4096,
            metadata={
                "task": "biomedical_report_generation",
            },
        )