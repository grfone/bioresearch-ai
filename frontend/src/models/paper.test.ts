import { describe, it, expect } from 'vitest';
import { googleScholarUrl, hasDoi } from '../models/paper';
import type { Paper } from '../models/paper';

function makePaper(overrides: Partial<Paper> = {}): Paper {
  return {
    title: 'Sample paper title',
    authors: [],
    journal: null,
    year: 2024,
    abstract: '',
    doi: null,
    pmid: null,
    keywords: [],
    url: '',
    ...overrides,
  };
}

describe('googleScholarUrl', () => {
  it('uses DOI when present', () => {
    const paper = makePaper({
      doi: '10.1038/nature14539',
      pmid: null,
      title: 'Deep learning',
    });
    const url = googleScholarUrl(paper);
    expect(url).not.toBeNull();
    expect(url!).toContain('scholar.google.com/scholar');
    expect(url!).toContain('q=10.1038%2Fnature14539');
  });

  it('uses PMID when DOI is missing', () => {
    const paper = makePaper({
      doi: null,
      pmid: '12345678',
      title: 'Some title',
    });
    const url = googleScholarUrl(paper);
    expect(url).not.toBeNull();
    expect(url!).toContain('q=PMID%3A12345678');
  });

  it('uses quoted title when both DOI and PMID are missing', () => {
    const paper = makePaper({
      doi: null,
      pmid: null,
      title: 'A study of amyloid cascade hypothesis',
    });
    const url = googleScholarUrl(paper);
    expect(url).not.toBeNull();
    // Quoted exact-phrase search
    // URLSearchParams uses + for spaces (form encoding)
    expect(url!).toContain('q=%22A+study+of+amyloid+cascade+hypothesis%22');
  });

  it('returns null when DOI, PMID, and title are all empty', () => {
    const paper = makePaper({
      doi: null,
      pmid: null,
      title: '',
    });
    expect(googleScholarUrl(paper)).toBeNull();
  });

  it('returns null when DOI and PMID are empty strings', () => {
    const paper = makePaper({
      doi: '   ',
      pmid: '',
      title: '',
    });
    expect(googleScholarUrl(paper)).toBeNull();
  });

  it('prefers DOI over PMID over title', () => {
    const paper = makePaper({
      doi: '10.1234/abc',
      pmid: '99999999',
      title: 'Some title',
    });
    const url = googleScholarUrl(paper);
    expect(url).not.toBeNull();
    expect(url!).toContain('q=10.1234%2Fabc');
    expect(url!).not.toContain('PMID');
    expect(url!).not.toContain('Some+title');
  });

  it('prefers PMID over title when DOI is missing', () => {
    const paper = makePaper({
      doi: null,
      pmid: '99999999',
      title: 'Some title',
    });
    const url = googleScholarUrl(paper);
    expect(url).not.toBeNull();
    expect(url!).toContain('q=PMID%3A99999999');
  });

  it('handles DOI with whitespace', () => {
    const paper = makePaper({
      doi: '  10.1234/abc  ',
      pmid: null,
      title: 'Some title',
    });
    const url = googleScholarUrl(paper);
    expect(url).not.toBeNull();
    // The whitespace is trimmed before URL-encoding.
    expect(url!).toContain('q=10.1234%2Fabc');
  });

  it('does not include any user-specific data', () => {
    const paper = makePaper({
      doi: '10.1234/abc',
      pmid: null,
      title: 'Some title',
    });
    const url = googleScholarUrl(paper)!;
    expect(url).toMatch(/^https:\/\/scholar\.google\.com\/scholar\?q=/);
    expect(url).not.toMatch(/user|session|token/);
  });
});

describe('hasDoi', () => {
  it('returns true for non-empty DOI', () => {
    expect(hasDoi(makePaper({ doi: '10.1038/x' }))).toBe(true);
  });

  it('returns false for null DOI', () => {
    expect(hasDoi(makePaper({ doi: null }))).toBe(false);
  });

  it('returns false for empty DOI', () => {
    expect(hasDoi(makePaper({ doi: '' }))).toBe(false);
  });

  it('returns false for whitespace-only DOI', () => {
    expect(hasDoi(makePaper({ doi: '   ' }))).toBe(false);
  });
});
