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

from app.core.enums.citation_style import CitationStyleEnum
from app.domain.entities.citation import Citation
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.summary import Summary
from app.domain.models.llm_response import LLMResponse

# Maximum number of citations to include in a report. The
# Summary's ``papers_used`` list may contain every paper that
# touched the synthesis (often 20+); the report UI only has
# room for a curated subset. We pick the top N by the order
# they appear in the summary text -- that maps to how the LLM
# used them, which is the best signal of "most relevant".
_MAX_CITATIONS = 20


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

        # Build the citations list from the papers the summary
        # was built on. We cap at ``_MAX_CITATIONS`` because real
        # research sessions routinely summarise 20+ papers and the
        # report UI only shows the most relevant subset. The order
        # is "first appearance in the summary text" -- the LLM
        # naturally cites the most relevant evidence first, and we
        # honour that ordering in the references list.
        citations = self._build_citations(
            summary,
            max_count=_MAX_CITATIONS,
        )

        return ResearchReport(
            summary=summary,
            citations=citations,
            limitations=self._extract_section(
                response.content,
                "Limitations",
            ),
            future_work=self._extract_section(
                response.content,
                "Future Work",
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
                "citation_count": str(len(citations)),
            },
        )

    @staticmethod
    def _build_citations(
        summary: Summary,
        max_count: int,
    ) -> list[Citation]:
        """Build a deduplicated, ordered list of Citations from ``summary``.

        The Summary entity already carries ``papers_used`` -- the
        papers the LLM saw when generating the synthesis. Every
        paper that contributed to the summary is a candidate
        citation in the final report.

        Ordering: papers are sorted by their first appearance in
        ``summary.text``. This preserves the order the LLM chose to
        mention them, which is the best proxy we have for
        "relevance" without re-running a separate ranking model.
        Papers that don't appear at all in the summary text (e.g.
        the LLM saw them but never cited them) are dropped -- if
        they didn't influence the synthesis, citing them in the
        report would be misleading.

        Deduplication: two papers may share the same DOI (e.g.
        preprint + journal version). We keep the first one we see.

        Cap: ``max_count`` to keep the UI manageable.

        Parameters
        ----------
        summary : Summary
            Evidence synthesis carrying ``papers_used`` and
            ``text``.

        max_count : int
            Maximum number of citations to return.

        Returns
        -------
        list[Citation]
            Citations ordered by appearance, deduplicated, capped.
        """
        # ``summary.papers_used`` may be a tuple or list; convert
        # defensively.
        papers = list(summary.papers_used)
        if not papers:
            return []

        text = summary.text or ""
        # Lowercase for case-insensitive substring matching.
        haystack = text.lower()

        def first_index(paper) -> int:
            # Match on title (most reliable signal). Fall back to
            # DOI if the title is missing or absent from the text.
            needle_title = (paper.title or "").lower()
            needle_doi = (paper.doi or "").lower()
            candidates = []
            if needle_title and len(needle_title) >= 4:
                # Long-enough title to avoid false matches on
                # common short phrases ("a study", "the", "and").
                # 4 chars is the smallest threshold that still
                # rejects trivial matches; papers with shorter
                # titles are extremely rare in biomedical research.
                idx = haystack.find(needle_title)
                if idx >= 0:
                    candidates.append(idx)
            if needle_doi and len(needle_doi) >= 7:
                idx = haystack.find(needle_doi)
                if idx >= 0:
                    candidates.append(idx)
            if not candidates:
                # The paper didn't appear in the summary text at
                # all -- the LLM saw it but didn't cite it. Skip.
                return -1
            return min(candidates)

        seen_dois: set[str] = set()
        ordered: list = []
        # Sort by first appearance; ties broken by stable order in
        # ``papers_used``. Papers with first_index == -1 (not
        # mentioned in the summary) sort to the end of the list and
        # get dropped below.
        indexed = sorted(
            enumerate(papers),
            key=lambda pair: (first_index(pair[1]), pair[0]),
        )
        for _, paper in indexed:
            # Drop papers that never appeared in the summary text.
            # They may have influenced the LLM's synthesis at a
            # high level (e.g. as background reading) but citing
            # them in the bibliography would be misleading -- the
            # report makes no claim that came from them.
            if first_index(paper) < 0:
                continue
            if paper.doi and paper.doi in seen_dois:
                # Deduplicate by DOI.
                continue
            if paper.doi:
                seen_dois.add(paper.doi)
            ordered.append(
                Citation(paper=paper, style=CitationStyleEnum.APA)
            )
            if len(ordered) >= max_count:
                break
        return ordered
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

        # Normalise the heading: lowercase + strip leading ``#`` so
        # the comparison is heading-content-only. ``## Limitations``
        # -> ``"limitations"`` after this transform.
        needle = heading.lower().lstrip("#").strip()

        for line in lines:

            stripped = line.strip()

            # Strip any leading ``#`` markers before comparing, so
            # ``## Limitations`` and ``Limitations`` and ``### Limitations``
            # all match the same heading.
            cleaned = stripped.lower().lstrip("#").strip()
            if cleaned == needle or cleaned.startswith(needle):
                collecting = True
                continue

            if collecting:

                # Stop at the next section header (any line that
                # starts with ``#``).
                if stripped.startswith("#"):
                    break

                if stripped.startswith("-"):
                    results.append(
                        stripped.removeprefix("-").strip()
                    )

        return results
