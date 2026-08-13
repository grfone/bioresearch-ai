"""
finding.py

Domain value objects representing single evidence findings and
contradictions extracted from a literature comparison.

These objects are intentionally minimal. They are the atomic units
of the evidence comparison and are always bound to one or more
paper IDs from the input set. The CitationValidator (in
application/validation) ensures that any cited paper_id was
actually part of the workspace.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class Finding:
    """
    A single factual observation supported by one or more papers.

    A Finding is a *value object*. It is immutable and bound to the
    paper IDs that support it. The ``evidence_strength`` field is a
    qualitative descriptor (e.g. "strong", "moderate", "weak") that
    the LLM is asked to assign and that the validation pipeline
    normalises.

    Attributes
    ----------
    claim : str
        A short, factual statement of the finding.

    paper_ids : list[str]
        PubMed IDs (or DOIs as fallback) of the papers that support
        the claim. The list is unordered and may contain duplicates
        that the validator dedupes.

    evidence_strength : str | None
        Optional qualitative strength assessment. Expected values are
        "strong", "moderate", "weak", or None. The validator does not
        enforce a closed vocabulary — it is normalised to lowercase.

    notes : str | None
        Optional free-text annotation provided by the LLM to clarify
        the finding.
    """

    claim: str
    paper_ids: list[str] = field(default_factory=list)
    evidence_strength: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        # Normalise paper IDs in place. The dataclass is frozen so a
        # direct mutation is impossible; we instead rebuild the field
        # via object.__setattr__ during construction.
        normalised = []
        seen: set[str] = set()
        for pid in self.paper_ids:
            pid = str(pid).strip()
            if not pid or pid in seen:
                continue
            seen.add(pid)
            normalised.append(pid)
        object.__setattr__(self, "paper_ids", normalised)

        if self.evidence_strength is not None:
            object.__setattr__(
                self,
                "evidence_strength",
                self.evidence_strength.strip().lower(),
            )


@dataclass(slots=True, frozen=True)
class Contradiction:
    """
    A documented disagreement between two or more papers.

    Like :class:`Finding`, a Contradiction is a value object bound to
    the paper IDs that participate in the disagreement. The ``topic``
    field is a short label (e.g. "GLP-1 efficacy on cognition") used
    to group contradictions in the UI.

    Attributes
    ----------
    topic : str
        Short label describing what the contradiction is about.

    description : str
        Human-readable description of the disagreement.

    paper_ids : list[str]
        Paper IDs that participate in the contradiction.

    severity : str | None
        Optional qualitative label ("minor", "major") used by the UI
        to highlight critical disagreements.
    """

    topic: str
    description: str
    paper_ids: list[str] = field(default_factory=list)
    severity: str | None = None

    def __post_init__(self) -> None:
        normalised = []
        seen: set[str] = set()
        for pid in self.paper_ids:
            pid = str(pid).strip()
            if not pid or pid in seen:
                continue
            seen.add(pid)
            normalised.append(pid)
        object.__setattr__(self, "paper_ids", normalised)

        if self.severity is not None:
            object.__setattr__(
                self,
                "severity",
                self.severity.strip().lower(),
            )
