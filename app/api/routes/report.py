"""
report.py

REST API endpoints for biomedical research report generation.

Purpose
-------
This module exposes HTTP endpoints responsible for generating structured
biomedical research reports from existing Research Workspaces.

A report represents the final synthesis stage of the BioResearch AI
workflow:

1. Retrieve scientific literature.
2. Analyze and summarize evidence.
3. Generate a structured scientific report.

The API layer is responsible only for:

- HTTP request handling.
- Request validation.
- Dependency injection.
- Response serialization.
- Exception translation.

All research logic remains inside the application layer.

Architecture
------------

              HTTP Client
                   |
                   |
             FastAPI Router
                   |
                   |
          ResearchAssistant
                   |
                   |
        GenerateReportUseCase
                   |
                   |
          ReportGenerator
                   |
                   |
           ResearchReport


Endpoints
---------

POST /reports/generate

    Generate a biomedical research report from a Research Workspace.


Future versions may support:

- report regeneration;
- report versioning;
- multiple report formats;
- PDF/DOCX export;
- reviewer workflows;
- collaborative annotations.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations


from uuid import UUID


from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status


from app.api.schemas.report_request import (
    ReportRequest,
)

from app.api.schemas.report_response import (
    ReportResponse,
)


from app.application.services.research_assistant import (
    ResearchAssistant,
)


from app.config.container import Container



router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
)



def get_research_assistant() -> ResearchAssistant:
    """
    Provide a configured ResearchAssistant instance.

    This dependency creates the application facade used by the
    presentation layer.

    Returns
    -------
    ResearchAssistant
        Fully configured application facade.
    """

    return Container.build()



@router.post(
    "/generate",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_report(
    request: ReportRequest,
    assistant: ResearchAssistant = Depends(
        get_research_assistant
    ),
) -> ReportResponse:
    """
    Generate a biomedical research report.

    The endpoint receives an existing Research Workspace identifier,
    retrieves the corresponding workspace, and executes the report
    generation workflow.

    Workflow
    --------
    1. Retrieve workspace.
    2. Extract research question.
    3. Generate evidence-based report.
    4. Serialize report response.

    Parameters
    ----------
    request
        Report generation request payload.

    assistant
        Application facade dependency.

    Returns
    -------
    ReportResponse
        Generated biomedical research report.

    Raises
    ------
    HTTPException
        404
            Workspace does not exist.

        400
            Report generation failed.
    """

    try:

        workspace = assistant.get_workspace(
            UUID(request.workspace_id)
        )


        report = assistant.generate_report(
            workspace.question.question
        )


        return ReportResponse.from_domain(
            workspace_id=request.workspace_id,
            report=report,
        )


    except ValueError as exc:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


    except Exception as exc:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )