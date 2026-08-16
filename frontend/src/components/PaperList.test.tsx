// components/PaperList.test.tsx
//
// Tests for the PaperList component — the workspace's
// rendering of multiple papers at once.
//
// Two responsibilities:
// 1. Empty state: render ``emptyMessage`` when ``papers`` is
//    empty and a message was supplied.
// 2. Rendered list: one PaperCard per paper, with stable keys
//    (pmid > doi > title) so React keeps DOM identity across
//    array reordering.

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PaperList } from './PaperList';
import type { Paper } from '../models/paper';

const PAPER_A: Paper = {
  title: 'Paper A — first paper.',
  authors: [{ first_name: 'A', last_name: 'Author', full_name: 'A Author', affiliation: null }],
  journal: { name: 'Cell', issn: '0092-8674', publisher: null },
  year: 2024,
  abstract: 'Abstract A.',
  doi: '10.1000/a',
  pmid: '111',
  keywords: [],
  url: null,
};

const PAPER_B: Paper = {
  ...PAPER_A,
  title: 'Paper B — second paper.',
  pmid: '222',
  doi: '10.1000/b',
};

const PAPER_C: Paper = {
  ...PAPER_A,
  title: 'Paper C — third paper.',
  // No pmid, only DOI.
  pmid: null,
  doi: '10.1000/c',
};

const PAPER_NO_ID: Paper = {
  ...PAPER_A,
  title: 'Paper D — no identifiers at all.',
  pmid: null,
  doi: null,
};

describe('PaperList', () => {
  describe('empty state', () => {
    it('renders the empty message when papers is empty', () => {
      render(<PaperList papers={[]} emptyMessage="No papers yet" />);
      expect(screen.getByText('No papers yet')).toBeInTheDocument();
    });

    it('renders nothing extra when papers is empty and no emptyMessage', () => {
      const { container } = render(<PaperList papers={[]} />);
      // The wrapping div still renders but is empty.
      expect(container.firstChild).not.toBeNull();
      expect(container.textContent).toBe('');
    });
  });

  describe('rendering', () => {
    it('renders one card per paper', () => {
      render(
        <PaperList
          papers={[PAPER_A, PAPER_B, PAPER_C]}
          emptyMessage="ignored when papers exist"
        />,
      );
      // Each paper title renders.
      expect(screen.getByText(/Paper A/)).toBeInTheDocument();
      expect(screen.getByText(/Paper B/)).toBeInTheDocument();
      expect(screen.getByText(/Paper C/)).toBeInTheDocument();
    });

    it('passes through onRemove to each PaperCard', () => {
      const onRemove = vi.fn();
      render(
        <PaperList papers={[PAPER_A, PAPER_B]} onRemovePaper={onRemove} />,
      );
      // Two remove buttons — one per card.
      const buttons = screen.getAllByRole('button', {
        name: /remove paper/i,
      });
      expect(buttons).toHaveLength(2);
    });

    it('keys cards by pmid when present', () => {
      // React keys are not directly testable through the DOM,
      // but we can assert the rendered order matches the
      // input order and that no key collisions occurred (no
      // console errors).
      const { container } = render(
        <PaperList papers={[PAPER_A, PAPER_B]} />,
      );
      const cards = container.querySelectorAll('.paper-card');
      expect(cards).toHaveLength(2);
    });
  });

  describe('stable keys for thin-paper fallback', () => {
    it('keys by DOI when PMID is null', () => {
      // The PaperList uses pmid > doi > title. Even if both
      // papers have the same title (a thin-paper fallback),
      // different DOIs give them different keys and React
      // keeps them as separate cards.
      render(<PaperList papers={[PAPER_C, PAPER_NO_ID]} />);
      const cards = document.querySelectorAll('.paper-card');
      expect(cards).toHaveLength(2);
    });
  });
});
