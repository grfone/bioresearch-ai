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
import { WorkspaceStatusBar } from '../components/WorkspaceStatusBar';
import { EvidenceComparisonPanel } from '../components/EvidenceComparisonPanel';
import {
  AlertCircle,
  BookOpen,
  Check,
  ChevronDown,
  Clock,
  FilePlus2,
  FileText,
  FileUp,
  GitCompareArrows,
  Hash,
  Loader2,
  Play,
  Plus,
  RotateCcw,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
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

  const handleGenerateReport = async () => {
    await handleRunAction('report', 'Report generation');
    if (can('report') === false && workspace?.state === 'REPORTED') {
      navigate(`/report/${workspaceId}`);
    }
  };

  const handleRemovePaper = (paper: any) => {
    const id = paper.pmid || paper.doi;
    if (id) {
      removePaper(id);
      toast.info('Paper removed');
    }
  };

  // The processing-action tier (Summarize, Compare, Generate Report)
  // is collapsed by default at CREATED so the bar stays focused on
  // the paper-entry workflow. Once papers exist it auto-expands so
  // returning users see their next actions immediately — not
  // "once papers exist on mount" (which would miss papers added
  // after the user navigates to this page), but "as soon as the
  // workspace has any papers at all".
  const [showProcessingActions, setShowProcessingActions] =
    useState(!!workspace?.total_papers);

  // Auto-expand the processing-action bar whenever papers appear
  // in the workspace. Without this effect, the initial
  // ``useState`` only runs on mount — if the workspace is empty
  // when the user lands on the page (very common: they always
  // start by running Search), the bar stays collapsed even
  // after Search returns 20 papers and the user is staring at
  // the Literature list wondering why Summarize / Compare /
  // Generate Report look disabled (they're not — they're
  // hidden behind the toggle).
  useEffect(() => {
    if (
      workspace &&
      workspace.total_papers > 0 &&
      !showProcessingActions
    ) {
      setShowProcessingActions(true);
    }
  }, [workspace?.total_papers, showProcessingActions, workspace]);

  // The Advanced Search modal opens when the user clicks
  // "Search PubMed" in the action bar. The modal's primary
  // CTA posts the filter bundle to the same backend endpoint
  // — when ``filters`` is supplied, the route dispatches
  // through ``WorkspaceOrchestrator.search_with_filters``.
  const [advancedSearchOpen, setAdvancedSearchOpen] = useState(false);

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

      {/* Lifecycle strip */}
      <WorkspaceStatusBar
        state={currentWorkspace.state}
        progress={currentWorkspace.progress}
        allowedActions={currentWorkspace.allowed_actions}
        lastError={currentWorkspace.last_error}
      />

      {/* AddPapersPanel — always visible when FSM allows add_paper.
          This is the primary paper-entry surface. Researchers
          paste DOIs into the bulk input or drop a PDF onto the
          dropzone; both paths go through the same resolver. */}
      <AddPapersPanel
        workspaceId={currentWorkspace.workspace_id}
        enabled={can('add_paper')}
        bulkInputRef={doiInputRef}
        shortcutHint={shortcutLabel({ key: 'k', ctrl: true }, isMacPlatform())}
      />

      {/* Action bar — two-tier per UX consultant.
          Primary tier (Search) is always visible because it's the
          default workflow at CREATED. Secondary tier (Summarize /
          Compare / Generate Report / Complete / Retry / Clear All)
          collapses behind a toggle so the bar stays clean while
          the user is still in the paper-entry phase. */}
      <div className="lab-bench-action-bar" role="toolbar" aria-label="Workspace actions">
        <div className="lab-bench-action-bar-primary">
          <span className="lab-bench-action-bar-primary-label">Retrieve</span>
          <button
            className="btn btn-primary"
            onClick={() => setAdvancedSearchOpen(true)}
            disabled={!can('search')}
            data-action="search"
            title={
              can('search')
                ? 'Open the Advanced Search modal to pick sources (PubMed, OpenAlex, Europe PMC, bioRxiv), year range, sort, and document type'
                : 'Search is not allowed in the current state'
            }
          >
            <Play size={16} />
            Advanced Search…
          </button>
          <button
            type="button"
            className="lab-bench-action-bar-toggle"
            onClick={() => setShowProcessingActions((v) => !v)}
            aria-expanded={showProcessingActions}
          >
            <ChevronDown
              size={14}
              style={{
                transform: showProcessingActions ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 150ms ease',
              }}
            />
            {showProcessingActions ? 'Hide' : 'Show'} processing actions
          </button>
        </div>

        <div
          className="lab-bench-action-bar-secondary"
          hidden={!showProcessingActions}
        >
          <button
            className="btn btn-primary"
            onClick={() => handleRunAction('summarize', 'Summarization')}
            disabled={!can('summarize')}
            data-action="summarize"
          >
            <Sparkles size={16} />
            Summarize
          </button>
          <button
            className="btn btn-primary"
            onClick={() => handleRunAction('compare', 'Evidence comparison')}
            disabled={!can('compare')}
            data-action="compare"
          >
            <GitCompareArrows size={16} />
            Compare
          </button>
          <button
            className="btn btn-primary"
            onClick={handleGenerateReport}
            disabled={!can('report')}
            data-action="report"
          >
            <FileText size={16} />
            Generate Report
          </button>
          <span style={{ flex: 1 }} />
          <button
            className="btn btn-secondary"
            onClick={() => handleRunAction('complete', 'Completion')}
            disabled={!can('complete')}
            data-action="complete"
          >
            <FilePlus2 size={16} />
            Complete
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => handleRunAction('retry', 'Retry')}
            disabled={!can('retry')}
            data-action="retry"
          >
            <RotateCcw size={16} />
            Retry
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleClearPapers}
            disabled={currentWorkspace.total_papers === 0}
          >
            <Trash2 size={16} />
            Clear All
          </button>
        </div>
      </div>

      {/* Summary */}
      {currentWorkspace.summary && (
        <div className="glass-panel mb-6">
          <h4 className="text-sm font-semibold uppercase text-muted tracking-wider mb-2">
            Evidence Summary
          </h4>
          <p className="text-secondary leading-relaxed">{currentWorkspace.summary}</p>
        </div>
      )}

      {/* Evidence Comparison */}
      <div className="mb-6">
        <EvidenceComparisonPanel
          workspaceId={currentWorkspace.workspace_id}
          hasComparison={currentWorkspace.has_evidence_comparison}
        />
      </div>

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
    </div>
  );
};
