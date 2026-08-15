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
  // returning users see their next actions immediately.
  const [showProcessingActions, setShowProcessingActions] =
    useState(!!workspace?.total_papers);

  // Refs into the entry surfaces so the empty-state cards can
  // scroll the relevant one into view on click.
  const papersSectionRef = React.useRef<HTMLDivElement | null>(null);
  const identifierInputRef = React.useRef<HTMLTextAreaElement | null>(null);
  const searchInputRef = React.useRef<HTMLInputElement | null>(null);

  const focusIdentifierInput = () => {
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
          This is the primary paper-entry surface for the
          "I have a list of PMIDs/DOIs" workflow. */}
      <AddPapersPanel
        workspaceId={currentWorkspace.workspace_id}
        enabled={can('add_paper')}
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
            onClick={() => handleRunAction('search', 'PubMed search')}
            disabled={!can('search')}
            data-action="search"
            title={
              can('search')
                ? 'Run a new PubMed search for this workspace'
                : 'Search is not allowed in the current state'
            }
          >
            <Play size={16} />
            Search PubMed
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
            onChooseIdentifier={focusIdentifierInput}
            onChooseSearch={focusSearchInput}
            onChoosePdf={() => {
              toast.info(
                "Drag-and-drop PDF parsing is on the roadmap. " +
                "For now, paste a DOI or PMID instead.",
              );
              focusIdentifierInput();
            }}
          />
        )}

        <div className="mb-6">
          <LiteratureSearch
            initialQuery={currentWorkspace.question}
            onSearchComplete={(count) => {
              toast.success(`Added ${count} papers`);
            }}
            inputRef={searchInputRef}
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
          />
        </div>
      </div>
    </div>
  );
};
