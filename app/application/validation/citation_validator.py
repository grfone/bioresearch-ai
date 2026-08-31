"""
citation_validator.py

Application-layer validator that enforces the "no fabricated citations"
invariant of BioResearch AI.

Purpose
-------
The LLM is given a closed set of papers and instructed to cite only
those papers. The validator is the second half of that contract: it
takes an AI-generated artefact (an EvidenceComparison, a
ResearchReport, an EvidenceMatrix) and verifies that every paper
ID it references actually belongs to the input set.

This is the difference between a system that *hopes* the LLM behaves
and a system that *enforces* it. Without the validator, the response
of the LLM is taken at face value; with it, fabricated citations are
rejected deterministically.

The validator is a pure application component. It knows about
domain entities but never about LLM providers, HTTP, or persistence.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from typing import Iterable

from app.core.exceptions import CitationValidationError
from app.domain.entities.citation import Citation
from app.domain.entities.finding import Contradiction, Finding
from app.domain.entities.paper import Paper
from app.domain.entities.research_report import ResearchReport


class CitationValidator:
    """
    Enforce that every cited paper is part of the workspace's paper set.

    The validator is constructed from a list of papers (typically the
    workspace's papers at the time of generation). It then exposes
    two methods that validate the two artefacts the LLM can
    produce:

    - ``validate_finding`` — the finding's paper IDs must be in the set.
    - ``validate_report`` — every citation's paper must be in the set.

    The cross-paper ``EvidenceComparison`` artefact that used to
    live between summary and report was removed on 2026-08-30
    (see the FSM diagram in ``app/core/enums/workspace_state.py``).
    ``validate_evidence_comparison`` and
    ``validate_evidence_matrix`` are gone with it.

    On violation, the validator raises :class:`CitationValidationError`
    with a list of offending paper IDs. The orchestrator can then
    decide whether to retry, log, or surface the failure to the user.
    """

    def __init__(self, papers: Iterable[Paper]) -> None:
        """
        Build the validator from the input paper set.

        Parameters
        ----------
        papers : Iterable[Paper]
            Papers that were passed to the LLM as context. These
            define the closed set of allowed citations.
        """
        self._allowed_ids: set[str] = set()
        for paper in papers:
            if paper.pmid:
                self._allowed_ids.add(f"pmid:{paper.pmid}")
            if paper.doi:
                self._allowed_ids.add(f"doi:{paper.doi}")
        # Bare PMID/DOI form is also accepted so the LLM can use
        # shorthand. The validator prefers the prefixed form but
        # tolerates the bare form.
        self._allowed_bare: set[str] = set()
        for paper in papers:
            if paper.pmid:
                self._allowed_bare.add(paper.pmid)
            if paper.doi:
                self._allowed_bare.add(paper.doi)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_allowed(self, paper_id: str) -> bool:
        """
        Return whether a paper ID is in the allowed set.

        Accepted forms:

        - ``pmid:12345`` (preferred)
        - ``doi:10.1234/...``
        - bare PMID or DOI (with or without a prefix in the actual
          paper's identifiers)

        Parameters
        ----------
        paper_id : str
            The paper identifier to check.

        Returns
        -------
        bool
            True if the ID is in the allowed set.
        """
        pid = paper_id.strip()
        if not pid:
            return False
        if pid in self._allowed_ids:
            return True
        if pid in self._allowed_bare:
            return True
        # Tolerate the LLM stripping the prefix.
        if ":" in pid:
            bare = pid.split(":", 1)[1]
            if bare in self._allowed_bare:
                return True
        return False

    def validate_finding(self, finding: Finding) -> None:
        """
        Validate that a finding's paper IDs are in the allowed set.

        Raises
        ------
        CitationValidationError
            If any cited paper ID is not in the allowed set.
        """
        self._validate_ids(finding.paper_ids, context=f"finding '{finding.claim!r}'")

    def validate_contradiction(
        self,
        contradiction: Contradiction,
    ) -> None:
        """
        Validate that a contradiction's paper IDs are in the allowed set.

        Raises
        ------
        CitationValidationError
            If any cited paper ID is not in the allowed set.
        """
        self._validate_ids(
            contradiction.paper_ids,
            context=f"contradiction '{contradiction.topic!r}'",
        )

    def validate_report(self, report: ResearchReport) -> None:
        """
        Validate that every citation in a ResearchReport is allowed.

        Raises
        ------
        CitationValidationError
            If any citation's paper is not in the allowed set.
        """
        for citation in report.citations:
            self._validate_citation(citation)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_ids(
        self,
        ids: Iterable[str],
        *,
        context: str,
    ) -> None:
        offenders = [
            pid for pid in ids if not self.is_allowed(pid)
        ]
        if offenders:
            raise CitationValidationError(
                f"Cited paper IDs not present in the workspace's paper set "
                f"({context}): {sorted(set(offenders))}"
            )

    def _validate_citation(self, citation: Citation) -> None:
        paper = citation.paper
        if self.is_allowed(paper.pmid or "") or self.is_allowed(paper.doi or ""):
            return
        identifier = paper.pmid or paper.doi or paper.title
        raise CitationValidationError(
            f"Citation refers to paper not in the workspace's paper set: "
            f"{identifier!r}"
        )
