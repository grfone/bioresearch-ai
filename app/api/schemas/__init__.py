"""
Re-exports of every public schema so callers can ``from
app.api.schemas import X`` instead of remembering the per-file
path.
"""

from app.api.schemas.evidence_comparison_response import (
    EvidenceComparisonResponse,
)
from app.api.schemas.paper_request import (
    AuthorRequest,
    JournalRequest,
    PaperRequest,
)
from app.api.schemas.report_request import ReportRequest
from app.api.schemas.report_response import ReportResponse
from app.api.schemas.search_request import SearchRequest
from app.api.schemas.search_response import (
    AuthorResponse,
    JournalResponse,
    PaperResponse,
    SearchResponse,
)
from app.api.schemas.workspace_action_request import WorkspaceActionRequest
from app.api.schemas.workspace_request import WorkspaceRequest
from app.api.schemas.workspace_response import WorkspaceResponse
from app.api.schemas.workspace_status_response import WorkspaceStatusResponse

__all__ = [
    "AuthorRequest",
    "AuthorResponse",
    "EvidenceComparisonResponse",
    "JournalRequest",
    "JournalResponse",
    "PaperRequest",
    "PaperResponse",
    "ReportRequest",
    "ReportResponse",
    "SearchRequest",
    "SearchResponse",
    "WorkspaceActionRequest",
    "WorkspaceRequest",
    "WorkspaceResponse",
    "WorkspaceStatusResponse",
]