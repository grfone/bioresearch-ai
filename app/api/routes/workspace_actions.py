"""
workspace_actions.py

REST API endpoints that drive the FSM of a Research Workspace.

Purpose
-------
This module exposes the :class:`WorkspaceOrchestrator` over HTTP.
Each endpoint corresponds to a single FSM action. The endpoint
validates the action against the workspace's current state and
returns the updated workspace.

Endpoints
---------

POST /workspaces/{id}/actions/search
    Run the SEARCH action (PubMed retrieval).

POST /workspaces/{id}/actions/summarize
    Run the SUMMARIZE action (evidence synthesis).

POST /workspaces/{id}/actions/compare
    Run the COMPARE action (cross-paper evidence comparison).

POST /workspaces/{id}/actions/report
    Run the REPORT action (final report generation).

POST /workspaces/{id}/actions/complete
    Mark the workspace as COMPLETED.

POST /workspaces/{id}/actions/retry
    Recover the workspace from the ERROR state.

POST /workspaces/{id}/papers
    Add a paper to the workspace manually. Used by the
    frontend's "Upload paper" form. Legal in any state that
    allows ``add_paper``.

DELETE /workspaces/{id}/papers/{paper_id}
    Remove a paper from the workspace. Legal in any state
    that allows ``remove_paper``.

GET /workspaces/{id}/transitions
    Return the FSM status of the workspace (state, allowed
    actions, history).

GET /workspaces/{id}/evidence-comparison
    Return the stored evidence comparison (if any).

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.schemas.evidence_comparison_response import (
    EvidenceComparisonResponse,
)
from app.api.schemas.paper_request import PaperRequest
from app.api.schemas.resolve_request import (
    FailedResolutionResponse,
    ResolutionEntryResponse,
    ResolveIdentifiersRequest,
    ResolveIdentifiersResponse,
    ResolvedPaperResponse,
)
from app.api.schemas.search_response import PaperResponse
from app.api.schemas.workspace_action_request import (
    WorkspaceActionRequest,
)
from app.api.schemas.workspace_response import WorkspaceResponse
from app.api.schemas.workspace_status_response import (
    WorkspaceStatusResponse,
)
from app.application.services.workspace_orchestrator import (
    WorkspaceOrchestrator,
)
from app.config.container import (
    get_identifier_resolver,
    get_workspace_orchestrator,
)
from app.core.enums.workspace_state import WorkspaceAction
from app.core.exceptions import (
    CitationValidationError,
    IllegalWorkspaceActionError,
)
from app.domain.entities.author import Author
from app.domain.entities.journal import Journal
from app.domain.entities.paper import Paper
from app.infrastructure.pubmed.identifier_resolver import (
    IdentifierResolver,
)


router = APIRouter(
    prefix="/workspaces",
    tags=["Workspace Actions"],
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _to_response(workspace) -> WorkspaceResponse:
    return WorkspaceResponse.from_domain(workspace)


def _illegal_action_response(exc: IllegalWorkspaceActionError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "illegal_workspace_action",
            "message": str(exc),
            "current_state": exc.current_state,
            "action": exc.action,
            "allowed_actions": exc.allowed,
        },
    )


def _run_action(
    orchestrator: WorkspaceOrchestrator,
    workspace_id: UUID,
    action_name: str,
    runner,
) -> WorkspaceResponse:
    try:
        workspace = runner(workspace_id)
    except IllegalWorkspaceActionError as exc:
        raise _illegal_action_response(exc) from exc
    except CitationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "citation_validation_failed",
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _to_response(workspace)


# ----------------------------------------------------------------------
# Action endpoints
# ----------------------------------------------------------------------


@router.post(
    "/{workspace_id}/actions/search",
    response_model=WorkspaceResponse,
    summary="Search PubMed and store the results in the workspace.",
)
def search_action(
    workspace_id: UUID,
    request: WorkspaceActionRequest,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Run the SEARCH action."""
    return _run_action(
        orchestrator,
        workspace_id,
        WorkspaceAction.SEARCH.value,
        lambda wid: orchestrator.search(wid, query=request.query),
    )


@router.post(
    "/{workspace_id}/actions/summarize",
    response_model=WorkspaceResponse,
    summary="Generate an evidence summary from the workspace's papers.",
)
def summarize_action(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Run the SUMMARIZE action."""
    return _run_action(
        orchestrator,
        workspace_id,
        WorkspaceAction.SUMMARIZE.value,
        orchestrator.summarize,
    )


@router.post(
    "/{workspace_id}/actions/compare",
    response_model=WorkspaceResponse,
    summary="Generate a cross-paper evidence comparison.",
)
def compare_action(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Run the COMPARE action."""
    return _run_action(
        orchestrator,
        workspace_id,
        WorkspaceAction.COMPARE.value,
        orchestrator.compare,
    )


@router.post(
    "/{workspace_id}/actions/report",
    response_model=WorkspaceResponse,
    summary="Generate the final research report from the workspace.",
)
def report_action(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Run the REPORT action.

    The report is generated from the workspace's *current* papers
    and summary — it does not re-query PubMed.
    """
    return _run_action(
        orchestrator,
        workspace_id,
        WorkspaceAction.REPORT.value,
        orchestrator.report,
    )


@router.post(
    "/{workspace_id}/actions/complete",
    response_model=WorkspaceResponse,
    summary="Mark the workspace as COMPLETED.",
)
def complete_action(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Run the COMPLETE action."""
    return _run_action(
        orchestrator,
        workspace_id,
        WorkspaceAction.COMPLETE.value,
        orchestrator.complete,
    )


@router.post(
    "/{workspace_id}/actions/retry",
    response_model=WorkspaceResponse,
    summary="Recover from the ERROR state.",
)
def retry_action(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Run the RETRY action."""
    return _run_action(
        orchestrator,
        workspace_id,
        WorkspaceAction.RETRY.value,
        orchestrator.retry,
    )


# ----------------------------------------------------------------------
# Introspection endpoints
# ----------------------------------------------------------------------


@router.get(
    "/{workspace_id}/transitions",
    response_model=WorkspaceStatusResponse,
    summary="Return the FSM status of the workspace.",
)
def transitions(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceStatusResponse:
    """Return the workspace's current FSM state, allowed actions,
    and history."""
    workspace = orchestrator.get_workspace(workspace_id)
    return WorkspaceStatusResponse.from_session(workspace)


@router.get(
    "/{workspace_id}/evidence-comparison",
    response_model=EvidenceComparisonResponse,
    summary="Return the stored evidence comparison.",
)
def evidence_comparison(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> EvidenceComparisonResponse:
    workspace = orchestrator.get_workspace(workspace_id)
    if workspace.evidence_comparison is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No evidence comparison has been generated for this "
                "workspace. Run the COMPARE action first."
            ),
        )
    return EvidenceComparisonResponse.from_domain(
        workspace.evidence_comparison
    )


# ----------------------------------------------------------------------
# Paper management — manual upload and removal
# ----------------------------------------------------------------------
#
# These endpoints let the user add or remove papers without going
# through the SEARCH action. They are useful when the user already
# knows the paper they want to study and does not want to spend
# API quota on a PubMed query. They are also the only way to add
# a paper that is not indexed in PubMed.


def _paper_request_to_domain(payload: PaperRequest) -> Paper:
    """Convert the validated request payload into a domain ``Paper``.

    The domain ``Author`` is keyed on ``first_name`` / ``last_name``
    (its ``full_name`` is a derived property). The request schema
    exposes ``full_name``, ``given_name``, and ``family_name`` so the
    user can supply any combination. We resolve them in this order:

    1. If ``first_name`` and ``last_name`` are both set, use them
       directly.
    2. Else if ``full_name`` is set, split it on the last whitespace
       boundary (so "Maria Del Carmen Garcia" becomes first="Maria
       Del Carmen", last="Garcia").
    3. Else fall back to whatever partial data is available, with
       "Unknown Author" as the last-resort default.
    """
    authors: list[Author] = []
    for a in payload.authors:
        first = (a.given_name or "").strip()
        last = (a.family_name or "").strip()
        full = (a.full_name or "").strip()
        if not first and not last and full:
            parts = full.rsplit(" ", 1)
            first = parts[0]
            last = parts[1] if len(parts) > 1 else ""
        if not first and not last:
            first = "Unknown"
            last = "Author"
        authors.append(Author(
            first_name=first,
            last_name=last,
            affiliation=None,
        ))
    journal = (
        Journal(
            name=payload.journal.name,
            issn=payload.journal.issn,
            publisher=payload.journal.publisher,
        )
        if payload.journal is not None
        else None
    )
    return Paper(
        title=payload.title,
        authors=authors,
        journal=journal,
        year=payload.year,
        abstract=payload.abstract,
        doi=payload.doi,
        pmid=payload.pmid,
        keywords=list(payload.keywords),
        url=payload.url,
    )


@router.post(
    "/{workspace_id}/papers",
    response_model=WorkspaceResponse,
    summary="Add a paper to the workspace manually.",
)
def add_paper(
    workspace_id: UUID,
    payload: PaperRequest,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Persist a user-supplied paper into the workspace.

    The endpoint accepts the same shape as ``PaperRequest`` from the
    API. It validates the payload, converts it to a domain ``Paper``,
    and forwards it to ``WorkspaceOrchestrator.add_paper``.

    The state machine must allow ``add_paper`` in the workspace's
    current state; otherwise the response is HTTP 409 Conflict with
    ``allowed_actions`` in the body (same contract as every other
    action endpoint).
    """
    paper = _paper_request_to_domain(payload)
    try:
        workspace = orchestrator.add_paper(workspace_id, paper)
    except IllegalWorkspaceActionError as exc:
        raise _illegal_action_response(exc) from exc
    return _to_response(workspace)


@router.delete(
    "/{workspace_id}/papers/{paper_id}",
    response_model=WorkspaceResponse,
    summary="Remove a paper from the workspace.",
)
def remove_paper(
    workspace_id: UUID,
    paper_id: str,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Remove a paper by its PMID or DOI.

    Returns HTTP 404 if the paper isn't in the workspace. Returns
    HTTP 409 Conflict if the current state doesn't allow
    ``remove_paper`` (e.g. while a SEARCH is in progress).
    """
    # Snapshot the paper count before the call. If it doesn't
    # change, the paper wasn't in the workspace and we return 404.
    before = len(orchestrator.get_workspace(workspace_id).papers)
    try:
        workspace = orchestrator.remove_paper(workspace_id, paper_id)
    except IllegalWorkspaceActionError as exc:
        raise _illegal_action_response(exc) from exc
    if len(workspace.papers) == before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No paper with PMID/DOI {paper_id!r} in this workspace.",
        )
    return _to_response(workspace)



# ----------------------------------------------------------------------
# Identifier resolution — PMID/DOI auto-fetch
# ----------------------------------------------------------------------
#
# These endpoints exist so the user can paste a PMID or DOI and
# have the system pull the full metadata automatically. The
# previous /papers endpoint required the user to fill in every
# field by hand, which is friction researchers hate. The new
# flow is:
#
# 1. User pastes 8 PMIDs into the "Add Paper" panel.
# 2. Frontend POSTs /papers/resolve and gets a per-identifier
#    status report (green/amber/red).
# 3. User clicks "Add 7 resolved papers" — frontend POSTs the
#    resolved papers to /papers/bulk in one go.
# Or, for the "one PMID and go" workflow, the frontend just
# POSTs /papers/fetch/{pmid} which resolves AND adds in one call.


def _domain_to_response_dict(paper: Paper) -> dict:
    """Convert a domain Paper to the JSON-friendly dict that
    :class:`PaperResponse` expects.

    We use the existing PaperResponse model so the wire format
    matches what /papers/search already returns.
    """
    return PaperResponse.model_validate(paper).model_dump(
        mode="json",
    )


@router.post(
    "/{workspace_id}/papers/resolve",
    response_model=ResolveIdentifiersResponse,
    summary="Resolve PMIDs/DOIs to full paper metadata.",
)
def resolve_identifiers(
    workspace_id: UUID,
    payload: ResolveIdentifiersRequest,
    resolver: IdentifierResolver = Depends(get_identifier_resolver),
) -> ResolveIdentifiersResponse:
    """Resolve a batch of PMIDs and DOIs.

    Returns per-identifier feedback so the frontend can show a
    status chip next to each entry. The endpoint never aborts
    the batch on a single failure; one mistyped PMID returns
    a ``FailedResolution`` and the other identifiers still
    resolve.

    Does not modify the workspace. To actually persist the
    resolved papers, the frontend then POSTs them to
    ``/papers/bulk``.
    """
    del workspace_id  # not needed for read-only resolution
    raw_results = resolver.resolve_many(payload.identifiers)
    entries: list[ResolutionEntryResponse] = []
    resolved_count = 0
    failed_count = 0
    for result in raw_results:
        if result.is_success and result.paper is not None:
            entries.append(
                ResolutionEntryResponse(
                    resolved=ResolvedPaperResponse(
                        identifier=result.paper.identifier,
                        identifier_type=result.paper.identifier_type,
                        paper=_domain_to_response_dict(
                            result.paper.paper,
                        ),
                    )
                )
            )
            resolved_count += 1
        else:
            failure = result.failure
            assert failure is not None  # mypy
            entries.append(
                ResolutionEntryResponse(
                    failed=FailedResolutionResponse(
                        identifier=failure.identifier,
                        reason=failure.reason,
                    )
                )
            )
            failed_count += 1
    return ResolveIdentifiersResponse(
        results=entries,
        resolved_count=resolved_count,
        failed_count=failed_count,
    )


@router.post(
    "/{workspace_id}/papers/bulk",
    response_model=WorkspaceResponse,
    summary="Add several papers to the workspace in one call.",
)
def add_papers_bulk(
    workspace_id: UUID,
    papers: list[PaperRequest],
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Persist a batch of papers in a single transaction.

    Used by the frontend after ``/papers/resolve`` returns the
    resolved metadata. The orchestrator dedupes by PMID/DOI so
    duplicates are silently dropped. Returns the updated
    workspace. HTTP 409 if the current state doesn't allow
    ``add_paper``.
    """
    domain_papers = [_paper_request_to_domain(p) for p in papers]
    try:
        workspace = orchestrator.add_papers_bulk(
            workspace_id, domain_papers,
        )
    except IllegalWorkspaceActionError as exc:
        raise _illegal_action_response(exc) from exc
    return _to_response(workspace)


@router.post(
    "/{workspace_id}/papers/fetch",
    response_model=WorkspaceResponse,
    summary="Resolve one PMID or DOI and add the paper to the workspace.",
)
def resolve_and_add_paper(
    workspace_id: UUID,
    identifier: str = Query(
        ...,
        description="PMID (1-8 digits) or DOI (10.xxxx/yyyy).",
        min_length=1,
        max_length=500,
    ),
    resolver: IdentifierResolver = Depends(get_identifier_resolver),
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """One-shot "add this PMID/DOI" endpoint.

    Resolves the identifier (PMID via PubMed EFetch, DOI via
    CrossRef), then adds the resulting paper to the workspace.
    Returns HTTP 422 if the identifier format is unrecognised,
    HTTP 502 if the upstream API fails, HTTP 409 if the FSM
    forbids ``add_paper`` in the current state.

    The identifier is passed as a query parameter so DOIs
    (which contain ``/``) are accepted without URL-encoding
    gymnastics.
    """
    result = resolver.resolve_one(identifier)
    if result.failure is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "identifier_resolution_failed",
                "reason": result.failure.reason,
                "identifier": result.failure.identifier,
            },
        )
    assert result.paper is not None
    try:
        workspace = orchestrator.add_paper(
            workspace_id, result.paper.paper,
        )
    except IllegalWorkspaceActionError as exc:
        raise _illegal_action_response(exc) from exc
    return _to_response(workspace)
