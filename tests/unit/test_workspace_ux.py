"""
Tests for the workspace UX improvements.

This file locks in two regressions that bit the user:

1. **The Add Paper button must be visible in the workspace page.**
   A previous version committed the showUpload state and the
   PaperUpload component but never added the actual button to
   the JSX. The user reported a workspace where they could see
   ``add_paper`` in the "Available actions" pills but had no way
   to trigger it. The new design embeds the AddPapersPanel
   directly above the action bar so the entry surface is
   always visible (when the FSM allows).

2. **The action bar must show a real primary action at CREATED.**
   The previous design listed every FSM action in a single row,
   which buried the most useful one. The new design has three
   labelled rows: Retrieve / Process / Lifecycle, with
   ``Search PubMed`` as the primary action and ``AddPapersPanel``
   above the bar.

These tests are source-level — they grep the JSX for the right
strings — because that's exactly the regression mode we're
guarding against.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_TSX = REPO_ROOT / "frontend/src/pages/Workspace.tsx"


def test_workspace_renders_add_papers_panel() -> None:
    """The workspace page must render the AddPapersPanel."""
    text = WORKSPACE_TSX.read_text()
    assert "<AddPapersPanel" in text, (
        "Workspace.tsx must render <AddPapersPanel /> so the "
        "Add Paper entry surface is visible to the user. A "
        "previous version committed showUpload state but never "
        "added the button to the JSX, leaving the user without "
        "any way to add a paper."
    )


def test_workspace_action_bar_is_grouped_into_rows() -> None:
    """The action bar must be split into Retrieve / Process /
    Lifecycle rows so the primary action is prominent at any
    state."""
    text = WORKSPACE_TSX.read_text()
    for label in ("Retrieve", "Process", "Lifecycle"):
        assert label in text, (
            f"action bar must have a '{label}' row label so the "
            "primary action is visible at each FSM state"
        )


def test_workspace_does_not_hide_add_papers_behind_a_toggle() -> None:
    """The add-papers UI must not be hidden behind a state
    toggle. The original bug was that ``showUpload`` defaulted
    to ``false`` with no visible way to flip it. The new design
    embeds the panel directly."""
    text = WORKSPACE_TSX.read_text()
    assert "showUpload" not in text, (
        "AddPapersPanel must not be hidden behind a state "
        "toggle. It should be rendered directly so users can "
        "see the entry surface immediately."
    )
    assert "setShowUpload" not in text, (
        "setShowUpload is the toggle handler for the buggy "
        "version. If it's still present, the regression has "
        "returned."
    )


def test_workspace_uses_add_papers_panel_not_paper_upload() -> None:
    """The old PaperUpload component was deleted because its
    toggle-based UX was the cause of the bug. If anyone
    resurrects it, the workspace page will silently break."""
    import os

    paper_upload = REPO_ROOT / "frontend/src/components/PaperUpload.tsx"
    assert not paper_upload.exists(), (
        "PaperUpload.tsx must not exist; the buggy "
        "showUpload-default-false pattern it embodies caused "
        "the original regression. Use AddPapersPanel instead."
    )

    text = WORKSPACE_TSX.read_text()
    assert "PaperUpload" not in text, (
        "Workspace.tsx must not import PaperUpload (it has been "
        "removed)."
    )



def test_workspace_renders_three_zone_empty_state() -> None:
    """When papers=0, the workspace must render the three-zone
    empty state that names real workflows ("I have specific
    papers", "I want to discover papers", "I have PDFs on my
    machine") rather than a passive "no papers yet" message.

    The previous design used ``<PaperList emptyMessage=...>``
    with the text "No papers retrieved yet." which told the user
    nothing about what to do next.
    """
    text = WORKSPACE_TSX.read_text()
    assert "<WorkspaceEmptyState" in text, (
        "Workspace.tsx must render <WorkspaceEmptyState /> when "
        "papers=0 so the user sees the three-zone workflow picker."
    )
    # The actual workflow labels live in WorkspaceEmptyState.tsx.
    # Read the component file to verify the copy is present so the
    # user sees meaningful workflow names (not placeholders).
    empty_state = (REPO_ROOT / "frontend/src/components/WorkspaceEmptyState.tsx").read_text()
    for label in (
        "I have specific papers",
        "I want to discover papers",
        "I have PDFs on my machine",
    ):
        assert label in empty_state, (
            f"WorkspaceEmptyState.tsx must list {label!r} as a "
            "workflow the user can pick from the three-zone empty "
            "state."
        )



def test_workspace_action_bar_uses_two_tier_model() -> None:
    """The action bar must follow the consultant's two-tier model:
    primary tier (Search PubMed) always visible, secondary tier
    (Summarize / Compare / Generate Report / Complete / Retry /
    Clear All) hidden behind a toggle that auto-expands when
    papers exist.
    """
    text = WORKSPACE_TSX.read_text()
    assert "showProcessingActions" in text, (
        "Workspace.tsx must gate the secondary action tier behind "
        "a state toggle so the bar stays clean at CREATED"
    )
    assert "lab-bench-action-bar-primary" in text, (
        "primary tier must use the lab-bench-action-bar-primary "
        "className"
    )
    assert "lab-bench-action-bar-secondary" in text, (
        "secondary tier must use the lab-bench-action-bar-secondary "
        "className and be hidden when collapsed"
    )
    # The old 3-row model must be gone.
    assert "lab-bench-action-row" not in text, (
        "the obsolete 3-row action-bar model must not remain in "
        "Workspace.tsx"
    )
