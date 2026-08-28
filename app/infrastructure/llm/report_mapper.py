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
        ``summary.body``. This preserves the order the LLM chose to
        mention them, which is the best proxy we have for
        "relevance" without re-running a separate ranking model.
        Papers that don't appear at all in the summary body (e.g.
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
        # ----------------------------------------------------------------
        # Citation matching strategy
        # ----------------------------------------------------------------
        # We use a two-signal approach: marker-based matching (the
        # primary signal) and title/DOI substring matching (the
        # fallback).
        #
        # Why marker-based is primary:
        #   Real LLM summaries paraphrase paper titles. The previous
        #   title-substring matcher found zero citations in production
        #   even with 20 papers loaded, because the LLM rewrote every
        #   title in the synthesis. ``[paper:N]`` markers in the
        #   summary body bypass the paraphrasing problem: the LLM
        #   references the paper by its 1-indexed position in the
        #   papers list, which is independent of the title text.
        #
        # Why we keep substring matching as a fallback:
        #   Markers require a summary prompt that emits them. If the
        #   LLM ignores the marker instruction (older prompts, model
        #   regressions), the substring matcher still works for papers
        #   that are mentioned by their literal title or DOI.
        #
        # The full chain (markers -> fallback -> dedup -> cap) is
        # exercised in tests/unit/test_report_mapper.py and the
        # integration suite.

        # ``summary.papers_used`` may be a tuple or list; convert
        # defensively.
        papers = list(summary.papers_used)
        if not papers:
            return []

        text = summary.body or ""

        import re as _re

        # Extract every ``[paper:N]`` marker position from the text.
        # ``re.finditer`` returns matches in left-to-right order so
        # we can rely on iteration order for "first appearance" tracking.
        marker_positions: dict[int, int] = {}
        for match in _re.finditer(r"\[paper:(\d+)\]", text):
            index = int(match.group(1))
            # First occurrence of each marker index wins (a paper can
            # be cited multiple times; we only care about the first).
            if index not in marker_positions:
                marker_positions[index] = match.start()

        # ``papers`` is 0-indexed but the LLM sees 1-indexed
        # positions. Build the marker-driven order: sort by the
        # FIRST occurrence of each marker in the text, so the
        # citation list mirrors the order the LLM chose to mention
        # them in the synthesis.
        marker_order: list[int] = []
        for marker_index_1based in sorted(
            marker_positions, key=lambda k: marker_positions[k]
        ):
            paper_index_0based = marker_index_1based - 1
            if 0 <= paper_index_0based < len(papers):
                marker_order.append(paper_index_0based)

        # Substring fallback for any papers not picked up by
        # markers. ``fallback_positions[i]`` is the first char
        # index in the text where paper i's title/DOI appears, or
        # -1 if the paper never appeared.
        haystack = text.lower()
        fallback_positions: list[int] = [-1] * len(papers)
        for paper_index, paper in enumerate(papers):
            if paper_index in marker_order:
                # Already cited via marker; no need to substring-match.
                continue
            needle_title = (paper.title or "").lower()
            needle_doi = (paper.doi or "").lower()
            candidates: list[int] = []
            if needle_title and len(needle_title) >= 4:
                idx = haystack.find(needle_title)
                if idx >= 0:
                    candidates.append(idx)
            if needle_doi and len(needle_doi) >= 7:
                idx = haystack.find(needle_doi)
                if idx >= 0:
                    candidates.append(idx)
            fallback_positions[paper_index] = (
                min(candidates) if candidates else -1
            )

        # Build the citation list.
        seen_dois: set[str] = set()
        ordered: list = []

        # Phase 1: marker-driven citations, in marker appearance order.
        for paper_index in marker_order:
            paper = papers[paper_index]
            if paper.doi and paper.doi in seen_dois:
                continue
            if paper.doi:
                seen_dois.add(paper.doi)
            ordered.append(
                Citation(paper=paper, style=CitationStyleEnum.APA)
            )
            if len(ordered) >= max_count:
                return ordered

        # Phase 2: substring-driven citations, in first-appearance order.
        # Papers with no match at all (fallback_positions == -1) are
        # dropped -- they didn't influence the synthesis, so citing
        # them in the bibliography would be misleading.
        substring_candidates = [
            (pos, idx)
            for idx, pos in enumerate(fallback_positions)
            if pos >= 0
        ]
        substring_candidates.sort(key=lambda pair: pair[0])
        for _, paper_index in substring_candidates:
            paper = papers[paper_index]
            if paper.doi and paper.doi in seen_dois:
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
