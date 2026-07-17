// client.ts
/**
 * client.ts
 * ----------
 * HTTP client for the BioResearch AI REST API.
 *
 * This module provides a typed interface for all backend endpoints,
 * including health checks, literature search, workspace management,
 * and report generation.
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
  SearchRequest,
  SearchResponse,
} from './search'; // We'll assume we have search.ts (similar to paper but for search)
// Actually we don't have search.ts yet, but we can define the types inside or import from paper?
// We can inline the types for search request/response.
// For simplicity, we define them here or import from separate file.
// Let's create a minimal SearchRequest and SearchResponse based on backend.

// We'll also import WorkspaceRequest, WorkspaceResponse, ReportRequest, ReportResponse from their modules.

import type { WorkspaceRequest, WorkspaceResponse } from '../models/workspace';
import type { ReportRequest, ReportResponse } from '../models/report';
import type { Paper } from '../models/paper';

// Since we don't have search.ts, we can define them here or create separate file.
// I'll create a search.ts later, but for client.ts we need them.
// For brevity, I'll define them inline.

/**
 * Request payload for literature search.
 */
export interface SearchRequest {
  /** Biomedical research question */
  question: string;
}

/**
 * Response from literature search.
 */
export interface SearchResponse {
  /** Original query */
  query: string;
  /** Literature source (e.g., "PubMed") */
  source: string;
  /** Total number of papers returned */
  total_results: number;
  /** UTC timestamp of search completion */
  retrieved_at: string;
  /** List of papers */
  papers: Paper[];
}

/**
 * Base configuration for the API client.
 */
const DEFAULT_BASE_URL = 'http://localhost:8000';
const BASE_URL = import.meta.env?.VITE_API_BASE_URL ?? DEFAULT_BASE_URL;

/**
 * Helper to construct full URL for a given path.
 *
 * @param path - API endpoint path (e.g., '/health').
 * @returns Full URL.
 */
function buildUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

/**
 * Wrapper for `fetch` that handles JSON serialisation, error responses,
 * and throws consistent errors.
 *
 * @param url - Full URL to fetch.
 * @param options - Fetch options.
 * @returns Parsed JSON response.
 * @throws {Error} If the HTTP response is not OK.
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
    let detail = 'Unknown error';
    try {
      const errorBody = await response.json();
      detail = errorBody.detail ?? JSON.stringify(errorBody);
    } catch {
      detail = response.statusText || `HTTP ${response.status}`;
    }
    throw new Error(`API error ${response.status}: ${detail}`);
  }

  return response.json();
}

/**
 * API client object containing methods for each backend endpoint.
 */
export const api = {
  /**
   * Health check endpoint.
   * @returns {Promise<{ status: string }>} Health status.
   */
  health: (): Promise<{ status: string }> => {
    return fetchJson(buildUrl('/health'));
  },

  /**
   * Root endpoint.
   * @returns {Promise<{ application: string; status: string }>} Application info.
   */
  root: (): Promise<{ application: string; status: string }> => {
    return fetchJson(buildUrl('/'));
  },

  /**
   * Search literature using the main `/search` endpoint.
   * @param request - Search request containing the question.
   * @returns {Promise<SearchResponse>} Search results.
   */
  search: (request: SearchRequest): Promise<SearchResponse> => {
    return fetchJson(buildUrl('/search'), {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  /**
   * Search literature using the legacy `/papers/search` endpoint.
   * Same payload and response as `/search`.
   */
  searchPapers: (request: SearchRequest): Promise<SearchResponse> => {
    return fetchJson(buildUrl('/papers/search'), {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  /**
   * Create a new Research Workspace.
   * @param request - Workspace creation payload.
   * @returns {Promise<WorkspaceResponse>} Created workspace.
   */
  createWorkspace: (request: WorkspaceRequest): Promise<WorkspaceResponse> => {
    return fetchJson(buildUrl('/workspaces'), {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  /**
   * Retrieve an existing Workspace by ID.
   * @param workspaceId - UUID of the workspace.
   * @returns {Promise<WorkspaceResponse>} Workspace data.
   */
  getWorkspace: (workspaceId: string): Promise<WorkspaceResponse> => {
    return fetchJson(buildUrl(`/workspaces/${workspaceId}`));
  },

  /**
   * Update an existing Workspace (currently only the question can be changed).
   * @param workspaceId - UUID of the workspace.
   * @param request - Updated workspace data.
   * @returns {Promise<WorkspaceResponse>} Updated workspace.
   */
  updateWorkspace: (workspaceId: string, request: WorkspaceRequest): Promise<WorkspaceResponse> => {
    return fetchJson(buildUrl(`/workspaces/${workspaceId}`), {
      method: 'PUT',
      body: JSON.stringify(request),
    });
  },

  /**
   * Generate a research report from a workspace.
   * @param request - Report generation options.
   * @returns {Promise<ReportResponse>} Generated report.
   */
  generateReport: (request: ReportRequest): Promise<ReportResponse> => {
    return fetchJson(buildUrl('/reports/generate'), {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },
};