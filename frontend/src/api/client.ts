// client.ts
/**
 * client.ts
 * ----------
 * HTTP client for the BioResearch AI REST API.
 *
 * This module provides a typed interface for all backend endpoints,
 * including health checks, literature search, workspace management,
 * FSM actions, evidence comparison, and report generation.
 *
 * The client uses the native `fetch` API and returns parsed JSON.
 * All methods are async and throw on HTTP errors.
 *
 * Base URL is configurable via the `VITE_API_BASE_URL` environment
 * variable (defaults to `http://localhost:8000`).
 *
 * @module client
 */

import type {
  WorkspaceRequest,
  WorkspaceResponse,
  WorkspaceStatusResponse,
} from '../models/workspace';
import type {
  EvidenceComparisonResponse,
} from '../models/comparison';
import type { ReportRequest, ReportResponse } from '../models/report';
import type { Paper, PaperRequest } from '../models/paper';

/**
 * Response payload for identifier resolution.
 *
 * The backend returns one entry per submitted identifier, in the
 * same order. Each entry has either ``resolved`` or ``failed``
 * populated; never both.
 */
export interface ResolvePaperResponse {
  identifier: string;
  identifier_type: 'pmid' | 'doi';
  paper: Paper;
}

export interface FailedResolution {
  identifier: string;
  reason: string;
}

export interface ResolveResultEntry {
  resolved: ResolvePaperResponse | null;
  failed: FailedResolution | null;
}

export interface ResolvePapersResponse {
  results: ResolveResultEntry[];
  resolved_count: number;
  failed_count: number;
}

/**
 * Request payload for literature search.
 */
export interface SearchRequest {
  question: string;
}

/**
 * Response payload for literature search.
 */
export interface SearchResponse {
  query: string;
  source: string;
  total_results: number;
  retrieved_at: string;
  papers: Paper[];
}

/**
 * Response from literature search.
 */
export interface SearchResponseWrapped {
  query: string;
  source: string;
  total_results: number;
  retrieved_at: string;
  papers: Paper[];
}

/**
 * Base configuration for the API client.
 */
const DEFAULT_BASE_URL = 'http://localhost:8000';
const BASE_URL = import.meta.env?.VITE_API_BASE_URL ?? DEFAULT_BASE_URL;

/**
 * Helper to construct full URL for a given path.
 */
function buildUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

/**
 * Structured error thrown by every API client method when the
 * backend returns a non-2xx response.
 *
 * The shape mirrors FastAPI's ``HTTPException`` body: ``detail``
 * is either a string (the message) or a structured object
 * (with ``error`` / ``message`` keys). Callers that want to
 * distinguish between error codes (e.g. ``no_identifiers_found``
 * vs ``title_no_confident_match``) can inspect
 * ``err.detail?.error`` directly.
 */
export class APIError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Wrapper for `fetch` that handles JSON serialisation, error responses,
 * and throws consistent errors.
 */
async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    let detail: unknown = 'Unknown error';
    try {
      const errorBody = await response.json();
      detail = (errorBody as { detail?: unknown }).detail ?? errorBody;
    } catch {
      detail = response.statusText || `HTTP ${response.status}`;
    }
    const detailStr =
      typeof detail === 'string' ? detail : JSON.stringify(detail);
    throw new APIError(
      response.status,
      detail,
      `API error ${response.status}: ${detailStr}`,
    );
  }

  return response.json();
}

/**
 * Multipart upload variant. The browser computes the
 * Content-Type (with boundary) so we deliberately do NOT set
 * a ``Content-Type`` header — the body must be a ``FormData``
 * instance, which the browser serialises with the right
 * ``multipart/form-data; boundary=…`` header.
 */
async function fetchMultipart<T>(
  url: string,
  formData: FormData,
): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    let detail: unknown = 'Unknown error';
    try {
      const errorBody = await response.json();
      detail = (errorBody as { detail?: unknown }).detail ?? errorBody;
    } catch {
      detail = response.statusText || `HTTP ${response.status}`;
    }
    const detailStr =
      typeof detail === 'string' ? detail : JSON.stringify(detail);
    throw new APIError(
      response.status,
      detail,
      `API error ${response.status}: ${detailStr}`,
    );
  }

  return response.json();
}

/**
 * API client object containing methods for each backend endpoint.
 */
export const api = {
  /** Health check endpoint. */
  health: (): Promise<{ status: string }> => {
    return fetchJson(buildUrl('/health'));
  },

  /** Root endpoint. */
  root: (): Promise<{ application: string; status: string }> => {
    return fetchJson(buildUrl('/'));
  },

  /** Search literature using the main `/search` endpoint. */
  search: (request: SearchRequest): Promise<SearchResponse> => {
    return fetchJson(buildUrl('/search'), {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  /** Search literature using the legacy `/papers/search` endpoint. */
  searchPapers: (request: SearchRequest): Promise<SearchResponse> => {
    return fetchJson(buildUrl('/papers/search'), {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  /** Create a new Research Workspace. */
  createWorkspace: (request: WorkspaceRequest): Promise<WorkspaceResponse> => {
    return fetchJson(buildUrl('/workspaces'), {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  /** Retrieve an existing Workspace by ID. */
  getWorkspace: (workspaceId: string): Promise<WorkspaceResponse> => {
    return fetchJson(buildUrl(`/workspaces/${workspaceId}`));
  },

  /** Update an existing Workspace (currently only the question can be changed). */
  updateWorkspace: (
    workspaceId: string,
    request: WorkspaceRequest,
  ): Promise<WorkspaceResponse> => {
    return fetchJson(buildUrl(`/workspaces/${workspaceId}`), {
      method: 'PUT',
      body: JSON.stringify(request),
    });
  },

  /** Generate a research report from a workspace (legacy). */
  generateReport: (request: ReportRequest): Promise<ReportResponse> => {
    return fetchJson(buildUrl('/reports/generate'), {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  // ------------------------------------------------------------------
  // FSM action endpoints
  // ------------------------------------------------------------------

  /**
   * Run the SEARCH action on a workspace.
   */
  runSearchAction: (
    workspaceId: string,
    query?: string,
  ): Promise<WorkspaceResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/actions/search`),
      {
        method: 'POST',
        body: JSON.stringify({ query: query ?? null }),
      },
    );
  },

  /** Run the SUMMARIZE action on a workspace. */
  runSummarizeAction: (workspaceId: string): Promise<WorkspaceResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/actions/summarize`),
      { method: 'POST' },
    );
  },

  /** Run the COMPARE action on a workspace. */
  runCompareAction: (workspaceId: string): Promise<WorkspaceResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/actions/compare`),
      { method: 'POST' },
    );
  },

  /** Run the REPORT action on a workspace. */
  runReportAction: (workspaceId: string): Promise<WorkspaceResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/actions/report`),
      { method: 'POST' },
    );
  },

  /** Run the COMPLETE action on a workspace. */
  runCompleteAction: (workspaceId: string): Promise<WorkspaceResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/actions/complete`),
      { method: 'POST' },
    );
  },

  /** Run the RETRY action on a workspace. */
  runRetryAction: (workspaceId: string): Promise<WorkspaceResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/actions/retry`),
      { method: 'POST' },
    );
  },

  /** Return the FSM status of a workspace. */
  getTransitions: (workspaceId: string): Promise<WorkspaceStatusResponse> => {
    return fetchJson(buildUrl(`/workspaces/${workspaceId}/transitions`));
  },

  /** Return the stored evidence comparison for a workspace. */
  getEvidenceComparison: (
    workspaceId: string,
  ): Promise<EvidenceComparisonResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/evidence-comparison`),
    );
  },

  // ------------------------------------------------------------------
  // Paper management
  // ------------------------------------------------------------------

  /**
   * Resolve a batch of PMIDs/DOIs to full paper metadata.
   *
   * Used by the AddPapersPanel when the user pastes a list of
   * identifiers. Returns per-identifier status (resolved or
   * failed) so the frontend can show chips next to each entry.
   * Does NOT modify the workspace.
   */
  resolvePapers: (
    workspaceId: string,
    identifiers: string[],
  ): Promise<ResolvePapersResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/papers/resolve`),
      {
        method: 'POST',
        body: JSON.stringify({ identifiers }),
      },
    );
  },

  /**
   * Add several papers to the workspace in one transaction.
   *
   * Called after ``resolvePapers`` to commit the resolved
   * metadata. The orchestrator dedupes by PMID/DOI, so duplicate
   * entries from a mistyped batch are silently dropped.
   */
  addPapersBulk: (
    workspaceId: string,
    papers: PaperRequest[],
  ): Promise<WorkspaceResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/papers/bulk`),
      {
        method: 'POST',
        body: JSON.stringify(papers),
      },
    );
  },

  /**
   * Resolve one PMID/DOI and add the paper to the workspace.
   *
   * One-shot "add this paper" endpoint for the simplest workflow.
   * The identifier is passed as a query parameter (not a path
   * parameter) because DOIs contain ``/`` which would otherwise
   * need URL-encoding gymnastics.
   */
  resolveAndAddPaper: (
    workspaceId: string,
    identifier: string,
  ): Promise<WorkspaceResponse> => {
    const params = new URLSearchParams({ identifier });
    return fetchJson(
      buildUrl(
        `/workspaces/${workspaceId}/papers/fetch?${params.toString()}`,
      ),
      { method: 'POST' },
    );
  },

  /**
   * Upload a PDF, extract DOI/PMID from the first page, and
   * add the resolved paper to the workspace.
   *
   * The backend uses the same IdentifierResolver that the
   * bulk-paste and one-shot-fetch flows use, so the response is
   * a normal WorkspaceResponse (same shape as ``addPaper``).
   */
  uploadPdf: (
    workspaceId: string,
    file: File,
  ): Promise<WorkspaceResponse> => {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return fetchMultipart<WorkspaceResponse>(
      buildUrl(`/workspaces/${workspaceId}/papers/from-pdf`),
      formData,
    );
  },

  /**
   * Add a paper to the workspace by title.
   *
   * Used as the title-driven fallback when the user dropped a
   * PDF that didn't yield a recognisable DOI or PMID on its
   * first page. The backend runs PubMed ESearch with the title
   * (and any optional disambiguation hints), picks the top
   * match, and adds it to the workspace.
   *
   * The backend's response shape is the same WorkspaceResponse
   * the other ``addPaper*`` methods return, so callers can
   * feed the result straight into the workspace store.
   *
   * Throws an ``Error`` with a parsed ``detail.error`` field
   * when the backend returns 422 ``title_no_confident_match``
   * — the frontend catches that to surface a "no precise
   * match" UI rather than a generic error toast.
   */
  addPaperByTitle: (
    workspaceId: string,
    payload: import('../models/paper').FindByTitleRequest,
  ): Promise<WorkspaceResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/papers/from-title`),
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    );
  },

  /**
   * Add a paper to the workspace manually. Used by the frontend's
   * "Upload paper" form for papers that aren't in PubMed (or that
   * the user already knows the metadata for). Returns the updated
   * workspace.
   */
  addPaper: (
    workspaceId: string,
    paper: PaperRequest,
  ): Promise<WorkspaceResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/papers`),
      {
        method: 'POST',
        body: JSON.stringify(paper),
      },
    );
  },

  /**
   * Remove a paper from the workspace by PMID or DOI. Returns the
   * updated workspace.
   */
  removePaper: (
    workspaceId: string,
    paperId: string,
  ): Promise<WorkspaceResponse> => {
    return fetchJson(
      buildUrl(`/workspaces/${workspaceId}/papers/${encodeURIComponent(paperId)}`),
      { method: 'DELETE' },
    );
  },
};
