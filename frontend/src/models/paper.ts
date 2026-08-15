// paper.ts
/**
 * paper.ts
 * ----------
 * Frontend TypeScript definitions for biomedical literature entities.
 *
 * These interfaces mirror the backend response schemas defined in
 * `search_response.py` and provide type safety when handling scientific
 * publications retrieved from the BioResearch AI API.
 *
 * The types are organized hierarchically:
 *
 * - Author          : individual author metadata
 * - Journal         : publishing journal metadata
 * - Paper           : complete scientific publication
 *
 * All interfaces use snake_case field names to match the JSON payloads
 * returned by the API, avoiding unnecessary transformation overhead.
 *
 * @module models/paper
 */

/**
 * Represents a scientific author.
 */
export interface Author {
  /** Author's given name(s) */
  first_name: string;
  /** Author's family name */
  last_name: string;
  /** Full name (first + last) */
  full_name: string;
  /** Institutional affiliation, if available */
  affiliation: string | null;
}

/**
 * Represents a scientific journal.
 */
export interface Journal {
  /** Journal title */
  name: string;
  /** International Standard Serial Number (optional) */
  issn: string | null;
  /** Publisher name (optional) */
  publisher: string | null;
}

/**
 * Represents a scientific publication (paper).
 *
 * This is the core entity used throughout the application for literature
 * retrieval and display. It contains all metadata necessary to cite,
 * reference, and summarise the publication.
 */
export interface Paper {
  /** Publication title */
  title: string;
  /** Ordered list of authors */
  authors: Author[];
  /** Publishing journal, if known */
  journal: Journal | null;
  /** Year of publication */
  year: number | null;
  /** Publication abstract (may be truncated) */
  abstract: string;
  /** Digital Object Identifier (DOI) */
  doi: string | null;
  /** PubMed ID (PMID) */
  pmid: string | null;
  /** Keywords or MeSH terms */
  keywords: string[];
  /** Direct URL to the publication (e.g., PubMed) */
  url: string | null;
}

/**
 * Helper function to determine whether a paper has a valid DOI.
 *
 * @param paper - The paper to check.
 * @returns True if the paper has a non‑empty DOI.
 */
export function hasDoi(paper: Paper): boolean {
  return !!paper.doi && paper.doi.trim().length > 0;
}

/**
 * Helper function to format a paper citation in a simple "Author et al." style.
 *
 * @param paper - The paper to format.
 * @param maxAuthors - Maximum number of authors to include before "et al.".
 * @returns A formatted citation string.
 */
export function formatPaperCitation(paper: Paper, maxAuthors = 3): string {
  const authors = paper.authors;
  if (authors.length === 0) return paper.title;

  let authorPart: string;
  if (authors.length <= maxAuthors) {
    authorPart = authors.map(a => a.full_name).join(', ');
  } else {
    const first = authors.slice(0, maxAuthors).map(a => a.full_name).join(', ');
    authorPart = `${first} et al.`;
  }

  const yearPart = paper.year ? ` (${paper.year})` : '';
  return `${authorPart}${yearPart}. ${paper.title}`;
}

// =====================================================================
// Manual upload types — used by the "Upload paper" form to add a paper
// to a workspace without going through PubMed. These mirror the
// backend PaperRequest schema.
// =====================================================================

/**
 * Author submitted by the user via the upload form.
 *
 * ``full_name`` is what the backend persists; ``given_name`` and
 * ``family_name`` are optional and only used when ``full_name`` is
 * empty (in which case the backend joins them with a space).
 */
export interface AuthorRequest {
  full_name: string;
  given_name?: string | null;
  family_name?: string | null;
}

/**
 * Journal submitted by the user via the upload form.
 */
export interface JournalRequest {
  name: string;
  issn?: string | null;
  publisher?: string | null;
}

/**
 * Payload the frontend sends to ``POST /workspaces/{id}/papers``.
 *
 * Only ``title`` is required; everything else is optional and may be
 * fleshed out later. The backend validates each field with Pydantic.
 */
export interface PaperRequest {
  title: string;
  authors?: AuthorRequest[];
  journal?: JournalRequest | null;
  year?: number | null;
  abstract?: string;
  doi?: string | null;
  pmid?: string | null;
  keywords?: string[];
  url?: string | null;
}

// =====================================================================
// Title-driven paper discovery — used by the title-fallback flow
// when the user dropped a PDF that didn't yield a recognisable
// DOI or PMID on its first page. The frontend offers an inline
// "Type the paper title" form, submits to
// ``POST /workspaces/{id}/papers/from-title``, and the backend
// runs PubMed ESearch with the title (plus optional hints).
// =====================================================================

/**
 * Body for ``POST /workspaces/{id}/papers/from-title``.
 *
 * Mirrors the backend ``FindByTitleRequest`` schema. ``title``
 * is required; the other fields are optional disambiguation
 * hints that the backend folds into the PubMed ESearch query.
 */
export interface FindByTitleRequest {
  title: string;
  first_author?: string | null;
  journal?: string | null;
  year?: number | null;
}
