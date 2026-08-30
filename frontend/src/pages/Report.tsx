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
import { api } from '../api/client';
import type { ReportResponse } from '../models/report';
import { hasLimitations, hasFutureWork } from '../models/report';
import {
  citationAnchorId,
  linkifyCitationDoi,
  linkifyCitationMarkers,
} from '../lib/citationLink';
import { renderCitationWithDoiLink, renderItemWithCitationLinks } from '../lib/citationRender';
import { FileText, RefreshCw, AlertCircle, Lightbulb, Download } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export const Report: React.FC = () => {
  const {workspaceId} = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();

  const {
    loading,
    error,
    fetchWorkspace,
    runAction,
  } = useWorkspace(workspaceId);

  const [report, setReport] = useState<ReportResponse | null>(null);
  const [generating, setGenerating] = useState(false);
  // Track the PUBLISH action separately so the spinner / loader
  // can distinguish "report is being generated" from "PDF is
  // being rendered". The PUBLISH call is fast (single-digit ms
  // for the minimal PDF generator + JSON round-trip), so most
  // users will only see the spinner flash for one frame.
  const [publishing, setPublishing] = useState(false);
  // PUBLISH error (separate from genError because the action is
  // conceptually distinct -- "the PDF generation failed" is
  // a different user-visible problem from "the report generation
  // failed").
  const [pubError, setPubError] = useState<string | null>(null);
  // Same idea for the LaTeX download button. The download
  // can fail for reasons orthogonal to the PDF (network
  // error on the GET endpoint, no report yet, etc.).
  const [texError, setTexError] = useState<string | null>(null);
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
  const [genError, setGenError] = useState<Error | string | null>(null);
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
      // FSM-aware REPORT action. The hook's ``runAction``
      // special-cases 'report' to call the FSM-aware
      // endpoint and return ``ReportResponse`` -- so the
      // legacy ``/reports/generate`` endpoint is bypassed
      // (it's still wired on the backend, marked deprecated,
      // and kept for any external client that hasn't migrated).
      // See ADR-009 and the b900965 / 1faf32e sessions for
      // the FSM-audit context.
      const result = await runAction('report');
      // The hook's return type is ``WorkspaceResponse |
      // ReportResponse`` because TypeScript can't narrow
      // method overloads on an interface. At this call site
      // we *know* the action is 'report' so the return is
      // a ReportResponse -- the cast is safe and the
      // runtime hook special-cases the 'report' branch.
      setReport(result as ReportResponse);
      // Optionally refetch workspace to update report_available flag.
      await fetchWorkspace(workspaceId);
    } catch (err) {
      // Store the Error object (not just ``err.message``)
      // so the error UI's structured-envelope reader can see
      // the FastAPI detail -- including ``last_error`` and
      // ``current_state`` from the legacy ``/reports/generate``
      // endpoint's 409 response. Without keeping the original
      // Error, the user sees the verbose "API error 409: ..."
      // message instead of the actionable ``last_error`` from
      // the orchestrator.
      setGenError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setGenerating(false);
      setInFlight(false);
    }
  };

  /**
   * Run the PUBLISH action and persist the rendered PDF.
   *
   * Layer 4 of the FSM audit (see ADR-009): the button must
   * route through the FSM-aware endpoint
   * ``POST /workspaces/{id}/actions/publish`` -- NOT the
   * legacy ``api.complete`` shortcut. Routing through
   * ``api.complete`` would advance the workspace to COMPLETED
   * but leave ``session.published_report`` empty, breaking the
   * PDF download. ``runAction('publish')`` is the only path
   * that:
   *
   *   1. Renders the PDF on the server,
   *   2. Persists it on the session, AND
   *   3. Advances REPORTED -> PUBLISHING -> COMPLETED
   *      (the audit trail is preserved).
   *
   * After this call resolves, the workspace's
   * ``published_report_available`` flag flips to true and we
   * trigger a browser download of the PDF via a hidden
   * ``<a download>`` click. The "Generate PDF" button
   * generates AND downloads -- the user no longer needs a
   * separate download step.
   */
  const handlePublish = async () => {
    if (!workspaceId) return;
    setPublishing(true);
    setPubError(null);
    try {
      // ``runAction('publish')`` dispatches to the FSM-aware
      // ``POST /workspaces/{id}/actions/publish`` endpoint.
      // The hook's ``runAction`` mirrors the server's
      // ``allowed_actions`` by raising ``IllegalWorkspaceActionError``
      // if the FSM doesn't allow PUBLISH from the current
      // state (e.g. if the user landed on this page after
      // somehow getting to CREATED without a report).
      await runAction('publish');
      // Refresh the workspace so the new
      // ``published_report_available`` flag is reflected in
      // ``currentWorkspace``. ``runAction`` already does this
      // internally, but an explicit refetch makes the data
      // flow obvious to anyone reading the code.
      await fetchWorkspace(workspaceId);
      // Auto-download the PDF. The endpoint sets
      // ``Content-Disposition: attachment`` so the browser
      // saves the file rather than navigating. We use a
      // temporary ``<a download>`` element rather than a
      // window navigation so the user stays on the page
      // (the click handler is in this same React tree).
      const a = document.createElement('a');
      a.href = api.getPublishedReportUrl(workspaceId);
      a.download = `report-${workspaceId}.pdf`;
      a.rel = 'noopener noreferrer';
      document.body.appendChild(a);
      a.click();
      // Clean up the temporary element on the next tick.
      // We don't ``removeChild`` synchronously because
      // some browsers (Firefox) cancel the download if
      // the link is removed before the download starts.
      setTimeout(() => {
        document.body.removeChild(a);
      }, 0);
    } catch (err) {
      setPubError(
        err instanceof Error ? err.message : 'Failed to publish report.',
      );
      // Do NOT bump ``publishedAt`` on error -- a stale
      // "Download PDF" link pointing at a non-existent PDF
      // would mislead the user.
    } finally {
      setPublishing(false);
    }
    // Bump outside the try/catch so it only fires on success.
    // The Zustand subscriber should have already updated the
    // selector by now, but the bump is a belt-and-braces
    // fallback for any state-flush edge case (see the comment
    // on the ``publishedAt`` state slot above).
    setPublishedAt((prev) => prev + 1);
  };

  /**
   * Download the workspace's LaTeX source. The endpoint
   * ``GET /workspaces/{id}/published-report.tex`` renders the
   * LaTeX on demand (the workspace must already have a report;
   * we don't require a prior PUBLISH because the rendering is
   * cheap and the LaTeX is what some users want without ever
   * needing the PDF).
   *
   * Same browser-side flow as the auto-download in
   * ``handlePublish``: temporary ``<a download>`` element +
   * click + cleanup on next tick.
   */
  const handleDownloadTex = async () => {
    if (!workspaceId) return;
    setTexError(null);
    try {
      const a = document.createElement('a');
      a.href = api.getPublishedTexUrl(workspaceId);
      a.download = `report-${workspaceId}.tex`;
      a.rel = 'noopener noreferrer';
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
      }, 0);
    } catch (err) {
      setTexError(
        err instanceof Error ? err.message : 'Failed to download LaTeX.',
      );
    }
  };

  // Build the PDF download URL lazily. The endpoint sets
  // ``Content-Disposition: attachment`` so the browser will
  // save the file rather than navigate away. We only compute
  // this when there's a PDF to download -- calling the URL
  // for an unpublished workspace returns 404.
  //
  // We subscribe to ``currentWorkspace`` via the Zustand
  // selector so the component re-renders when
  // ``runAction('publish')`` writes the post-publish
  // workspace into the store. ``published_report_available``
  // is the specific field we care about; we select it
  // directly (rather than the whole object) so unrelated
  // state changes don't trigger a re-render.
  //
  // We also re-read it via a local state bump that the
  // ``handlePublish`` ``finally`` block flips. The
  // Zustand selector is the primary signal, but the local
  // bump is a belt-and-braces fallback for any test mocks
  // or production edge cases where the store write happens
  // synchronously but the selector subscriber hasn't yet
  // flushed. The cost is one extra state slot and a single
  // ``setState`` per publish -- negligible.
  const [publishedAt, setPublishedAt] = useState<number>(0);
  const publishedReportAvailable = useWorkspaceStore(
    (state) => state.currentWorkspace?.published_report_available ?? false,
  );
  const downloadUrl =
    workspaceId && (publishedReportAvailable || publishedAt > 0)
      ? api.getPublishedReportUrl(workspaceId)
      : null;

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

  // The legacy ``/reports/generate`` endpoint (which the frontend
  // still uses) returns a structured 409 envelope when the
  // workspace is in ERROR. We surface both the user-visible
  // ``last_error`` string from the envelope AND the
  // ``current_state`` so the user knows whether a Retry will
  // work or whether they need to recover first.
  //
  // The frontend's `Retry` button now also handles the
  // recover-from-ERROR path: if the workspace is in ERROR,
  // we run the FSM RETRY action first to move it back to
  // CREATED, then re-attempt generation. This matches what
  // the FSM contract expects and prevents the user from
  // getting stuck in a 409 loop clicking "Retry".
  const errorEnvelope: {
    error?: string;
    message?: string;
    current_state?: string;
    last_error?: string | null;
    /**
     * v5 schema: UTC timestamp paired with ``last_error``.
     * ``null`` for non-ERROR workspaces. Used by the error
     * UI to render an "at HH:MM:SS" stamp next to the
     * detail -- the user can tell fresh vs stale failures.
     */
    last_error_at?: string | null;
    allowed_actions?: string[];
  } | null = (() => {
    const candidate = (error ?? genError) as
      { detail?: unknown } | null;
    if (
      candidate &&
      typeof candidate === 'object' &&
      'detail' in candidate &&
      candidate.detail &&
      typeof candidate.detail === 'object'
    ) {
      return candidate.detail as {
        error?: string;
        message?: string;
        current_state?: string;
        last_error?: string | null;
        allowed_actions?: string[];
      };
    }
    return null;
  })();

  // Distinguish the three failure shapes:
  //   - "report_generation_failed": the LLM/provider call
  //     crashed; the workspace is in ERROR.
  //   - "illegal_workspace_action": the FSM rejected the
  //     action before it ran; the workspace is still in a
  //     normal state and a plain Retry can succeed.
  //   - anything else: a generic network/transport error;
  //     same Retry path as before.
  const isRecoverable =
    errorEnvelope?.error === 'report_generation_failed' &&
    errorEnvelope?.current_state === 'ERROR';

  if (error || genError) {
    const headerMessage = isRecoverable
      ? 'Report generation hit an error.'
      : 'Error generating report.';
    // Prefer ``last_error`` (the orchestrator's reason for the
    // failure) over the raw ``message`` (which can include the
    // exception type and the wrapped ``from exc`` detail). Both
    // are user-visible; ``last_error`` is the action that
    // actually failed.
    const detailMessage =
      errorEnvelope?.last_error ??
      errorEnvelope?.message ??
      error?.message ??
      (typeof genError === 'string' ? genError : null);
    // ``last_error_at`` -- the UTC timestamp paired with
    // ``last_error`` (v5 schema). When present we render a
    // small "at HH:MM:SS" stamp next to the error detail so
    // the user can tell whether the failure is fresh or
    // stale. Particularly useful after a container restart,
    // where the timestamp is the only signal of when the
    // error actually happened.
    const errorAt = errorEnvelope?.last_error_at ?? null;
    const errorAtLabel =
      errorAt != null
        ? new Date(errorAt).toLocaleString(undefined, {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            month: 'short',
            day: 'numeric',
          })
        : null;
    const recoverHint = isRecoverable
      ? 'The workspace is in an error state. Click "Recover & Retry" to reset it and try again.'
      : null;

    return (
        <div className="page section flex items-center justify-center min-h-screen">
          <div className="text-center text-error">
            <p>{headerMessage}</p>
            {detailMessage && (
              <p
                className="text-sm text-secondary mt-2"
                data-testid="report-error-detail"
              >
                {detailMessage}
                {errorAtLabel && (
                  <>
                    {' '}
                    <span
                      className="text-xs opacity-75"
                      data-testid="report-error-detail-at"
                    >
                      (at {errorAtLabel})
                    </span>
                  </>
                )}
              </p>
            )}
            {recoverHint && (
              <p
                className="text-sm text-secondary mt-2"
                data-testid="report-error-recover-hint"
              >
                {recoverHint}
              </p>
            )}
            <button
              className="btn btn-outline mt-4"
              data-action="report-retry"
              onClick={async () => {
                // Two paths:
                //
                //   1. ``isRecoverable`` is true: the
                //      workspace is in ERROR. Run the FSM
                //      RETRY action first to reset to
                //      CREATED, then re-attempt generation.
                //   2. Otherwise: just refresh the
                //      workspace and re-attempt generation
                //      (handles transient network blips,
                //      FSM-rejected illegal actions, etc).
                if (!workspaceId) return;
                setInFlight(true);
                setPhase('Loading workspace…');
                try {
                  if (isRecoverable) {
                    // ``runAction('retry')`` is the
                    // FSM-aware path (POST .../actions/retry).
                    // The legacy /reports/generate endpoint
                    // does NOT have a corresponding retry --
                    // only the FSM action moves ERROR -> CREATED.
                    await runAction('retry');
                    // ``runAction`` already refetches via
                    // ``setCurrentWorkspace`` internally; we
                    // call ``fetchWorkspace`` again so the
                    // local React state mirrors what the
                    // server actually has after the retry.
                    await fetchWorkspace(workspaceId);
                  } else {
                    await fetchWorkspace(workspaceId);
                  }
                  await handleGenerateReport();
                } catch (err) {
                  setGenError(err instanceof Error ? err.message : 'Failed to retry.');
                }
              }}
            >
              <RefreshCw size={16}/>
              {isRecoverable ? 'Recover & Retry' : 'Retry'}
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
  const reportBody = linkifyCitationMarkers(
    report.summary.replace(/^# .*\n?/, ""),
    report.citations.length,
  );

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

            {/* PUBLISH action: renders a PDF on the server and
                auto-downloads it (via a hidden ``<a>`` click
                in ``handlePublish``). The button is disabled
                during the in-flight call (visual spinner via
                the disabled state) and shows a separate error
                if it fails. ``data-action="publish-pdf"`` is
                kept for end-to-end tests that grep the
                rendered DOM. */}
            <button
                className="btn btn-primary"
                onClick={handlePublish}
                disabled={publishing}
                data-action="publish-pdf"
                aria-busy={publishing}
            >
              <Download size={16}/>
              {publishing ? 'Generating…' : 'Generate PDF'}
            </button>

            {/* LaTeX download: a separate button so users can
                grab the editable source without going through
                the PDF flow. The LaTeX endpoint renders on
                demand (no FSM state change) and we trigger
                the browser download via a hidden ``<a>``
                click. Same pattern as the PDF auto-download.
                The button is blue (btn-primary on a fresh
                colour variant) -- visually distinct from the
                PDF button so the user knows they're getting
                different artefacts. We use the ``data-action``
                attribute for end-to-end test selection. */}
            <button
                className="btn btn-secondary"
                onClick={handleDownloadTex}
                disabled={!report}
                data-action="download-tex"
                title={
                  report
                    ? 'Download the LaTeX source for this report'
                    : 'Generate a report before downloading the LaTeX source'
                }
            >
              <FileText size={16}/>
              Generate TeX
            </button>

            <button
                className="btn btn-outline"
                onClick={() => navigate(`/workspace/${workspaceId}`)}
            >
              Back to Workspace
            </button>
          </div>

          {pubError && (
            <div
              className="text-error text-sm mt-2"
              role="alert"
              data-testid="publish-error"
            >
              Failed to publish PDF: {pubError}
            </div>
          )}

          {texError && (
            <div
              className="text-error text-sm mt-2"
              role="alert"
              data-testid="download-tex-error"
            >
              Failed to download LaTeX: {texError}
            </div>
          )}
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
                          id={citationAnchorId(idx + 1)}
                          className="text-secondary text-sm leading-relaxed"
                      >
                        <span className="text-primary font-semibold mr-2">
                          [{idx + 1}]
                        </span>
                        {renderCitationWithDoiLink(
                          linkifyCitationDoi(citation)
                        )}
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
                        {renderItemWithCitationLinks(
                          linkifyCitationMarkers(item, report.citations.length)
                        )}
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
                        {renderItemWithCitationLinks(
                          linkifyCitationMarkers(item, report.citations.length)
                        )}
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