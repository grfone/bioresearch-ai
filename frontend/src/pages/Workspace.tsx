/**
 * ============================================================================
 * Workspace.tsx
 * ============================================================================
 *
 * BioResearch AI
 * Scientific Research Workstation
 *
 * ----------------------------------------------------------------------------
 * Purpose
 * ----------------------------------------------------------------------------
 *
 * The lab-bench view of a Research Workspace. Shows the research question,
 * the FSM lifecycle strip, the retrieved literature, the evidence summary,
 * the cross-paper comparison, and the final report.
 *
 * The page is fully driven by the FSM: action buttons are enabled only
 * when the FSM allows them. There is no "always-on" report button — the
 * UI consults ``workspace.allowed_actions``.
 *
 * ----------------------------------------------------------------------------
 * Author
 * ----------------------------------------------------------------------------
 *
 * Guillermo Ramajo Fernández
 * ============================================================================
 */

import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useWorkspace } from '../hooks/useWorkspace';
import { LiteratureSearch } from '../components/LiteratureSearch';
import { PaperList } from '../components/PaperList';
import { AddPapersPanel } from '../components/AddPapersPanel';
import { AdvancedSearchModal } from '../components/AdvancedSearchModal';
import { WorkspaceEmptyState } from '../components/WorkspaceEmptyState';
import {
  AlertCircle,
  BookOpen,
  Clock,
  Loader2,
  Upload,
  X,
} from 'lucide-react';
import { WorkspaceActionBar } from '../components/WorkspaceActionBar';
import { useWorkspaceStore } from '../state/workspaceStore';
import { toast } from '../state/toastStore';
import {
  isMacPlatform,
  shortcutLabel,
  useKeyboardShortcut,
} from '../hooks/useKeyboardShortcut';
import type { WorkspaceAction } from '../models/workspace';

export const Workspace: React.FC = () => {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();

  const storeWorkspace = useWorkspaceStore((s) => s.currentWorkspace);

  const shouldFetch = !storeWorkspace || storeWorkspace.workspace_id !== workspaceId;

  const {
    workspace,
    loading,
    error,
    fetchWorkspace,
    runAction,
  } = useWorkspace(workspaceId, { autoFetch: false });

  useEffect(() => {
    if (shouldFetch && workspaceId) {
      (async () => {
        try {
          await fetchWorkspace(workspaceId);
        } catch (err) {
          console.error('Workspace fetch error:', err);
        }
      })();
    }
  }, [workspaceId, shouldFetch, fetchWorkspace]);

  const removePaper = useWorkspaceStore((s) => s.removePaper);
  const clearPapers = useWorkspaceStore((s) => s.clearPapers);

  const can = (action: WorkspaceAction): boolean => {
    return workspace?.allowed_actions.includes(action) ?? false;
  };

  const handleRunAction = async (action: WorkspaceAction, label: string) => {
    try {
      await runAction(action);
      toast.success(`${label} completed`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${label} failed: ${message}`);
    }
  };

  const handleGenerateReport = () => {
    // Navigate immediately so the user sees the
    // ``Report`` page's loading screen the instant they
    // click "Generate Report". Previously we awaited the
    // full ``runAction('report')`` round-trip here (which
    // takes 11-43s because the orchestrator auto-summarises
    // + auto-compares + reports inside one FSM action --
    // see ADR-008). The user spent that whole window
    // staring at the Workspace page with no feedback.
    //
    // The Report page now owns the generation lifecycle:
    // on mount it ``fetchWorkspace``s, then auto-triggers
    // ``generateReport``. The legacy endpoint
    // (``POST /reports/generate``) is also FSM-aware --
    // it delegates to ``orchestrator.report`` which
    // auto-summarises when ``session.summary is None``.
    //
    // The error path is now: if the generation fails, the
    // Report page's existing error UI surfaces the message
    // and offers a Retry button. We do NOT need a try/
    // catch here because we are not awaiting anything.
    navigate(`/report/${workspaceId}`);
  };

  const handleRemovePaper = (paper: any) => {
    const id = paper.pmid || paper.doi;
    if (id) {
      removePaper(id);
      toast.info('Paper removed');
    }
  };

  // The Advanced Search dropdown opens when the user clicks
  // the "Advanced Search" button. The dropdown's primary
  // CTA posts the filter bundle to the same backend endpoint
  // — when ``filters`` are non-default, the route dispatches
  // through ``WorkspaceOrchestrator.search_with_filters``.
  const [advancedSearchOpen, setAdvancedSearchOpen] = useState(false);

  // The Add Papers panel is collapsed by default. The user
  // sees a single "Add papers" button on the workspace page;
  // clicking opens a modal containing the DOI/PMID/PDF entry
  // surface. This mirrors the Advanced Search modal pattern
  // and keeps the workspace page scannable when the user is
  // reviewing papers rather than adding them.
  const [addPapersOpen, setAddPapersOpen] = useState(false);

  // Escape key closes the Add Papers modal. We only attach
  // the listener while the modal is open so the rest of the
  // page (text inputs, the global Ctrl/Cmd+K shortcut) is
  // unaffected.
  useEffect(() => {
    if (!addPapersOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setAddPapersOpen(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [addPapersOpen]);

  // Refs into the entry surfaces so the empty-state cards can
  // scroll the relevant one into view on click.
  const papersSectionRef = React.useRef<HTMLDivElement | null>(null);
  const doiInputRef = React.useRef<HTMLTextAreaElement | null>(null);
  const searchInputRef = React.useRef<HTMLInputElement | null>(null);

  const focusDoiInput = () => {
    papersSectionRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    // The AddPapersPanel textarea is the second textarea in the
    // panel — finding it by ref would require prop drilling, so
    // we just scroll and let the user click into it.
  };

  const focusSearchInput = () => {
    papersSectionRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    setTimeout(() => searchInputRef.current?.focus(), 350);
  };

  // Global Ctrl/Cmd+K shortcut. PC-first default: the binding is
  // just ``Ctrl+K`` and Mac fires the same ``ctrlKey`` event for
  // both Ctrl and Cmd. The display string switches to ``⌘K``
  // on Mac so users see the platform-appropriate hint.
  //
  // What gets focused depends on the FSM state: at CREATED with
  // zero papers, the DOI input is the most useful entry
  // surface (the consultant's "I have specific papers" workflow).
  // Once papers exist, the PubMed search input is the more
  // useful next step.
  const focusShortcutTarget = () => {
    const isEmptyWorkspace =
      !currentWorkspace || currentWorkspace.total_papers === 0;
    if (isEmptyWorkspace) {
      focusDoiInput();
      setTimeout(() => doiInputRef.current?.focus(), 350);
    } else {
      focusSearchInput();
    }
  };
  useKeyboardShortcut({ key: 'k', ctrl: true }, focusShortcutTarget);

  const handleClearPapers = () => {
    if (window.confirm('Remove all papers from this workspace?')) {
      clearPapers();
      toast.info('All papers cleared');
    }
  };

  if (loading && !workspace) {
    return (
      <div className="page section flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="spinner mx-auto mb-4" />
          <p className="text-secondary">Loading workspace…</p>
        </div>
      </div>
    );
  }

  if (error && !workspace) {
    return (
      <div className="page section flex items-center justify-center min-h-screen">
        <div className="text-center text-error">
          <p>Error loading workspace.</p>
          <p className="text-sm text-secondary mt-2">{error.message}</p>
        </div>
      </div>
    );
  }

  const currentWorkspace = workspace;

  if (!currentWorkspace) {
    return (
      <div className="page section flex items-center justify-center min-h-screen">
        <div className="empty-state">
          <BookOpen size={48} className="text-muted" />
          <h3 className="empty-state-title">Workspace not found</h3>
          <p className="empty-state-description">
            The workspace you are looking for does not exist.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="page section">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-primary">{currentWorkspace.question}</h1>
          <div className="flex items-center gap-3 mt-2 text-sm text-muted">
            <span className="flex items-center gap-1">
              <Clock size={14} />
              {new Date(currentWorkspace.created_at).toLocaleDateString()}
            </span>
            <span className="badge badge-neutral">{currentWorkspace.state}</span>
            {currentWorkspace.report_available && (
              <span className="badge badge-success">Report Available</span>
            )}
          </div>
        </div>
      </div>

      {/* Lifecycle strip removed in commit c0edd56 ("drop the lifecycle strip") and the
          component file was removed in the immediately
          following cleanup commit.
          The 5-station progress strip (Question -> Papers ->
          Summary -> Comparison -> Report) sat between the
          action bar and the AddPapersPanel. The action bar
          already exposes the FSM state and allowed_actions,
          and the per-paper list shows progress at the row
          level; the strip was redundant visual noise. If a
          future design needs lifecycle progress again, a
          compact "Step N of M" pill in the action bar header
          would be a better home than a full-width strip. */}

      {/* Action bar — three buttons in a single equal-weight row:
          Generate Report, Advanced Search Options, Add More Papers.
          All three use the same ``.btn btn-primary`` styling so the
          workspace page reads as a single coherent control surface.
          See ``components/WorkspaceActionBar.tsx`` for the
          callback contract and the rationale. The Add Papers modal
          itself (DOI/PMID bulk + single DOI + PDF upload) is
          rendered further down the page; the button just fires the
          click. */}
      <WorkspaceActionBar
        canReport={can('report')}
        canAddPapers={can('add_paper')}
        onGenerateReport={handleGenerateReport}
        onOpenAdvancedSearch={() => setAdvancedSearchOpen(true)}
        onAddMorePapers={() => setAddPapersOpen(true)}
      />

      {/* Evidence Summary used to render here, but the
          user asked to drop it: the summary was a duplicate
          preview of what the final Report page already shows,
          and it sat between the action bar and the literature
          list as a long block that the user had to scroll
          past on every visit. The ``session.summary`` data
          is still set on the workspace model by the
          auto-summarise step in ``WorkspaceOrchestrator.report``
          (see ADR-008) and surfaces in the dedicated
          ``/report/{id}`` page. If a future feature needs
          to preview the summary inline, we can re-mount
          this with a different surface (e.g. a collapsible
          detail panel). */}

      {/* Evidence Comparison was rendered here in the prior
          version of this page. The COMPARE action and the
          COMPARING/COMPARED FSM states were removed on
          2026-08-30 (see ADR-016) because the report
          generator never consumed the comparison as input —
          the report works from the summary alone, and the
          evidence comparison was a write-only artefact.
          If a future feature needs a side-by-side matrix, it
          can be re-mounted here. The slot is intentionally
          empty for now. */}

      {/* Literature Search + Papers List, wrapped in a ref so the
          empty-state cards above can scroll into view. */}
      <div ref={papersSectionRef}>
        {/* Three-zone empty state — only shown when the workspace
            has zero papers. Each card names a real workflow and
            brings the matching entry surface into view. */}
        {currentWorkspace.total_papers === 0 && (
          <WorkspaceEmptyState
            onChooseIdentifier={focusDoiInput}
            onChooseSearch={focusSearchInput}
            onChoosePdf={() => {
              // The PDF dropzone is real now — clicking this card
              // focuses the DOI input as a fallback since the
              // PDF dropzone doesn't have a forwarded ref yet.
              focusDoiInput();
            }}
            shortcutHint={shortcutLabel({ key: 'k', ctrl: true }, isMacPlatform())}
          />
        )}

        <div className="mb-6">
          <LiteratureSearch
            workspaceId={currentWorkspace.workspace_id}
            initialQuery={currentWorkspace.question}
            onSelectComplete={(count) => {
              toast.success(
                `Added ${count} paper${count === 1 ? '' : 's'}.`,
              );
            }}
            inputRef={searchInputRef}
            shortcutHint={shortcutLabel({ key: 'k', ctrl: true }, isMacPlatform())}
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold text-primary flex items-center gap-2">
              <BookOpen size={20} />
              Literature ({currentWorkspace.total_papers})
            </h2>
          </div>

          <PaperList
            papers={currentWorkspace.papers}
            emptyMessage="No papers retrieved yet."
            onRemovePaper={handleRemovePaper}
            paperSources={currentWorkspace.paper_sources}
          />
        </div>
      </div>

      {/* Advanced Search modal — opens from the "Search
          PubMed" button. The modal's primary CTA calls
          ``api.runSearchAction`` with the chosen filter
          bundle; when filters are non-default, the backend
          dispatches through
          ``WorkspaceOrchestrator.search_with_filters`` for
          multi-source fan-out. */}
      <AdvancedSearchModal
        workspaceId={currentWorkspace.workspace_id}
        workspaceQuestion={currentWorkspace.question}
        isOpen={advancedSearchOpen}
        onClose={() => setAdvancedSearchOpen(false)}
      />

      {/* Add Papers modal — opens from the "Add papers"
          button. The actual entry surface is the existing
          ``<AddPapersPanel>`` component (DOI tab + PDF
          tab + bulk input + dropzone); we just wrap it in
          a backdrop+dialog overlay so the workspace page
          itself stays scannable. The modal closes when
          the user clicks the backdrop, presses Escape, or
          clicks the X in the header. */}
      {addPapersOpen && (
        <div
          id="add-papers-modal"
          className="overlay"
          onClick={() => setAddPapersOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label="Add papers to this workspace"
        >
          <div
            className="dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="dialog-header">
              <h2 className="dialog-title">Add papers</h2>
              <button
                type="button"
                className="icon-button"
                onClick={() => setAddPapersOpen(false)}
                aria-label="Close add papers"
              >
                <X size={20} />
              </button>
            </div>
            <AddPapersPanel
              workspaceId={currentWorkspace.workspace_id}
              enabled={can('add_paper')}
              bulkInputRef={doiInputRef}
              shortcutHint={shortcutLabel(
                { key: 'k', ctrl: true },
                isMacPlatform(),
              )}
            />
          </div>
        </div>
      )}
    </div>
  );
};
