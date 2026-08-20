/**
 * Component tests for WorkspaceActionBar.
 *
 * The bar is intentionally minimal — two buttons:
 *
 *   1. **Generate Report**: a prominent primary CTA, disabled
 *      when ``canReport`` is false. Calls ``onGenerateReport``
 *      on click. Title attribute changes based on disabled
 *      state so the user gets a hint about why it's
 *      disabled.
 *
 *   2. **Advanced Search Options**: a standard blue button
 *      with a constant label (no toggle verb). Clicking it
 *      fires ``onOpenAdvancedSearch``; the modal itself is
 *      rendered separately by the parent. The button does
 *      NOT mirror the modal's open/close state — there's no
 *      "Show / Hide" verb and no chevron rotation.
 *
 * Why the component is tested in isolation (not as part of
 * the Workspace tree):
 *
 *   - The full Workspace page pulls in every route, the
 *     router, the toast store, and the multi-source
 *     literature search. A unit test on the tree would
 *     re-test the same boilerplate over and over.
 *
 *   - The action bar is the user-visible surface for the
 *     most important user action ("Generate Report"). A
 *     focused test catches regressions in the button label,
 *     disabled state, and aria attributes — which are the
 *     bits the user actually sees.
 *
 *   - The bar is the right granularity for a "does the
 *     button exist and is it enabled" test. Anything more
 *     (network, navigation) belongs in the full-page test.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorkspaceActionBar } from './WorkspaceActionBar';

describe('WorkspaceActionBar', () => {
  it('renders the Generate Report button as a primary CTA', () => {
    render(
      <WorkspaceActionBar
        canReport={true}
        onGenerateReport={() => {}}
        onOpenAdvancedSearch={() => {}}
      />
    );
    const reportButton = screen.getByRole('button', {
      name: /generate report/i,
    });
    expect(reportButton).toBeInTheDocument();
    // The Generate Report button should be the prominent
    // primary CTA — verify the modifier class is present.
    expect(reportButton).toHaveClass('btn-action-primary');
    expect(reportButton).not.toBeDisabled();
  });

  it('disables the Generate Report button when canReport is false', () => {
    render(
      <WorkspaceActionBar
        canReport={false}
        onGenerateReport={() => {}}
        onOpenAdvancedSearch={() => {}}
      />
    );
    const reportButton = screen.getByRole('button', {
      name: /generate report/i,
    });
    expect(reportButton).toBeDisabled();
    // Title attribute should hint at why it's disabled.
    expect(reportButton.title).toMatch(/not allowed/i);
  });

  it('calls onGenerateReport when the Generate Report button is clicked', async () => {
    const user = userEvent.setup();
    const onGenerateReport = vi.fn();
    render(
      <WorkspaceActionBar
        canReport={true}
        onGenerateReport={onGenerateReport}
        onOpenAdvancedSearch={() => {}}
      />
    );
    const reportButton = screen.getByRole('button', {
      name: /generate report/i,
    });
    await user.click(reportButton);
    expect(onGenerateReport).toHaveBeenCalledTimes(1);
  });

  it('renders the Advanced Search Options button with a constant label', () => {
    render(
      <WorkspaceActionBar
        canReport={false}
        onGenerateReport={() => {}}
        onOpenAdvancedSearch={() => {}}
      />
    );
    // The button label is constant — no "Show" or "Hide"
    // verb. The user expects a standard button that always
    // reads the same thing.
    const button = screen.getByRole('button', {
      name: /advanced search options/i,
    });
    expect(button).toBeInTheDocument();
    expect(button).toHaveTextContent('Advanced Search Options');
    // The button is NOT a toggle: it has no aria-expanded
    // attribute (the modal manages its own open state).
    expect(button).not.toHaveAttribute('aria-expanded');
  });

  it('renders the Advanced Search Options button as a standard blue primary button', () => {
    render(
      <WorkspaceActionBar
        canReport={true}
        onGenerateReport={() => {}}
        onOpenAdvancedSearch={() => {}}
      />
    );
    const button = screen.getByRole('button', {
      name: /advanced search options/i,
    });
    // ``btn-primary`` is the standard blue button styling.
    // It does NOT carry ``btn-action-primary`` (that's the
    // modifier reserved for the prominent Generate Report
    // CTA) and it does NOT carry ``btn-secondary`` (which
    // was used by the older "show / hide toggle" shape).
    expect(button).toHaveClass('btn-primary');
    expect(button).not.toHaveClass('btn-action-primary');
    expect(button).not.toHaveClass('btn-secondary');
  });

  it('does NOT include a chevron icon in the Advanced Search Options button', () => {
    // The user explicitly asked for a "standard blue
    // button like the others". The earlier toggle had a
    // ``<ChevronDown />`` icon that rotated 180deg on open.
    // We verify the new button has no SVG icon at all so
    // the toggle shape can never reappear by accident.
    render(
      <WorkspaceActionBar
        canReport={true}
        onGenerateReport={() => {}}
        onOpenAdvancedSearch={() => {}}
      />
    );
    const button = screen.getByRole('button', {
      name: /advanced search options/i,
    });
    expect(button.querySelector('svg')).toBeNull();
  });

  it('calls onOpenAdvancedSearch when the Advanced Search Options button is clicked', async () => {
    const user = userEvent.setup();
    const onOpenAdvancedSearch = vi.fn();
    render(
      <WorkspaceActionBar
        canReport={true}
        onGenerateReport={() => {}}
        onOpenAdvancedSearch={onOpenAdvancedSearch}
      />
    );
    const button = screen.getByRole('button', {
      name: /advanced search options/i,
    });
    await user.click(button);
    expect(onOpenAdvancedSearch).toHaveBeenCalledTimes(1);
  });

  it('uses data-action="advanced-search-open" so end-to-end tests can target it', () => {
    // The frontend E2E test suite (and any future Playwright
    // test) targets the button by ``data-action``. Pin the
    // attribute so a rename in this file propagates to
    // every test consumer.
    render(
      <WorkspaceActionBar
        canReport={true}
        onGenerateReport={() => {}}
        onOpenAdvancedSearch={() => {}}
      />
    );
    const button = screen.getByRole('button', {
      name: /advanced search options/i,
    });
    expect(button).toHaveAttribute('data-action', 'advanced-search-open');
  });
});
