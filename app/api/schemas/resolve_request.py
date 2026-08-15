"""
resolve_request.py

Request/response schemas for the identifier-resolution endpoint.

This endpoint accepts a list of PMIDs and/or DOIs (one per item)
and returns per-identifier feedback so the frontend can show a
green/amber/red status chip next to each entry the user pasted.

The resolver never aborts the batch — one bad identifier returns
a ``FailedResolution`` and the others continue. This matches the
"grant reviewer with 8 references" workflow where one PMID might
be mistyped.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class ResolveIdentifiersRequest(BaseModel):
    """Payload for ``POST /workspaces/{id}/papers/resolve``.

    Attributes
    ----------
    identifiers : list[str]
        PMIDs and/or DOIs to resolve. Mixed formats are accepted.
    """

    model_config = ConfigDict(from_attributes=True)

    identifiers: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description=(
            "One or more PMIDs or DOIs. Mixed formats are accepted "
            "(e.g. [\"40000001\", \"10.1038/s41593-025-00001-1\"])."
        ),
    )


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class ResolvedPaperResponse(BaseModel):
    """Successfully resolved paper.

    Attributes
    ----------
    identifier : str
        The PMID or DOI that was resolved.

    identifier_type : str
        ``"pmid"`` or ``"doi"``.

    paper : PaperResponse
        The full paper metadata.
    """

    identifier: str
    identifier_type: str
    # Imported lazily to avoid a circular import on the schemas
    # package. The actual PaperResponse is filled in by the route.
    paper: dict = Field(default_factory=dict)


class FailedResolutionResponse(BaseModel):
    """An identifier that could not be resolved.

    Attributes
    ----------
    identifier : str
        The PMID or DOI that was attempted.

    reason : str
        Short human-readable explanation.
    """

    identifier: str
    reason: str


class ResolutionEntryResponse(BaseModel):
    """Per-identifier outcome of a resolve batch.

    Exactly one of ``resolved`` or ``failed`` is populated. Use
    ``is_success`` to dispatch on the frontend.
    """

    resolved: ResolvedPaperResponse | None = None
    failed: FailedResolutionResponse | None = None

    @property
    def is_success(self) -> bool:
        return self.resolved is not None


class ResolveIdentifiersResponse(BaseModel):
    """Top-level response for a resolve batch.

    Attributes
    ----------
    results : list[ResolutionEntryResponse]
        One entry per input identifier, in the same order.

    resolved_count : int
        Convenience field with the number of successes.

    failed_count : int
        Convenience field with the number of failures.
    """

    results: list[ResolutionEntryResponse]
    resolved_count: int
    failed_count: int