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

    if workspace.report is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Report generation produced no report.",
        )

    return ReportResponse.from_domain(
        workspace_id=request.workspace_id,
        report=workspace.report,
    )
