"""
pdf_generator.py

Abstract interface implemented by every PDF renderer.

The interface is intentionally narrow: a single
``generate`` method that takes the artefacts it needs and
returns raw PDF bytes. This is the same shape as
``LLMProvider`` -- one entry point, no ceremony.

The interface lives in the Domain layer because the
``PublishReportUseCase`` (which orchestrates the publish flow)
depends on it. The actual implementation lives in the
infrastructure layer (see ``app.infrastructure.pdf``).

The interface deliberately does NOT take a ``ResearchSession``
or any other wide object. Keeping the parameter list narrow
makes the contract testable without setting up a full session --
the unit tests just construct a ``ResearchReport`` with stub data
and assert on the bytes.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.research_report import ResearchReport


class PDFGenerator(ABC):
    """
    Render a :class:`ResearchReport` as a PDF document.

    Implementations
    ---------------
    - :class:`app.infrastructure.pdf.minimal_generator.MinimalPDFGenerator`
      (hand-rolled, no third-party dependency)

    A future implementation might use ``reportlab`` or
    ``weasyprint`` -- the interface stays the same.

    Contract
    --------
    Implementations MUST:

    1. Return bytes that start with ``b"%PDF-"`` (the PDF 1.4+
       magic header). Anything else breaks downstream parsers.
    2. Produce a valid single-document PDF that opens in
       standard readers (Preview, Acrobat, Chrome).
    3. Include the report's summary, citations, limitations,
       and future_work sections in that order.
    4. Be deterministic for a given input -- the same report
       should produce byte-identical PDFs across runs (this lets
       tests assert on the content).
    """

    @abstractmethod
    def generate(self, report: ResearchReport) -> bytes:
        """
        Render ``report`` as PDF bytes.

        Parameters
        ----------
        report : ResearchReport
            The structured report to render.

        Returns
        -------
        bytes
            A valid PDF document. Must start with ``b"%PDF-"``.

        Raises
        ------
        ValueError
            If the report has no summary text to render (the
            mapper guarantees this for any non-empty report).
        """
