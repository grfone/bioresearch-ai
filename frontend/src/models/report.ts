// report.ts
/**
 * report.ts
 * ----------
 * Frontend TypeScript definitions for research report generation.
 *
 * These interfaces mirror the backend request/response schemas from
 * `report_request.py` and `report_response.py`.
 *
 * A Report is the final synthesis of a biomedical investigation,
 * produced from the evidence collected in a Research Workspace.
 *
 * The module exports:
 *
 * - ReportRequest   : payload for generating a report
 * - ReportResponse  : complete report returned by the API
 *
 * All field names use snake_case to match the API contract.
 *
 * @module models/report
 */

/**
 * Request payload for generating a biomedical research report.
 *
 * The request references an existing workspace and optionally configures
 * sections to include in the final report.
 */
export interface ReportRequest {
  /** UUID of the workspace from which to generate the report */
  workspace_id: string;
  /** Whether to include a limitations section */
  include_limitations: boolean;
  /** Whether to include future work recommendations */
  include_future_work: boolean;
}

/**
 * Full report response returned by the API.
 *
 * Contains the synthesised summary, citations, and optional sections
 * such as limitations and future work.
 */
export interface ReportResponse {
  /** UUID of the source workspace */
  workspace_id: string;
  /** Executive summary of the evidence */
  summary: string;
  /** List of human‑readable citations supporting the report */
  citations: string[];
  /** Known limitations of the available evidence (if requested) */
  limitations: string[];
  /** Suggested future research directions (if requested) */
  future_work: string[];
  /** UTC timestamp when the report was generated */
  generated_at: string; // ISO 8601 date string
}

/**
 * Helper to check if a report contains any limitations.
 *
 * @param report - The report to check.
 * @returns True if limitations are present.
 */
export function hasLimitations(report: ReportResponse): boolean {
  return report.limitations.length > 0;
}

/**
 * Helper to check if a report contains future work suggestions.
 *
 * @param report - The report to check.
 * @returns True if future work is present.
 */
export function hasFutureWork(report: ReportResponse): boolean {
  return report.future_work.length > 0;
}