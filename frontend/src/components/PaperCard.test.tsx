// components/PaperCard.test.tsx
//
// Tests for the PaperCard component — the user-visible rendering
// of a single publication in the workspace paper list.
//
// These tests pin the three behaviours the consultant flagged:
//
// 1. A full paper renders title, authors (truncated to "et al."
//    after three), journal/year, abstract, and identifier badges
//    (DOI / PMID) each linking to its canonical resolver.
// 2. A thin paper (no authors AND no abstract) gets the
//    asterisk marker AND the warning banner — both render.
// 3. A paper that's missing only authors OR only abstract is
//    NOT marked thin — both fields have to be empty.
// 4. ``onRemove`` is wired correctly to the X button.
//
// We mock the workspace store so the cards can be tested in
// isolation without a real Zustand context.

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PaperCard, isThinPaper } from './PaperCard';
import type { Paper } from '../models/paper';

const FULL_PAPER: Paper = {
  title: 'The amyloid cascade hypothesis revisited.',
  authors: [
    { first_name: 'J A', last_name: 'Hardy', full_name: 'J A Hardy', affiliation: null },
    { first_name: 'G A', last_name: 'Higgins', full_name: 'G A Higgins', affiliation: null },
    { first_name: 'D J', last_name: 'Selkoe', full_name: 'D J Selkoe', affiliation: null },
  ],
  journal: { name: 'Science', issn: '0036-8075', publisher: 'AAAS' },
  year: 1992,
  abstract: 'A short abstract about amyloids in Alzheimer disease.',
  doi: '10.1126/science.1566067',
  pmid: '1566067',
  keywords: ['Alzheimer'],
  url: 'https://pubmed.ncbi.nlm.nih.gov/1566067/',
};

const THIN_PAPER: Paper = {
  title: 'A 2025 conference abstract with no metadata.',
  authors: [],
  journal: null,
  year: 2025,
  abstract: '',
  doi: '10.9999/bogus-doi',
  pmid: null,
  keywords: [],
  url: null,
};

const NO_AUTHORS_PAPER: Paper = {
  ...FULL_PAPER,
  authors: [],
};

const NO_ABSTRACT_PAPER: Paper = {
  ...FULL_PAPER,
  abstract: '',
};

describe('isThinPaper', () => {
  it('returns true when both authors and abstract are empty', () => {
    expect(isThinPaper(THIN_PAPER)).toBe(true);
  });

  it('returns false when only authors are empty', () => {
    // Even without authors, an abstract gives the LLM stages
    // something to work with.
    expect(isThinPaper(NO_AUTHORS_PAPER)).toBe(false);
  });

  it('returns false when only abstract is empty', () => {
    // Same logic in the other direction — authors alone is
    // enough metadata.
    expect(isThinPaper(NO_ABSTRACT_PAPER)).toBe(false);
  });

  it('returns false for a fully populated paper', () => {
    expect(isThinPaper(FULL_PAPER)).toBe(false);
  });

  it('treats whitespace-only abstract as empty', () => {
    expect(isThinPaper({ ...FULL_PAPER, abstract: '   \n  ' })).toBe(false);
    // Authors + non-whitespace abstract both present — full paper.
    // Stripped whitespace abstract + empty authors -> thin.
    expect(
      isThinPaper({
        ...FULL_PAPER,
        authors: [],
        abstract: '   ',
      }),
    ).toBe(true);
  });
});

describe('PaperCard', () => {
  describe('full paper rendering', () => {
    it('renders the title and metadata', () => {
      render(<PaperCard paper={FULL_PAPER} />);
      expect(
        screen.getByText('The amyloid cascade hypothesis revisited.'),
      ).toBeInTheDocument();
    });

    it('renders all three authors as a comma-separated list', () => {
      render(<PaperCard paper={FULL_PAPER} />);
      // Authors are visible as a single text node joined by ", "
      const authorsLine = screen.getByText(/J A Hardy/);
      expect(authorsLine.textContent).toContain('G A Higgins');
      expect(authorsLine.textContent).toContain('D J Selkoe');
    });

    it('truncates author list with "et al." beyond three authors', () => {
      const manyAuthors: Paper = {
        ...FULL_PAPER,
        authors: [
          { first_name: 'A', last_name: 'Author1', full_name: 'A Author1', affiliation: null },
          { first_name: 'B', last_name: 'Author2', full_name: 'B Author2', affiliation: null },
          { first_name: 'C', last_name: 'Author3', full_name: 'C Author3', affiliation: null },
          { first_name: 'D', last_name: 'Author4', full_name: 'D Author4', affiliation: null },
        ],
      };
      render(<PaperCard paper={manyAuthors} />);
      expect(screen.getByText(/A Author1, B Author2, C Author3 et al\./)).toBeInTheDocument();
    });

    it('renders journal + year as a citation line', () => {
      render(<PaperCard paper={FULL_PAPER} />);
      expect(screen.getByText('Science, 1992')).toBeInTheDocument();
    });

    it('renders the abstract when present', () => {
      render(<PaperCard paper={FULL_PAPER} />);
      expect(
        screen.getByText(/A short abstract about amyloids/),
      ).toBeInTheDocument();
    });

    it('renders DOI and PMID identifier badges', () => {
      render(<PaperCard paper={FULL_PAPER} />);
      const doiBadge = screen.getByText(/DOI: 10\.1126\/science\.1566067/);
      const pmidBadge = screen.getByText(/PMID: 1566067/);
      expect(doiBadge).toBeInTheDocument();
      expect(pmidBadge).toBeInTheDocument();
      // Each badge is a link to its canonical resolver.
      expect(doiBadge.closest('a')).toHaveAttribute(
        'href',
        'https://doi.org/10.1126/science.1566067',
      );
      expect(pmidBadge.closest('a')).toHaveAttribute(
        'href',
        'https://pubmed.ncbi.nlm.nih.gov/1566067/',
      );
    });

    it('omits the partial-metadata marker for a full paper', () => {
      const { container } = render(<PaperCard paper={FULL_PAPER} />);
      // The marker is a span with class .paper-title-partial-marker.
      expect(
        container.querySelector('.paper-title-partial-marker'),
      ).not.toBeInTheDocument();
      // The warning banner also shouldn't render.
      expect(
        container.querySelector('.paper-thin-warning'),
      ).not.toBeInTheDocument();
    });
  });

  describe('thin-metadata paper', () => {
    it('renders the asterisk marker next to the title', () => {
      render(<PaperCard paper={THIN_PAPER} />);
      // The asterisk is wrapped in a span with the marker class.
      // React inserts whitespace around the JSX expression
      // ``{' *'}`` so the rendered text starts with a space —
      // match by selector instead of by literal text.
      const marker = document.querySelector(
        '.paper-title-partial-marker',
      );
      expect(marker).not.toBeNull();
      expect(marker?.textContent).toMatch(/\*/);
      expect(marker).toHaveAttribute(
        'title',
        expect.stringContaining('Partial metadata'),
      );
      expect(marker).toHaveAttribute(
        'aria-label',
        expect.stringContaining('Partial metadata'),
      );
    });

    it('renders the warning banner under the metadata', () => {
      render(<PaperCard paper={THIN_PAPER} />);
      const warning = document.querySelector('.paper-thin-warning');
      expect(warning).toBeInTheDocument();
      expect(warning?.textContent).toContain(
        'CrossRef returned only the title',
      );
    });

    it('marks the card with data-thin-metadata="true"', () => {
      const { container } = render(<PaperCard paper={THIN_PAPER} />);
      const card = container.querySelector('[data-thin-metadata]');
      expect(card).toBeInTheDocument();
      expect(card?.getAttribute('data-thin-metadata')).toBe('true');
    });
  });

  describe('paper missing one field only', () => {
    it('does NOT mark thin when only authors are missing', () => {
      const { container } = render(<PaperCard paper={NO_AUTHORS_PAPER} />);
      expect(
        container.querySelector('.paper-title-partial-marker'),
      ).not.toBeInTheDocument();
    });

    it('does NOT mark thin when only abstract is missing', () => {
      const { container } = render(<PaperCard paper={NO_ABSTRACT_PAPER} />);
      expect(
        container.querySelector('.paper-title-partial-marker'),
      ).not.toBeInTheDocument();
    });
  });

  describe('showPartialMarker=false', () => {
    it('suppresses the marker and banner when explicitly disabled', () => {
      const { container } = render(
        <PaperCard paper={THIN_PAPER} showPartialMarker={false} />,
      );
      expect(
        container.querySelector('.paper-title-partial-marker'),
      ).not.toBeInTheDocument();
      expect(
        container.querySelector('.paper-thin-warning'),
      ).not.toBeInTheDocument();
    });
  });

  describe('remove button', () => {
    it('does not render when onRemove is undefined', () => {
      render(<PaperCard paper={FULL_PAPER} />);
      expect(
        screen.queryByRole('button', { name: /remove paper/i }),
      ).not.toBeInTheDocument();
    });

    it('calls onRemove with the paper when clicked', () => {
      const onRemove = vi.fn();
      render(<PaperCard paper={FULL_PAPER} onRemove={onRemove} />);
      const removeButton = screen.getByRole('button', {
        name: /remove paper/i,
      });
      fireEvent.click(removeButton);
      expect(onRemove).toHaveBeenCalledTimes(1);
      expect(onRemove).toHaveBeenCalledWith(FULL_PAPER);
    });
  });

  describe('external link', () => {
    it('does not render when paper.url is null', () => {
      const paperWithoutUrl: Paper = { ...FULL_PAPER, url: null };
      render(<PaperCard paper={paperWithoutUrl} />);
      expect(
        screen.queryByRole('link', { name: /open paper/i }),
      ).not.toBeInTheDocument();
    });

    it('renders a link to paper.url when present', () => {
      render(<PaperCard paper={FULL_PAPER} />);
      const link = screen.getByRole('link', { name: /open paper/i });
      expect(link).toHaveAttribute('href', FULL_PAPER.url ?? '');
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    });
  });


  describe('source badge', () => {
    it('does not render a badge when source is undefined', () => {
      // Legacy PubMed-only workspaces — no badge.
      const { container } = render(<PaperCard paper={FULL_PAPER} />);
      expect(
        container.querySelector('.paper-source-badge'),
      ).toBeNull();
    });

    it('renders a "via openalex" badge when source is openalex', () => {
      const { container } = render(
        <PaperCard paper={FULL_PAPER} source="openalex" />,
      );
      const badge = container.querySelector('.paper-source-badge');
      expect(badge).not.toBeNull();
      expect(badge!.textContent).toMatch(/openalex/i);
      expect(badge!.getAttribute('data-source')).toBe('openalex');
    });

    it('renders a "via europe_pmc" badge for europe_pmc', () => {
      const { container } = render(
        <PaperCard paper={FULL_PAPER} source="europe_pmc" />,
      );
      const badge = container.querySelector('.paper-source-badge');
      expect(badge!.textContent).toMatch(/europe_pmc/i);
    });

    it('renders a "via biorxiv" badge for biorxiv', () => {
      const { container } = render(
        <PaperCard paper={FULL_PAPER} source="biorxiv" />,
      );
      const badge = container.querySelector('.paper-source-badge');
      expect(badge!.textContent).toMatch(/biorxiv/i);
    });

    it('renders a "via pubmed" badge for legacy single-source', () => {
      // The legacy single-source path also populates
      // paper_sources (since search_with_filters replaces
      // the legacy search in the modal), but the test
      // confirms the badge text is consistent.
      const { container } = render(
        <PaperCard paper={FULL_PAPER} source="pubmed" />,
      );
      const badge = container.querySelector('.paper-source-badge');
      expect(badge!.textContent).toMatch(/pubmed/i);
    });

    it('does not affect the partial-marker badge', () => {
      // A thin paper with source="openalex" should still
      // render the asterisk marker AND the source badge.
      const { container } = render(
        <PaperCard paper={THIN_PAPER} source="openalex" />,
      );
      expect(
        container.querySelector('.paper-title-partial-marker'),
      ).not.toBeNull();
      expect(
        container.querySelector('.paper-source-badge'),
      ).not.toBeNull();
  describe('Scholar escape-hatch link', () => {
    it('does NOT render the Scholar link when the abstract is present', () => {
      // When the paper has a full abstract, the user doesn't
      // need a Scholar escape hatch -- the abstract is right
      // there on the card.
      const { container } = render(<PaperCard paper={FULL_PAPER} />);
      expect(
        container.querySelector('.paper-identifier--scholar'),
      ).toBeNull();
    });

    it('renders the Scholar link when abstract is missing but DOI is present', () => {
      // NO_ABSTRACT_PAPER has doi set and abstract empty.
      // The link should be there as the escape hatch.
      const { container } = render(<PaperCard paper={NO_ABSTRACT_PAPER} />);
      const link = container.querySelector('.paper-identifier--scholar');
      expect(link).not.toBeNull();
      // Should be an <a> tag with the Scholar URL containing the DOI.
      expect(link!.tagName).toBe('A');
      expect(link!.getAttribute('href')).toMatch(
        /^https:\/\/scholar\.google\.com\/scholar\?q=10\.1126/,
      );
      expect(link!.getAttribute('target')).toBe('_blank');
      expect(link!.getAttribute('rel')).toMatch(/noopener/);
    });

    it('renders the Scholar link when abstract is missing AND DOI is missing', () => {
      // Title-only fallback path. THIN_PAPER has a doi though,
      // so we need a custom fixture.
      const noDoiPaper: Paper = {
        ...NO_ABSTRACT_PAPER,
        doi: null,
        pmid: null,
      };
      const { container } = render(<PaperCard paper={noDoiPaper} />);
      const link = container.querySelector('.paper-identifier--scholar');
      expect(link).not.toBeNull();
      // URL should contain the quoted title.
      expect(link!.getAttribute('href')).toMatch(
        /q=%22The\+amyloid\+cascade\+hypothesis\+revisited\.%22/,
      );
    });

    it('does NOT render the Scholar link when abstract is missing AND title is empty', () => {
      // No DOI, no PMID, no title -- nothing to search by.
      // The link should not render (and we don't crash).
      const emptyPaper: Paper = {
        ...NO_ABSTRACT_PAPER,
        doi: null,
        pmid: null,
        title: '',
      };
      const { container } = render(<PaperCard paper={emptyPaper} />);
      expect(
        container.querySelector('.paper-identifier--scholar'),
      ).toBeNull();
    });

    it('uses PMID for the Scholar query when DOI is missing but PMID is present', () => {
      const noDoiPaper: Paper = {
        ...NO_ABSTRACT_PAPER,
        doi: null,
        // PMID inherited from NO_ABSTRACT_PAPER (which is FULL_PAPER.copy)
      };
      const { container } = render(<PaperCard paper={noDoiPaper} />);
      const link = container.querySelector('.paper-identifier--scholar');
      expect(link).not.toBeNull();
      expect(link!.getAttribute('href')).toMatch(/q=PMID/);
    });
  });

    });
  });
});
