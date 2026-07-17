"""
workspace_request.py

API request schema for creating and managing Research Workspaces.

A Research Workspace represents a complete biomedical investigation.
Unlike individual endpoints such as literature search or report generation,
the workspace is designed to persist the state of an entire research
session.

Request schemas belong to the Presentation layer and are responsible for
validating incoming HTTP payloads before converting them into domain
entities.

The WorkspaceRequest intentionally contains no business logic. It merely
defines the contract between API clients and the BioResearch AI backend.

Architecture
------------

        HTTP Request
              │
              ▼
      WorkspaceRequest
              │
              ▼
      ResearchQuestion
              │
              ▼
      ResearchSession

Future versions of this schema may support additional configuration
options including:

- preferred LLM provider;
- preferred literature databases;
- maximum retrieved papers;
- report template selection;
- citation style;
- biological domain presets;
- experimental workflows.

Author
------
Guillermo Ramajo Fernández
"""

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class WorkspaceRequest(BaseModel):
    """
    Request model used to create a new biomedical Research Workspace.

    A workspace begins with a scientific research question and evolves
    throughout the investigation as literature is retrieved, evidence is
    synthesized, and reports are generated.

    Attributes
    ----------
    question : str
        Scientific research question defining the investigation.

    Notes
    -----
    The request intentionally contains only the minimum information
    required to initialize a new research session.

    Future versions may optionally include workspace configuration
    parameters without breaking backward compatibility.

    Examples
    --------
    {
        "question":
        "Compare KRAS G12C inhibitors in non-small cell lung cancer."
    }
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    question: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description=(
            "Biomedical research question that will initialize "
            "a new Research Workspace."
        ),
        examples=[
            "Compare KRAS G12C inhibitors.",
            "What are the latest biomarkers for Alzheimer's disease?",
            "Summarize CAR-T therapy for glioblastoma."
        ],
    )