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

import logging
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from app.api.schemas.evidence_comparison_response import (
    EvidenceComparisonResponse,
)
from app.api.schemas.find_by_title_request import FindByTitleRequest
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
from app.api.schemas.report_response import ReportResponse
from app.api.schemas.workspace_response import WorkspaceResponse
from app.api.schemas.workspace_status_response import (
    WorkspaceStatusResponse,
)
from app.application.services.workspace_orchestrator import (
    WorkspaceOrchestrator,
)
from app.config.literature import literature_settings
from app.config.container import (
    get_identifier_resolver,
    get_workspace_orchestrator,
)
from app.config.literature import literature_settings
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
from app.infrastructure.pubmed.pdf_extractor import (
    extract_identifiers_from_pdf,
)
from app.infrastructure.pubmed.pdf_structured_extractor import (
    extract_paper_from_pdf as extract_structured_paper_from_pdf,
)


router = APIRouter(
    prefix="/workspaces",
    tags=["Workspace Actions"],
)

logger = logging.getLogger(__name__)


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
    summary="Search literature and store the results in the workspace.",
)
def search_action(
    workspace_id: UUID,
    request: WorkspaceActionRequest,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Run the SEARCH action.

    Two shapes are accepted:

    1. **Legacy single-source search** — only ``query`` in
       the body. Routes through
       :meth:`WorkspaceOrchestrator.search` and uses the
       default source set (PubMed + OpenAlex + Europe PMC
       by default).

    2. **Advanced search** — full ``filters`` block in the
       body. Routes through
       :meth:`WorkspaceOrchestrator.search_with_filters`
       and respects the user's source selection, year
       bounds, sort, open-access flag, and document-type
       filter.
    """
    # Advanced search path — caller supplied the full filter
    # bundle. We build a domain ``SearchFilters`` from the
    # Pydantic shape, then dispatch through
    # ``search_with_filters``. If the user also passed a
    # top-level ``query``, that wins for the actual question
    # text (the filters block's ``query`` is set to the
    # workspace's existing question by the orchestrator).
    if request.filters is not None:
        from app.core.enums.search_source import SearchSource
        from app.domain.value_objects.search_filters import (
            SearchDocumentType,
            SearchFilters,
            SortBy,
        )

        # Resolve the actual query text. The legacy ``query``
        # field is preferred; fall back to the workspace's
        # existing question. If neither is set, return a 400
        # so the user gets a clear error rather than a silent
        # empty-search.
        query_text = (request.query or "").strip()
        if not query_text:
            try:
                workspace = orchestrator.get_workspace(workspace_id)
                query_text = workspace.question.question
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Either ``query`` or a workspace with "
                        "an existing question is required for "
                        "advanced search."
                    ),
                ) from exc

        filters_dict = request.filters.model_dump(exclude={"query"})
        # Translate API strings to domain enums.
        filters = SearchFilters(
            query=query_text,
            since_year=filters_dict.get("since_year"),
            until_year=filters_dict.get("until_year"),
            max_results=filters_dict.get("max_results", 20),
            sort_by=SortBy(filters_dict.get("sort_by", "relevance")),
            include_abstracts=filters_dict.get(
                "include_abstracts", True
            ),
            open_access_only=filters_dict.get("open_access_only", False),
            document_types=tuple(
                SearchDocumentType(t)
                for t in filters_dict.get("document_types", [])
            ),
        )
        sources = (
            [SearchSource(s) for s in request.filters.sources]
            if request.filters.sources
            else None
        )
        return _run_action(
            orchestrator,
            workspace_id,
            WorkspaceAction.SEARCH.value,
            lambda wid: orchestrator.search_with_filters(
                wid, filters=filters, sources=sources
            ),
        )

    # Legacy path — just ``query``.
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
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate the final research report from the workspace.",
)
def report_action(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> ReportResponse:
    """Run the REPORT action and return the rendered report.

    The report is generated from the workspace's *current* papers
    and summary — it does not re-query PubMed.

    Response shape
    --------------
    Unlike the other FSM action endpoints (which return
    ``WorkspaceResponse`` so the React frontend can mirror state
    via ``setCurrentWorkspace``), this endpoint returns the
    canonical ``ReportResponse`` shape -- the same one the
    legacy ``/reports/generate`` endpoint returns. The split is
    intentional: the *action surface* is FSM-aware (so we get
    proper 409 / ``last_error`` envelopes), but the *data
    surface* is the report content (because the page renders
    it directly via ``setReport(result)`` rather than reading
    ``currentWorkspace.report``).

    The FSM contract is still enforced end-to-end: a REPORT
    from an illegal state returns ``409`` with the standard
    FSM envelope, and an orchestrator crash returns ``409``
    with ``error="report_generation_failed"`` +
    ``last_error`` + ``allowed_actions``. See
    ``test_publish_action_*`` in ``tests/integration/test_api_fsm.py``
    and the v4 schema migration in ``sqlite_workspace_repository.py``
    for the audit trail.

    Returns
    -------
    ReportResponse
        The generated report (workspace_id, summary text,
        citations, limitations, future_work, generated_at).

    Raises
    ------
    HTTPException
        * ``409 Conflict`` (illegal_workspace_action) if the
          FSM doesn't allow REPORT from the current state.
        * ``409 Conflict`` (report_generation_failed) if the
          LLM call crashes; ``last_error`` carries the
          orchestrator's reason.
        * ``400 Bad Request`` for validation errors.
    """
    try:
        workspace = orchestrator.report(workspace_id)
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
    except Exception as exc:
        # Mirror the legacy endpoint's recovery pattern
        # (see ``app/api/routes/report.py`` -- the ``b900965``
        # bug fix). The orchestrator's ``report()`` already
        # moved the workspace to ERROR before re-raising, so
        # we re-fetch to surface ``last_error`` in the
        # envelope. Without this catch, the user would see a
        # bare 500 (FastAPI's default handler) and lose
        # actionable context.
        logger.exception(
            "FSM /actions/report failed for workspace %s", workspace_id
        )
        try:
            failed = orchestrator.get_workspace(workspace_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "report_generation_failed",
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "report_generation_failed",
                "message": str(exc),
                "current_state": failed.state.value,
                "last_error": failed.last_error,
                "action": WorkspaceAction.REPORT.value,
                "allowed_actions": [
                    a.value for a in failed.allowed_actions()
                ],
            },
        ) from exc

    if workspace.report is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Report generation produced no report.",
        )

    return ReportResponse.from_domain(
        workspace_id=str(workspace_id),
        report=workspace.report,
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
    "/{workspace_id}/actions/publish",
    response_model=WorkspaceResponse,
    summary="Publish the workspace's report as a PDF.",
)
def publish_action(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Run the PUBLISH action.

    Renders the workspace's final report as a PDF and persists
    the bytes on the session. The workspace advances through
    ``PUBLISHING`` to the terminal ``COMPLETED`` state.

    This is the document-export step -- after PUBLISH succeeds,
    the user can download the PDF via
    ``GET /workspaces/{id}/published-report.pdf``.

    Legal from REPORTED only. Any other starting state returns
    409 with the FSM error envelope. PUBLISH is irreversible
    in the sense that it overwrites any previously-published
    PDF, but the workspace's report itself is preserved (the
    user can still re-run REPORT to regenerate the markdown).

    See ADR-009 for the FSM audit + the four-layer pattern
    that drove this endpoint.
    """
    return _run_action(
        orchestrator,
        workspace_id,
        WorkspaceAction.PUBLISH.value,
        orchestrator.publish,
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


@router.get(
    "/{workspace_id}/published-report.pdf",
    summary="Download the published PDF.",
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": (
                "The rendered PDF produced by the PUBLISH action."
            ),
        },
        404: {
            "description": (
                "No PDF has been published for this workspace yet. "
                "Run the PUBLISH action first."
            ),
        },
    },
)
def published_report_pdf(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> Response:
    """Serve the workspace's published PDF as ``application/pdf``.

    This is the download companion to ``POST /workspaces/{id}/actions/publish``.
    The PDF is generated by the PUBLISH action and stored on the
    session as ``session.published_report``. We serve it from the
    session directly -- no on-demand re-render -- so the bytes
    the user downloads are exactly what the publish step
    produced (deterministic for a given report).

    Response shape
    --------------
    - HTTP 200 with ``Content-Type: application/pdf``,
      ``Content-Length: <byte_size>``, and a
      ``filename="report-<workspace_id>.pdf"`` disposition.
    - HTTP 404 if the workspace has not been published yet (no
      PDF on the session). The error message tells the user which
      action to run first.

    Caching
    -------
    ``Cache-Control: no-store`` because the PDF is regenerated
    on every PUBLISH call (a re-publish overwrites the bytes).
    Browsers won't serve a stale copy.

    Note
    ----
    This endpoint is *not* part of the FSM action surface -- it
    doesn't mutate any state. It sits alongside
    ``GET /workspaces/{id}/evidence-comparison`` which is also
    a read-only download of stored artefacts.
    """
    workspace = orchestrator.get_workspace(workspace_id)
    if workspace.published_report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No PDF has been published for this workspace yet. "
                "POST /workspaces/{workspace_id}/actions/publish "
                "first to render the report as a PDF."
            ),
        )

    pdf = workspace.published_report
    return Response(
        content=pdf.pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="report-{workspace_id}.pdf"'
            ),
            "Content-Length": str(pdf.byte_size),
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{workspace_id}/published-report.tex",
    summary="Download the published LaTeX source.",
    responses={
        200: {
            "content": {"text/x-tex": {}},
            "description": (
                "The rendered LaTeX source produced by the "
                "PUBLISH action. Compile with ``pdflatex "
                "report.tex && pdflatex report.tex`` "
                "(twice) to produce the final PDF."
            ),
        },
        404: {
            "description": (
                "No report has been generated for this "
                "workspace yet. Run the REPORT action first."
            ),
        },
    },
)
def published_report_tex(
    workspace_id: UUID,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> Response:
    """
    Serve the workspace's report as a LaTeX source file.

    This endpoint is the LaTeX counterpart to
    ``GET /workspaces/{id}/published-report.pdf``. It
    renders the workspace's final report on demand -- no
    FSM state change, no caching (the workspace's report
    is small and the rendering is fast).

    The output is a complete, self-contained ``.tex``
    file with:

    - ``\\documentclass[11pt,a4paper]{article}``
    - ``\\usepackage[utf8]{inputenc}`` for Unicode
      (β, é, etc.)
    - ``\\usepackage{hyperref}`` so ``[N]`` references
      are clickable in the compiled PDF
    - ``\\begin{document}`` ... ``\\end{document}``

    The user can edit the source in their favourite
    LaTeX editor (Overleaf, TeXstudio, etc.) and
    recompile.

    Response shape
    --------------
    - HTTP 200 with ``Content-Type: text/x-tex`` and
      ``filename="report-<workspace_id>.tex"``.
    - HTTP 404 if the workspace has no report yet (the
      REPORT action has not been run).

    Caching
    -------
    ``Cache-Control: no-store`` because the LaTeX is
    rendered on demand. (Unlike the PDF, we don't cache
    the LaTeX -- the rendering is fast and the file is
    text -- but no caching means the user always gets
    the latest report version.)
    """
    workspace = orchestrator.get_workspace(workspace_id)
    if workspace.report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No report has been generated for this "
                "workspace yet. POST /workspaces/{id}/actions/report "
                "first to generate the report."
            ),
        )

    # Render the LaTeX on demand. The rendering is
    # ~tens of milliseconds for typical reports; the
    # workspace's report is small enough that no
    # caching is needed.
    from app.infrastructure.latex.latex_generator import (
        LatexReportGenerator,
    )
    tex_source = LatexReportGenerator().generate(workspace.report)
    tex_bytes = tex_source.encode("utf-8")

    return Response(
        content=tex_bytes,
        media_type="text/x-tex; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="report-{workspace_id}.tex"'
            ),
            "Content-Length": str(len(tex_bytes)),
            "Cache-Control": "no-store",
        },
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



# ----------------------------------------------------------------------
# PDF upload — extract DOI/PMID from the first page of a user-
# supplied PDF, resolve via the existing IdentifierResolver, and
# add the resulting paper to the workspace.
#
# This is the user-visible "drag a PDF onto the workspace" flow.
# The extractor is intentionally lightweight (no ML, no OCR) —
# it reads the first page text with pypdf and sweeps DOI / PMID
# patterns. Scanned PDFs come back with an empty identifiers
# list and the user is told to use the PMID/DOI tab instead.
# ----------------------------------------------------------------------


# PDF upload size cap. The original hardcoded 10 MB cap was
# too small for legitimate research papers (a 21 MB thesis
# chapter is a perfectly normal input). The default is now
# 200 MB to accommodate large annotated reviews and book
# chapters; operators can lower it via ``PDF_UPLOAD_MAX_BYTES``
# in .env if they need a tighter cap.
#
# Note: this constant is set at startup from
# ``LiteratureSettings.pdf_upload_max_bytes``. The hard cap
# (``_PDF_UPLOAD_MAX_BYTES_HARD_CAP``) below prevents a
# misconfigured env var from opening the door to resource
# exhaustion -- a 10 GB file would OOM the container.
_PDF_UPLOAD_MAX_BYTES_HARD_CAP = 200 * 1024 * 1024  # 200 MB
_PDF_UPLOAD_MAX_BYTES: int = min(
    _PDF_UPLOAD_MAX_BYTES_HARD_CAP,
    max(0, int(literature_settings.pdf_upload_max_bytes)),
)


@router.post(
    "/{workspace_id}/papers/from-pdf",
    response_model=WorkspaceResponse,
    summary="Extract DOI/PMID from a PDF and add the paper to the workspace.",
)
async def add_paper_from_pdf(
    workspace_id: UUID,
    file: UploadFile = File(
        ...,
        description="PDF file to extract identifiers from. "
                    "Max 200 MB by default; configurable via the "
                    "PDF_UPLOAD_MAX_BYTES env var (hard ceiling "
                    "200 MB). The first page is scanned for "
                    "DOI (10.xxxx/...) and PMID patterns.",
    ),
    resolver: IdentifierResolver = Depends(get_identifier_resolver),
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Upload a PDF, extract DOI/PMID from the first page, and
    add the resolved paper to the workspace.

    Returns HTTP 422 if the PDF can't be parsed, has no DOI/PMID
    on the first page, or the identifier fails to resolve. Returns
    HTTP 413 if the file is larger than the configured cap
    (default 200 MB, hard ceiling 200 MB). Returns HTTP 409 if the
    current state doesn't allow ``add_paper``.
    """
    if file.content_type and not file.content_type.startswith("application/pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type {file.content_type!r}. "
                "Only application/pdf is accepted."
            ),
        )

    raw = await file.read()
    if len(raw) > _PDF_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"PDF is {len(raw)} bytes; the max is "
                f"{_PDF_UPLOAD_MAX_BYTES}. Split it or use the "
                "PMID/DOI tab instead."
            ),
        )

    # Extract identifiers from the first page(s).
    import io

    try:
        extraction = extract_identifiers_from_pdf(io.BytesIO(raw))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "pdf_read_failed",
                "message": str(exc),
            },
        ) from exc

    # Resolve the extracted identifiers through the same
    # pipeline that the bulk-paste flow uses.
    results = resolver.resolve_many(extraction.identifiers)
    resolved_papers = [
        result.paper.paper for result in results if result.is_success
    ]

    if not resolved_papers:
        # External lookup failed (or there were no
        # identifiers to look up). The user uploaded the PDF
        # for a reason — they want the paper in the workspace.
        # Fall back to structured extraction from the PDF
        # text itself. The :class:`PaperCard` component
        # renders a partial-metadata marker for thin papers
        # so the user knows what they're getting.
        structured = extract_structured_paper_from_pdf(
            io.BytesIO(raw),
            max_pages=1,
        )
        if structured is None or not structured.paper.title.strip():
            # Surface every failure so the user can see which
            # identifier broke AND why the structured fallback
            # didn't yield a title.
            failed = [
                {
                    "identifier": result.failure.identifier,
                    "reason": result.failure.reason,
                }
                for result in results
                if result.failure is not None
            ]
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "all_identifiers_failed",
                    "message": (
                        "Found identifiers in the PDF but none of "
                        "them resolved via PubMed or CrossRef, and "
                        "the PDF text didn't contain a recognisable "
                        "title for fallback extraction."
                    ),
                    "extracted": extraction.identifiers,
                    "failures": failed,
                    "extracted_text_preview": (
                        extraction.pdf_text[:500]
                        if not structured
                        else ""
                    ),
                },
            )
        # Use the structured paper as the fallback. We surface
        # a header so the frontend can flag it as "no external
        # metadata — partial data from the PDF".
        papers_to_add = [structured.paper]
        pdf_fallback_used = True
    else:
        papers_to_add = resolved_papers
        pdf_fallback_used = False

    # Add to workspace via the bulk path. The orchestrator
    # dedupes by PMID/DOI, so uploading the same PDF twice is a
    # no-op.
    try:
        workspace = orchestrator.add_papers_bulk(
            workspace_id, papers_to_add,
        )
    except IllegalWorkspaceActionError as exc:
        raise _illegal_action_response(exc) from exc

    if pdf_fallback_used:
        # Tell the caller the paper was added from PDF text
        # only, with no external metadata. The PaperCard's
        # partial-metadata marker will surface this visually.
        logger.info(
            "PDF upload for workspace %s fell back to "
            "structured extraction (no CrossRef/PubMed match); "
            "added paper title=%r doi=%r",
            workspace_id,
            papers_to_add[0].title,
            papers_to_add[0].doi,
        )

    return _to_response(workspace)


# ---------------------------------------------------------------------------
# Title-driven paper recovery
# ---------------------------------------------------------------------------
# When the user's PDF didn't contain a recognisable DOI or PMID on the
# first page (e.g. a scanned PDF, a citation from a non-PubMed source),
# ``/papers/from-pdf`` returns ``422 no_identifiers_found``. The frontend
# then offers to recover the paper by title: the user types the title,
# we hit PubMed ESearch with that title, take the top match, and add it
# to the workspace via the same ``add_papers_bulk`` path used by the
# DOI/PMID flow.
#
# Returns the updated workspace, plus an ``X-Matched-Paper`` header so
# the frontend can show the user which paper we picked before it lands
# in the workspace.


@router.post(
    "/{workspace_id}/papers/from-title",
    response_model=WorkspaceResponse,
    summary="Find a paper by title and add it to the workspace.",
)
def add_paper_by_title(
    workspace_id: UUID,
    payload: FindByTitleRequest,
    orchestrator: WorkspaceOrchestrator = Depends(
        get_workspace_orchestrator
    ),
) -> WorkspaceResponse:
    """Resolve a paper by title and add it.

    The user types a paper title (and optionally a first author,
    journal, or year for disambiguation). We feed those to PubMed's
    ESearch, take the top match, and persist it through the standard
    ``ADD_PAPER`` flow.

    Returns HTTP 422 if PubMed returns no candidates. Returns HTTP 502
    if the upstream search fails. Returns HTTP 409 if the FSM forbids
    ``add_paper`` in the current state.
    """
    try:
        session, matched = orchestrator.resolve_and_add_by_title(
            workspace_id=workspace_id,
            title=payload.title,
            first_author=payload.first_author,
            journal=payload.journal,
            year=payload.year,
        )
    except IllegalWorkspaceActionError as exc:
        raise _illegal_action_response(exc) from exc

    # If we couldn't pin a confident match, leave the workspace
    # untouched and return 422 with the search reason. The frontend
    # treats this as a "no precise match" surface and prompts the user
    # to tighten the title or fall back to the PMID/DOI tab.
    if matched is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "title_no_confident_match",
                "message": (
                    "PubMed returned no paper that matched the "
                    "supplied title (and optional author / journal "
                    "/ year). Try a different wording or paste the "
                    "PMID directly in the first tab."
                ),
            },
        )

    # The frontend reads ``matched.title`` from the workspace
    # response (it's the new entry in ``workspace.papers``) and
    # uses it for the toast. We return the updated workspace so
    # the React state stays a single source of truth.
    _ = matched  # silence "unused" — kept for the API contract

    return _to_response(session)
