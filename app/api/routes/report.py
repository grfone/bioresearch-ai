"""
report.py

REST API endpoints for biomedical research report generation.

Purpose
-------
This module exposes the legacy ``POST /reports/generate`` endpoint
that has been retained for backwards compatibility with the
existing frontend.

The endpoint is now a thin wrapper around the
:class:`WorkspaceOrchestrator.report` action. This is the
behaviour change that fixes the original bug: the report is
generated from the workspace's *current* papers and summary,
not from a fresh PubMed search.

New clients should call
``POST /workspaces/{id}/actions/report`` instead.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
import logging

from app.api.schemas.report_request import (
    ReportRequest,
)
from app.api.schemas.report_response import (
    ReportResponse,
)
from app.application.services.workspace_orchestrator import (
    WorkspaceOrchestrator,
)
from app.config.container import get_workspace_orchestrator
from app.core.enums.workspace_state import WorkspaceAction
from app.core.exceptions import IllegalWorkspaceActionError


router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
)

logger = logging.getLogger(__name__)


def get_orchestrator() -> WorkspaceOrchestrator:
    return get_workspace_orchestrator()


@router.post(
    "/generate",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
    summary="(Deprecated) Generate a report from a workspace.",
    description=(
        "This endpoint is deprecated. Use "
        "``POST /workspaces/{id}/actions/report`` instead. "
        "The deprecated endpoint is kept as a thin shim that "
        "delegates to the orchestrator's REPORT action."
    ),
)
def generate_report(
    request: ReportRequest,
    orchestrator: WorkspaceOrchestrator = Depends(get_orchestrator),
) -> ReportResponse:
    """
    Generate a biomedical research report.

    Parameters
    ----------
    request : ReportRequest
        Report generation request payload.

    orchestrator : WorkspaceOrchestrator
        Orchestrator dependency.

    Returns
    -------
    ReportResponse
        Generated biomedical research report.

    Raises
    ------
    HTTPException
        * ``409 Conflict`` if the workspace is in a state that
          doesn't allow REPORT (e.g. ERROR), with the standard
          FSM error envelope.
        * ``400 Bad Request`` for validation failures.
        * ``409 Conflict`` with ``error="report_generation_failed"``
          if the underlying LLM call fails -- the workspace has
          been moved to ``ERROR`` state by the orchestrator and
          ``last_error`` on the response carries the reason. The
          user MUST run ``POST /workspaces/{id}/actions/retry``
          before re-attempting. This is the same shape the
          FSM-aware endpoint returns.
        * ``500 Internal Server Error`` only if ``orchestrator.report``
          completes without raising but produces no report (a
          server-side invariant violation; this branch is the
          legacy code's last-resort fallback).
    """
    try:
        workspace = orchestrator.report(UUID(request.workspace_id))
    except IllegalWorkspaceActionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "illegal_workspace_action",
                "message": str(exc),
                "current_state": exc.current_state,
                "action": WorkspaceAction.REPORT.value,
                "allowed_actions": exc.allowed,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        # The orchestrator's ``report()`` method wraps the
        # LLM/provider call in a try/except that puts the
        # workspace into ERROR and re-raises. We re-fetch the
        # session so we can surface the resulting ``last_error``
        # to the caller -- the user needs to know WHAT went
        # wrong, not just that something did.
        #
        # Without this catch, the unhandled exception would
        # bubble to FastAPI's default handler and return a
        # bare ``500 Internal Server Error`` with no actionable
        # information. That's the bug the live verify surfaced:
        # the user saw 500, then clicked Retry, then saw 409
        # -- but never learned WHY the first request failed or
        # WHAT to do next. A 409 with ``last_error`` + the
        # standard FSM envelope tells the frontend everything
        # it needs to render a useful error message.
        #
        # This is a deprecated endpoint, but it MUST still
        # behave correctly because the existing frontend
        # ``generateReport`` API call uses it. The fix is to
        # match the FSM-aware endpoint's contract (see
        # ``app/api/routes/workspace_actions.py::report_action``).
        logger.exception(
            "Legacy /reports/generate failed for workspace %s",
            request.workspace_id,
        )
        try:
            failed = orchestrator.get_workspace(
                UUID(request.workspace_id)
            )
        except Exception:
            # If the post-failure refetch itself fails (very
            # unlikely -- the orchestrator just persisted the
            # ERROR state) we don't want to mask the original
            # error. Fall back to a generic 500 with the
            # exception type so the user at least knows what
            # went wrong.
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
                # The workspace is in ERROR; the only legal
                # next move is RETRY. We surface this so the
                # frontend can render a "Click RETRY" CTA
                # instead of letting the user click Generate
                # again and get another 409.
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
        workspace_id=request.workspace_id,
        report=workspace.report,
    )
