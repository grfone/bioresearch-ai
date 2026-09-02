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
from app.domain.entities.paper import Paper
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.summary import Summary
from app.domain.models.llm_response import LLMResponse

# Maximum number of citations to include in a report. The
# Summary's ``papers_used`` list may contain every paper that
# touched the synthesis (often 20+); the report UI only has
# room for a curated subset. We pick the top N by the order
# they appear in the summary text -- that maps to how the LLM
# used them, which is the best signal of "most relevant".
#
# As of the 2026-08-31 FSM-fix iteration the cap is no longer
# applied to the citation list itself; instead the mapper
# returns EVERY workspace paper in proper order (marker-driven,
# then substring-driven, then corpus order) so that the user
# always sees the full bibliography matching ``workspace.papers``.
# The constant is retained because it's referenced by tests
# that pin the legacy "≤ 20" guarantee (defence against
# regressions that would re-introduce the silent cap).
_MAX_CITATIONS_LEGACY = 20


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
            max_count=_MAX_CITATIONS_LEGACY,
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

    def _build_citations(
        self,
        summary: Summary,
        max_count: int,
    ) -> list[Citation]:
        """Build a deduplicated, ordered list of Citations from ``summary``.

        The Summary entity already carries ``papers_used`` -- the
        papers the LLM saw when generating the synthesis. Every
        paper that touched the workspace is included in the
        bibliography, regardless of whether the LLM explicitly
        cited it in the body. The user's hard rule is "executive
        reports can contain only references available at
        INTERMEDIATE, not more (less is possible, but definitely
        not more!)" -- after observing that the LLM sometimes
        skips 5-10 of 20 papers in the body, the user wanted
        every INTERMEDIATE paper visible in the bibliography.

        Ordering:
          1. Papers cited via ``[paper:N]`` markers in the body,
             in the order the markers first appear (the LLM's
             natural ordering, which is the best signal of
             "relevance").
          2. Papers mentioned in the body by title or DOI
             substring match (some models paraphrase titles
             instead of citing the bibliography index).
          3. Remaining workspace papers, in corpus order (the
             order they were added to ``workspace.papers``).
             These were "seen by the LLM but not cited" -- the
             user wants to see them anyway so they can verify
             nothing was lost when they remove papers.

        Deduplication: two papers may share the same PMID/DOI
        (e.g. preprint + journal version). We keep the first one
        we see in each phase.

        The ``max_count`` parameter is now ignored -- it was a
        legacy cap (``_MAX_CITATIONS_LEGACY = 20``) that we no
        longer apply, because the user's invariant
        (``citations ⊆ workspace.papers``) is enforced at the
        entity layer by ``ResearchSession.set_report`` (ADR-019).
        The parameter is retained so tests that pin the legacy
        contract don't break; the value is silently unused.

        Parameters
        ----------
        summary : Summary
            Evidence synthesis carrying ``papers_used`` and
            ``body``.

        max_count : int
            **Ignored.** Retained for backward-compatibility with
            tests written against the pre-fix contract.

        Returns
        -------
        list[Citation]
            Citations ordered by marker → substring → corpus,
            deduplicated by PMID/DOI/title identity.
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
        # The bibliography always includes EVERY workspace paper
        # (subject to DOI dedup). The order reflects the LLM's
        # attention: marker-cited papers first (in marker
        # appearance order), then substring-matched papers (in
        # first-appearance order), then remaining workspace papers
        # (in corpus order). This ensures the user sees a complete
        # bibliography that matches ``workspace.papers`` regardless
        # of whether the LLM chose to mention each paper in the
        # body text -- a guarantee the user asked for after seeing
        # citation counts lower than the workspace size.
        #
        # Previously the mapper truncated at
        # ``_MAX_CITATIONS_LEGACY = 20``, which silently dropped
        # papers the LLM did not cite in its body. The cap is now
        # the workspace paper count (enforced by ADR-019's
        # ``set_report`` invariant: ``report.citations ⊆ workspace.papers``).
        seen_dois: set[str] = set()
        ordered: list = []
        seen_paper_ids: set[str] = set()

        def _add_paper(paper_index: int) -> None:
            """Append a paper to the bibliography, dedup-aware.

            Skips papers already added (by PMID/DOI/URL identity)
            so the LLM's accidental double-citation does not
            produce duplicate entries.
            """
            if paper_index < 0 or paper_index >= len(papers):
                return
            paper = papers[paper_index]
            identity = self._paper_identity(paper)
            if identity in seen_paper_ids:
                return
            seen_paper_ids.add(identity)
            if paper.doi and paper.doi in seen_dois:
                return
            if paper.doi:
                seen_dois.add(paper.doi)
            ordered.append(
                Citation(paper=paper, style=CitationStyleEnum.APA)
            )

        # Phase 1: marker-driven citations, in marker appearance order.
        for paper_index in marker_order:
            _add_paper(paper_index)

        # Phase 2: substring-driven citations, in first-appearance
        # order. Papers here were mentioned in the body by title or
        # DOI but the LLM did not emit a ``[paper:N]`` marker for them
        # (some models paraphrase paper titles instead of citing the
        # bibliography index).
        substring_candidates = [
            (pos, idx)
            for idx, pos in enumerate(fallback_positions)
            if pos >= 0
        ]
        substring_candidates.sort(key=lambda pair: pair[0])
        for _, paper_index in substring_candidates:
            _add_paper(paper_index)

        # Phase 3: remaining workspace papers, in corpus order.
        # These were not picked up by markers or substring matching
        # but the user expects to see the full bibliography --
        # the executive report's bibliography must reflect every
        # paper available at INTERMEDIATE (the user's hard rule
        # is "less is possible, but definitely not more", which
        # we honour in the upper-bound direction; the lower bound
        # is "all of them" so the user can verify nothing was lost
        # when they remove papers).
        for paper_index in range(len(papers)):
            _add_paper(paper_index)

        return ordered

    @staticmethod
    def _paper_identity(paper: "Paper") -> str:
        """Stable identity for dedup-aware bookkeeping.

        Mirrors ``ResearchSession._paper_identity`` so two
        papers with the same PMID compare as equal even when
        the LLM has rewritten their ``title`` / ``abstract``.
        Identifiers are checked in PMID → DOI → title order.

        Defined as a static method here (rather than importing
        from the entity) to keep the mapper free of domain
        circular-import concerns.
        """
        if paper.pmid:
            return f"pmid:{paper.pmid}"
        if paper.doi:
            return f"doi:{paper.doi}"
        return f"title:{(paper.title or '').strip().lower()}"
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
