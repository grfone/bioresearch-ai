// pages/Report.tsx
/**
 * ============================================================================
 * Report.tsx
 * ============================================================================
 *
 * BioResearch AI
 * Scientific Research Workstation
 *
 * ----------------------------------------------------------------------------
 * Purpose
 * ----------------------------------------------------------------------------
 *
 * Displays a generated biomedical research report.
 *
 * This page retrieves the report for a given workspace. If the report
 * has not been generated yet, it provides an action to generate it.
 *
 * The report is fetched by calling the report generation endpoint again,
 * but the backend may cache or regenerate it. For simplicity, we always
 * regenerate when the page loads (or when the user explicitly requests).
 *
 * ----------------------------------------------------------------------------
 * Architecture
 * ----------------------------------------------------------------------------
 *
 *              Report (Page)
 *                    │
 *           useWorkspace (hook)
 *                    │
 *         ┌──────────┴──────────┐
 *         │                     │
 *    ReportHeader         ReportContent
 *         │                     │
 *    Metadata             ┌─────┴─────┐
 *                         │           │
 *                   Summary       Citations
 *                         │           │
 *                   Limitations  FutureWork
 *
 * ----------------------------------------------------------------------------
 * Responsibilities
 * ----------------------------------------------------------------------------
 *
 * • Display the executive summary.
 * • List supporting citations.
 * • Show limitations and future work sections if included.
 * • Provide a button to regenerate the report.
 *
 * The page uses the `useWorkspace` hook to generate the report and
 * updates the workspace store accordingly.
 *
 * ----------------------------------------------------------------------------
 * Author
 * ----------------------------------------------------------------------------
 *
 * Guillermo Ramajo Fernández
 * ============================================================================
 */

import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useWorkspace } from '../hooks/useWorkspace';
import { useWorkspaceStore } from '../state/workspaceStore';
import type { ReportResponse } from '../models/report';
import { hasLimitations, hasFutureWork } from '../models/report';
import { FileText, RefreshCw, AlertCircle, Lightbulb } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export const Report: React.FC = () => {
  const {workspaceId} = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();

  const {
    loading,
    error,
    fetchWorkspace,
    generateReport,
  } = useWorkspace(workspaceId);

  const [report, setReport] = useState<ReportResponse | null>(null);
  const [generating, setGenerating] = useState(false);
  // Phase label shown next to the spinner. Mirrors the
  // orchestrator's actual phases for the report action:
  //   1. ``Loading workspace...`` while ``fetchWorkspace``
  //      is in flight (the user always sees this -- it's
  //      a prerequisite for everything else).
  //   2. ``Summarizing...`` ONLY IF the workspace has no
  //      summary yet. The orchestrator's ``report()`` does
  //      an auto-summarise when ``session.summary is None``
  //      (see ADR-008); we mirror that decision in the UI
  //      so the user doesn't see "Summarizing..." for a
  //      workspace that already has a summary (the
  //      auto-summarise branch is skipped server-side too).
  //   3. ``Generating report...`` while the report use
  //      case is in flight.
  // The Compare step is NOT shown because
  // ``WorkspaceOrchestrator.report()`` doesn't actually
  // call the compare use case (see ADR-008 follow-up --
  // compare is data-side still set on the workspace model
  // but doesn't block report generation).
  const [phase, setPhase] = useState<string>('Loading workspace…');
  const [genError, setGenError] = useState<string | null>(null);
  // True while the page is in any loading phase (initial
  // ``fetchWorkspace``, optional ``Summarizing``, and
  // ``Generating report``). We track this separately from
  // ``loading`` (which is only the fetch) and ``generating``
  // (which is only the report call) because there's a brief
  // gap between them: after fetchWorkspace resolves, both
  // flags are false momentarily before handleGenerateReport
  // sets ``generating: true``. We don't want to flash the
  // report-or-error UI during that gap.
  const [inFlight, setInFlight] = useState(true);

  // Load workspace and generate report on mount if not already available.
  useEffect(() => {
    if (!workspaceId) return;
    let cancelled = false;
    setInFlight(true);
    setPhase('Loading workspace…');
    (async () => {
      try {
        await fetchWorkspace(workspaceId);
        if (cancelled) return;
        // The workspace FSM now lives in the
        // useWorkspaceStore -- read the freshly-fetched
        // ``summary`` to decide whether the orchestrator
        // will auto-summarise inside report().
        const fresh = useWorkspaceStore.getState().currentWorkspace;
        const willSummarize =
          fresh?.workspace_id === workspaceId && fresh.summary == null;
        if (willSummarize) {
          setPhase('Summarizing…');
        } else {
          setPhase('Generating report…');
        }
        await handleGenerateReport();
      } catch (err) {
        if (cancelled) return;
        setGenError(err instanceof Error ? err.message : 'Failed to load workspace.');
      } finally {
        if (!cancelled) setInFlight(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleGenerateReport = async () => {
    if (!workspaceId) return;
    setGenerating(true);
    setInFlight(true);
    setGenError(null);
    // Compute the phase from the current workspace state:
    // if the orchestrator will auto-summarise (no
    // summary yet), show 'Summarizing...'; otherwise skip
    // straight to 'Generating report...'. We do this here
    // too -- not just in the useEffect -- so the Retry
    // button on the error UI picks the right phase on
    // subsequent attempts, even after the useEffect has
    // already finished and left ``phase`` set to a stale
    // value.
    const fresh = useWorkspaceStore.getState().currentWorkspace;
    const willSummarize =
      fresh?.workspace_id === workspaceId && fresh.summary == null;
    setPhase(willSummarize ? 'Summarizing…' : 'Generating report…');
    try {
      const result = await generateReport();
      setReport(result);
      // Optionally refetch workspace to update report_available flag.
      await fetchWorkspace(workspaceId);
    } catch (err) {
      setGenError(err instanceof Error ? err.message : 'Failed to generate report.');
    } finally {
      setGenerating(false);
      setInFlight(false);
    }
  };

  if (loading || generating || inFlight) {
    // ``phase`` carries the current label throughout the
    // lifecycle (initial value: 'Loading workspace…').
    // ``setPhase`` calls in the useEffect + handleGenerateReport
    // advance it through 'Summarizing…' (if the
    // orchestrator will auto-summarise) and
    // 'Generating report…' as the work progresses.
    // The ternary is a safety net: if ``phase`` is somehow
    // empty (e.g. the Retry button clicked handleGenerateReport
    // directly), default to 'Loading workspace…' rather
    // than rendering an empty label.
    const phaseLabel = phase || 'Loading workspace…';
    return (
        <div className="page section flex items-center justify-center min-h-screen">
          <div className="text-center">
            <div className="spinner mx-auto mb-4"/>
            <p className="text-secondary">{phaseLabel}</p>
          </div>
        </div>
    );
  }

  if (error || genError) {
    return (
        <div className="page section flex items-center justify-center min-h-screen">
          <div className="text-center text-error">
            <p>Error generating report.</p>
            <p className="text-sm text-secondary mt-2">{error?.message || genError}</p>
            <button
              className="btn btn-outline mt-4"
              onClick={async () => {
                // Retry: refresh first (so we know the
                // current workspace state and pick the
                // correct phase), then re-run generation.
                if (!workspaceId) return;
                setInFlight(true);
                setPhase('Loading workspace…');
                try {
                  await fetchWorkspace(workspaceId);
                  await handleGenerateReport();
                } catch (err) {
                  setGenError(err instanceof Error ? err.message : 'Failed to retry.');
                }
              }}
            >
              <RefreshCw size={16}/>
              Retry
            </button>
          </div>
        </div>
    );
  }

  if (!report) {
    return (
        <div className="page section flex items-center justify-center min-h-screen">
          <div className="empty-state">
            <FileText size={48} className="text-muted"/>
            <h3 className="empty-state-title">No Report Available</h3>
            <p className="empty-state-description">
              Generate a report from the workspace to see it here.
            </p>
            <button className="btn btn-primary mt-4" onClick={handleGenerateReport}>
              Generate Report
            </button>
          </div>
        </div>
    );
  }

  // Extract the report title from the first Markdown heading
  const reportTitle =
      report.summary
          .split("\n")
          .find((line) => line.startsWith("# "))
          ?.replace(/^#\s+/, "") ?? "Research Report";

// Remove the title from the markdown so it isn't shown twice
  const reportBody = report.summary.replace(/^# .*\n?/, "");

  return (
      <div className="page section">
        {/* Report Hero */}
        <header className="report-hero">
          <div className="report-hero-content">
        <span className="report-eyebrow">
          Research Report
        </span>

            <h1 className="report-title">
              {reportTitle}
            </h1>

            <div className="report-meta">
          <span>
            Generated {new Date(report.generated_at).toLocaleDateString()}
          </span>

              <span>
            {report.citations.length} Citation
                {report.citations.length !== 1 && "s"}
          </span>
            </div>
          </div>

          <div className="report-actions">
            <button
                className="btn btn-secondary"
                onClick={handleGenerateReport}
            >
              <RefreshCw size={16}/>
              Regenerate
            </button>

            <button
                className="btn btn-outline"
                onClick={() => navigate(`/workspace/${workspaceId}`)}
            >
              Back to Workspace
            </button>
          </div>
        </header>

        {/* Report Content */}
        <div className="space-y-8">
          {/* Summary */}
          <section className="glass-panel">
            <h2 className="text-lg font-semibold mb-6">
              Executive Summary
            </h2>

              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                className="
                  prose
                  prose-invert
                  max-w-5xl mx-auto
                  prose-headings:text-white
                  prose-p:text-slate-300
                  prose-li:text-slate-300
                  prose-strong:text-white
                  prose-h1:mb-6
                  prose-h2:mt-10
                  prose-h2:mb-4
                  prose-p:leading-8
                "
              >
              {reportBody}
            </ReactMarkdown>
          </section>

          {/* Citations */}
          {report.citations.length > 0 && (
              <section className="glass-panel">
                <h2 className="text-lg font-semibold text-primary mb-3">
                  Citations
                </h2>

                <ul className="space-y-2 list-disc pl-5">
                  {report.citations.map((citation, idx) => (
                      <li
                          key={idx}
                          className="text-secondary text-sm leading-relaxed"
                      >
                        {citation}
                      </li>
                  ))}
                </ul>
              </section>
          )}

          {/* Limitations */}
          {hasLimitations(report) && (
              <section className="glass-panel border-l-4 border-warning">
                <h2 className="text-lg font-semibold text-warning flex items-center gap-2 mb-3">
                  <AlertCircle size={18}/>
                  Limitations
                </h2>

                <ul className="space-y-2 list-disc pl-5">
                  {report.limitations.map((item, idx) => (
                      <li
                          key={idx}
                          className="text-secondary text-sm leading-relaxed"
                      >
                        {item}
                      </li>
                  ))}
                </ul>
              </section>
          )}

          {/* Future Work */}
          {hasFutureWork(report) && (
              <section className="glass-panel border-l-4 border-primary">
                <h2 className="text-lg font-semibold text-primary flex items-center gap-2 mb-3">
                  <Lightbulb size={18}/>
                  Future Research Directions
                </h2>

                <ul className="space-y-2 list-disc pl-5">
                  {report.future_work.map((item, idx) => (
                      <li
                          key={idx}
                          className="text-secondary text-sm leading-relaxed"
                      >
                        {item}
                      </li>
                  ))}
                </ul>
              </section>
          )}

          {/* Metadata */}
          <div className="text-xs text-muted flex flex-wrap gap-4 pt-4 border-t border-border-subtle">
        <span>
          Generated: {new Date(report.generated_at).toLocaleString()}
        </span>

            <span>
          Workspace ID: {report.workspace_id}
        </span>

            <span>
          Citations: {report.citations.length}
        </span>
          </div>
        </div>
      </div>
  );
};