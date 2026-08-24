// comparison.ts
/**
 * comparison.ts
 * --------------
 * Frontend TypeScript definitions for the cross-paper evidence
 * comparison returned by the backend.
 *
 * @module models/comparison
 */

export interface FindingResponse {
  claim: string;
  paper_ids: string[];
  evidence_strength: string | null;
  notes: string | null;
}

export interface ContradictionResponse {
  topic: string;
  description: string;
  paper_ids: string[];
  severity: string | null;
}

export interface MatrixCellResponse {
  paper_id: string;
  facets: Record<string, string>;
}

export interface EvidenceMatrixResponse {
  columns: string[];
  rows: MatrixCellResponse[];
  used_paper_ids: string[];
}

export interface EvidenceComparisonResponse {
  consensus: FindingResponse[];
  contradictions: ContradictionResponse[];
  research_gaps: string[];
  future_directions: string[];
  used_paper_ids: string[];
  matrix: EvidenceMatrixResponse | null;
  metadata: Record<string, string>;
}
