"""
report_request.py

API request schema for biomedical research report generation.

This module defines the request model accepted by the report generation
endpoint.

A report is generated from the current state of an existing Research
Workspace. Consequently, this request does not contain the scientific
literature itself. Instead, it identifies the workspace and specifies
optional report generation preferences.

Request schemas belong to the Presentation layer and are responsible for
validating incoming HTTP payloads before they are converted into domain
objects.

The ReportRequest intentionally contains no business logic. It defines
the contract between API clients and the BioResearch AI backend.

Architecture
------------

        HTTP Request
              │
              ▼
        ReportRequest
              │
              ▼
    GenerateReportUseCase
              │
              ▼
      ResearchReport

Future versions may support additional options including:

- report templates;
- citation styles;
- report language;
- report length;
- evidence confidence thresholds;
- target audience (researcher, clinician, patient);
- export formats (Markdown, PDF, DOCX, HTML).

Author
------
Guillermo Ramajo Fernández
"""

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class ReportRequest(BaseModel):
    """
    Request model used to generate a biomedical research report.

    A report summarizes the current evidence contained within a Research
    Workspace. The request specifies which workspace should be used and
    optionally customizes how the report should be produced.

    Attributes
    ----------
    workspace_id : str
        Unique identifier of the Research Workspace.

    include_limitations : bool
        Whether the generated report should explicitly discuss known
        limitations of the available evidence.

    include_future_work : bool
        Whether the report should include suggested future research
        directions.

    Examples
    --------
    {
        "workspace_id": "e8b94af1-4e72-46d7-a3db-f9ec22bb58f3",
        "include_limitations": true,
        "include_future_work": true
    }
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    workspace_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Unique identifier of the Research Workspace used to "
            "generate the report."
        ),
        examples=[
            "e8b94af1-4e72-46d7-a3db-f9ec22bb58f3"
        ],
    )

    include_limitations: bool = Field(
        default=True,
        description=(
            "Include a section discussing the limitations of the "
            "available scientific evidence."
        ),
    )

    include_future_work: bool = Field(
        default=True,
        description=(
            "Include recommended future research directions."
        ),
    )