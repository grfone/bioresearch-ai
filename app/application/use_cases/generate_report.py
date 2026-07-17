"""
generate_report.py

Application Use Case
--------------------
This module defines the GenerateReportUseCase, responsible for orchestrating
the creation of a biomedical research report.

The use case does **not** contain report generation logic itself. Instead,
it delegates that responsibility to an implementation of the
``ReportGenerator`` interface.

Following Clean Architecture principles, this layer coordinates the flow
between the domain and infrastructure layers while remaining independent
of specific implementations (e.g., OpenAI, Claude, local models, etc.).

Responsibilities
----------------
- Receive a validated research question.
- Receive an AI-generated evidence summary.
- Delegate report creation to a ReportGenerator.
- Return a structured ResearchReport.

This design allows different report generation strategies to be swapped
without modifying the application layer.

Author
------
Guillermo Ramajo Fernández
"""

from app.domain.entities.research_question import ResearchQuestion
from app.domain.entities.summary import Summary
from app.domain.entities.research_report import ResearchReport
from app.domain.interfaces.report_generator import ReportGenerator


class GenerateReportUseCase:
    """
    Coordinates the generation of a biomedical research report.

    This use case represents the application-layer orchestration for the
    report generation process. It receives the inputs required to build
    the final scientific report and delegates the actual generation to
    the configured ReportGenerator implementation.

    The use case is intentionally lightweight. Business rules belong to
    the domain layer, while external integrations (LLMs, APIs, templates,
    etc.) belong to the infrastructure layer.

    Parameters
    ----------
    report_generator : ReportGenerator
        Concrete implementation responsible for generating the final
        ResearchReport.

    Examples
    --------
        generator = OpenAIReportGenerator(...)
        use_case = GenerateReportUseCase(generator)
        report = use_case.execute(question, summary)
    """

    def __init__(self, report_generator: ReportGenerator) -> None:
        """
        Initialize the use case.

        Parameters
        ----------
        report_generator : ReportGenerator
            Service responsible for generating the final report.
        """
        self._report_generator = report_generator

    def execute(
        self,
        question: ResearchQuestion,
        summary: Summary,
    ) -> ResearchReport:
        """
        Generate a structured biomedical research report.

        This method orchestrates the report generation process by
        delegating the work to the configured ReportGenerator.

        Parameters
        ----------
        question : ResearchQuestion
            Original research question submitted by the user.

        summary : Summary
            AI-generated synthesis of the retrieved scientific evidence.

        Returns
        -------
        ResearchReport
            Structured report containing the synthesized findings,
            citations, limitations, and suggested future work.

        Raises
        ------
        ValueError
            If the provided question or summary is invalid.
        """

        if question is None:
            raise ValueError("Research question cannot be None.")

        if summary is None:
            raise ValueError("Summary cannot be None.")

        return self._report_generator.generate(
            question=question,
            summary=summary,
        )