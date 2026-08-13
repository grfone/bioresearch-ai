"""
workspace_action_request.py

API request schema for invoking an FSM action on a Research Workspace.

The body is intentionally minimal: most actions do not require
any input. The ``query`` field is optional and only used by the
``search`` action to override the workspace's stored question.

Author
------
Guillermo Ramajo Fernández
"""

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceActionRequest(BaseModel):
    """
    Request body for ``POST /workspaces/{id}/actions/{action}``.

    Attributes
    ----------
    query : str | None
        Optional override of the question. Only used by the
        ``search`` action.

    Examples
    --------
    ::

        {
            "query": "GLP-1 receptor agonists and Alzheimer's"
        }
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    query: str | None = Field(
        default=None,
        description=(
            "Optional override of the question. Used by the search "
            "action to re-run PubMed with a different query."
        ),
        examples=[
            "GLP-1 receptor agonists and Alzheimer's",
        ],
    )
