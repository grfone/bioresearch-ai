// WorkspaceEmptyState.tsx
/**
 * WorkspaceEmptyState.tsx
 * -----------------------
 * Three-zone empty state shown when a workspace has zero papers.
 *
 * Replaces the bare "No papers yet" message that the previous
 * paper list rendered. Each zone names a workflow the user
 * actually does — not an absence — and opens the matching entry
 * mode pre-focused. Cards are clickable.
 *
 * The three zones (matching the consultant's recommendation):
 *
 *   1. "I have specific papers"  → AddPapersPanel in PMID/DOI tab
 *   2. "I want to discover papers" → existing PubMed search input
 *   3. "I have PDFs on my machine" → AddPapersPanel in PDF tab (stub)
 *
 * The component is purely visual — it doesn't open the panels
 * itself. The parent (Workspace.tsx) wires the click handlers
 * so the empty state stays a dumb display.
 */

import React from 'react';
import { FileUp, Hash, Search } from 'lucide-react';

interface WorkspaceEmptyStateProps {
  onChooseIdentifier: () => void;
  onChooseSearch: () => void;
  onChoosePdf: () => void;
  /** Keyboard shortcut hint surfaced on the primary card. PC
   *  default is ``Ctrl+K``; Mac users see ``⌘K``. */
  shortcutHint?: string;
}

interface ChoiceCardProps {
  icon: React.ReactNode;
  title: string;
  body: string;
  hint: React.ReactNode;
  onClick: () => void;
  accent?: 'primary' | 'secondary';
}

const ChoiceCard: React.FC<ChoiceCardProps> = ({
  icon,
  title,
  body,
  hint,
  onClick,
  accent = 'secondary',
}) => (
  <button
    type="button"
    className={`workspace-empty-card workspace-empty-card--${accent}`}
    onClick={onClick}
    aria-label={title}
  >
    <span className="workspace-empty-card-icon" aria-hidden="true">
      {icon}
    </span>
    <span className="workspace-empty-card-title">{title}</span>
    <span className="workspace-empty-card-body">{body}</span>
    <span className="workspace-empty-card-hint">{hint}</span>
  </button>
);

export const WorkspaceEmptyState: React.FC<WorkspaceEmptyStateProps> = ({
  onChooseIdentifier,
  onChooseSearch,
  onChoosePdf,
  shortcutHint = 'Ctrl+K',
}) => (
  <section className="workspace-empty" aria-label="Get started">
    <header className="workspace-empty-header">
      <h3 className="workspace-empty-title">Start your workspace</h3>
      <p className="workspace-empty-subtitle">
        Pick the workflow that matches what you have in front of you
        right now. You can mix and match — for example, paste a few
        PMIDs and then run a search to fill in the gaps.
      </p>
    </header>
    <div className="workspace-empty-grid">
      <ChoiceCard
        icon={<Hash size={20} />}
        title="I have specific papers"
        body="Paste PMIDs or DOIs from a colleague's email, grant
              reference list, or your Zotero library. Bulk paste works
              — one per line, mixed formats OK."
        hint={
          <>
            Auto-fetches full metadata from PubMed or CrossRef. Press{' '}
            <kbd>{shortcutHint}</kbd> from anywhere to focus this input.
          </>
        }
        onClick={onChooseIdentifier}
        accent="primary"
      />
      <ChoiceCard
        icon={<Search size={20} />}
        title="I want to discover papers"
        body="Search PubMed for this research question. The search
              input is already prefilled with the question that
              created this workspace."
        hint="Returns up to 20 candidates ranked by relevance."
        onClick={onChooseSearch}
      />
      <ChoiceCard
        icon={<FileUp size={20} />}
        title="I have PDFs on my machine"
        body="Drop one or more PDFs and we'll extract the DOI from
              the first page, fetch the rest of the metadata, and
              let you fix the gaps inline."
        hint="Coming soon — for now, paste a DOI instead."
        onClick={onChoosePdf}
      />
    </div>
  </section>
);

export default WorkspaceEmptyState;