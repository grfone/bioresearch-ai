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