"""
Tests for the workspace UX improvements (keyboard shortcut,
select-to-add, PDF drag-and-drop, empty-state).

The previous UX had three regressions the user reported:

1. The "Add Paper" button was hidden behind a state toggle that
   defaulted to ``false`` — so the user couldn't see it.
2. The PubMed search auto-appended all results, leaving the user
   no way to pick which papers entered the workspace.
3. There was no global keyboard shortcut to focus the entry
   surface.

The new design:
- The AddPapersPanel is rendered directly when the FSM allows.
- The LiteratureSearch now shows a checkbox list with "Add selected".
- The workspace exposes Ctrl/Cmd+K to focus the right input.
- The PDF tab in AddPapersPanel is a real drag-and-drop uploader.

These tests are source-level. They grep the JSX/TS for the
right strings so the regressions can't return.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_TSX = REPO_ROOT / "frontend/src/pages/Workspace.tsx"
LITERATURE_SEARCH_TSX = REPO_ROOT / "frontend/src/components/LiteratureSearch.tsx"
ADD_PAPERS_PANEL_TSX = REPO_ROOT / "frontend/src/components/AddPapersPanel.tsx"
KEYBOARD_HOOK_TS = REPO_ROOT / "frontend/src/hooks/useKeyboardShortcut.ts"


# ---------------------------------------------------------------------------
# Keyboard shortcut hook
# ---------------------------------------------------------------------------


def test_keyboard_hook_handles_pc_first_default() -> None:
    """The hook's display layer defaults to PC (Ctrl+K). Mac is
    detected at runtime and shown as ``⌘K`` only when the
    platform actually is Mac."""
    text = KEYBOARD_HOOK_TS.read_text()
    assert "isMacPlatform" in text, (
        "useKeyboardShortcut must expose isMacPlatform() so the "
        "display string can switch on Mac"
    )
    assert "shortcutLabel" in text, (
        "useKeyboardShortcut must export shortcutLabel() so the "
        "workspace can show the right hint per platform"
    )
    # The display function must branch on isMac to swap Ctrl/⌘.
    assert "isMac ?" in text or "isMac?" in text, (
        "shortcutLabel must produce 'Ctrl' on PC and '⌘' on Mac"
    )
    # The literal must be Ctrl first (PC default).
    assert "'Ctrl'" in text, (
        "shortcutLabel must produce 'Ctrl' — the PC default"
    )
    assert "'⌘'" in text, (
        "shortcutLabel must produce the mac command glyph "
        "for Mac users"
    )


def test_keyboard_hook_uses_ctrl_as_modifier() -> None:
    """The hook binds ``Ctrl+K`` as the primary shortcut. Mac
    fires ``ctrlKey`` for both Ctrl and Cmd because the browser
    normalises the event, so the same binding works on both
    platforms without a separate Mac branch."""
    text = KEYBOARD_HOOK_TS.read_text()
    assert "ctrl" in text
    # The matches() function must accept ``event.ctrlKey`` OR
    # ``event.metaKey`` as fulfilling the ctrl requirement, so
    # both Mac Cmd and PC Ctrl trigger the binding.
    assert "event.ctrlKey" in text and "event.metaKey" in text, (
        "matches() must accept either ctrlKey or metaKey for the "
        "Ctrl binding so Mac Cmd+K also works"
    )


def test_keyboard_hook_skips_when_user_is_typing() -> None:
    """The hook must NOT fire while the user is typing in a
    form field. Otherwise letter keys would steal focus from
    inputs and the user couldn't type."""
    text = KEYBOARD_HOOK_TS.read_text()
    assert "isTypingInField" in text or "INPUT" in text, (
        "useKeyboardShortcut must check whether the user is in "
        "an input / textarea / contenteditable before firing"
    )


def test_keyboard_hook_uses_prevent_default() -> None:
    """The hook must call ``event.preventDefault()`` so the
    browser's default Ctrl+K (e.g. Firefox's search bar) does
    not open over the user's workspace."""
    text = KEYBOARD_HOOK_TS.read_text()
    assert "preventDefault" in text, (
        "useKeyboardShortcut must call event.preventDefault() so "
        "the browser's default Ctrl+K handler doesn't override it"
    )


# ---------------------------------------------------------------------------
# Ctrl/Cmd+K wiring in Workspace
# ---------------------------------------------------------------------------


def test_workspace_binds_ctrl_k_shortcut() -> None:
    """The workspace must bind the Ctrl/Cmd+K shortcut to focus
    the appropriate input based on the FSM state."""
    text = WORKSPACE_TSX.read_text()
    assert "useKeyboardShortcut" in text, (
        "Workspace.tsx must call useKeyboardShortcut to bind the "
        "global Ctrl/Cmd+K shortcut"
    )
    assert "key: 'k', ctrl: true" in text or 'key: "k", ctrl: true' in text, (
        "Workspace.tsx must bind key='k' with ctrl=true. Mac "
        "users get the same binding via event.metaKey, so the "
        "display label adapts per platform."
    )


def test_workspace_distinguishes_identifier_vs_search_focus() -> None:
    """At CREATED with zero papers, Ctrl+K must focus the
    PMID/DOI input. Otherwise (papers exist), it must focus the
    PubMed search input. The two surfaces serve different
    workflows (specific identifiers vs. discovery)."""
    text = WORKSPACE_TSX.read_text()
    assert "focusIdentifierInput" in text, (
        "Workspace.tsx must define focusIdentifierInput() so the "
        "Ctrl+K handler can focus the PMID/DOI input at CREATED"
    )
    assert "focusSearchInput" in text, (
        "Workspace.tsx must define focusSearchInput() so the "
        "Ctrl+K handler can focus the PubMed search input when "
        "papers exist"
    )
    # The shortcut target must switch based on the FSM state.
    assert "isEmptyWorkspace" in text or "total_papers === 0" in text, (
        "the Ctrl+K target must differ based on workspace state"
    )


def test_workspace_passes_shortcut_hint_to_components() -> None:
    """Both the AddPapersPanel and the WorkspaceEmptyState must
    receive the platform-aware shortcut hint so the user sees
    ``Ctrl+K`` on PC and ``⌘K`` on Mac."""
    text = WORKSPACE_TSX.read_text()
    assert "shortcutHint={" in text, (
        "Workspace.tsx must pass shortcutHint to the components "
        "that surface it"
    )


# ---------------------------------------------------------------------------
# Select-to-add workflow (LiteratureSearch)
# ---------------------------------------------------------------------------


def test_literature_search_supports_select_to_add() -> None:
    """The PubMed search must show results as a checkbox list
    with a commit button. The previous auto-append flow is
    gone."""
    text = LITERATURE_SEARCH_TSX.read_text()
    assert "type=\"checkbox\"" in text or "type='checkbox'" in text, (
        "LiteratureSearch must render checkboxes for each result"
    )
    assert "selected" in text and "toggleSelected" in text, (
        "LiteratureSearch must track selected indices per result"
    )
    assert "Add selected" in text or "Add " in text, (
        "the commit button must say something like 'Add N papers'"
    )
    # The auto-append on search must be gone — that was the
    # consultant's "Workflow C" complaint.
    assert "addPapers(result.papers)" not in text, (
        "LiteratureSearch must NOT auto-append all results. The "
        "consultant explicitly asked for an explicit "
        "'Add selected' workflow."
    )


def test_literature_search_selects_all_by_default() -> None:
    """When results come back, all are selected by default. The
    user un-checks the irrelevant ones rather than having to
    check every relevant one. This is the consultant's
    Workflow C guidance."""
    text = LITERATURE_SEARCH_TSX.read_text()
    assert "setSelected(new Set(result.papers.map" in text, (
        "LiteratureSearch must select all results by default"
    )


# ---------------------------------------------------------------------------
# PDF drag-and-drop tab
# ---------------------------------------------------------------------------


def test_add_papers_panel_has_real_pdf_drop_zone() -> None:
    """The PDF tab in AddPapersPanel must be a real drag-and-drop
    uploader, not a placeholder. The previous "soon" badge is
    removed and the file input is wired to the API."""
    text = ADD_PAPERS_PANEL_TSX.read_text()
    assert "onDragOver" in text and "onDrop" in text, (
        "AddPapersPanel must wire onDragOver and onDrop for the "
        "PDF drag-and-drop zone"
    )
    assert "api.uploadPdf" in text, (
        "AddPapersPanel must call api.uploadPdf() to upload the "
        "PDF to the backend"
    )
    # The placeholder that's gone now used this exact text.
    assert "Drag-and-drop PDF parsing is on the roadmap" not in text, (
        "the placeholder copy must be removed; the PDF tab is now "
        "real"
    )
    assert 'accept="application/pdf"' in text, (
        "the file input must accept only application/pdf"
    )
