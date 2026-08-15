// PaperUpload.tsx
/**
 * PaperUpload.tsx
 * ----------------
 * Form for adding a paper to a workspace manually — without
 * going through PubMed. Useful when the user already knows the
 * paper they want to study, or when the paper isn't indexed in
 * PubMed at all.
 *
 * The form is intentionally minimal: title is required,
 * everything else is optional. The user can flesh out authors,
 * abstract, DOI, etc. over time.
 *
 * The component is rendered on the Workspace page when the FSM
 * allows the ``add_paper`` action — that is, in CREATED,
 * PAPERS_RETRIEVED, SUMMARIZED, COMPARED, REPORTED, and
 * COMPLETED states.
 *
 * @module components/PaperUpload
 */

import React, { useState } from 'react';
import type { PaperRequest } from '../models/paper';
import { useWorkspaceStore } from '../state/workspaceStore';

interface PaperUploadProps {
  /** ID of the workspace to add the paper to. */
  workspaceId: string;
  /** Whether the FSM allows ``add_paper`` in the current state. */
  enabled: boolean;
}

interface FormState {
  title: string;
  author_name: string;
  journal_name: string;
  year: string;
  abstract: string;
  doi: string;
  pmid: string;
  keywords: string;
  url: string;
}

const EMPTY_FORM: FormState = {
  title: '',
  author_name: '',
  journal_name: '',
  year: '',
  abstract: '',
  doi: '',
  pmid: '',
  keywords: '',
  url: '',
};

export const PaperUpload: React.FC<PaperUploadProps> = ({
  workspaceId,
  enabled,
}) => {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const addPapersToCurrent = useWorkspaceStore((s) => s.addPapersToCurrent);

  const reset = () => {
    setForm(EMPTY_FORM);
    setError(null);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.title.trim()) {
      setError('Title is required.');
      return;
    }
    setSubmitting(true);
    setError(null);

    // Build the PaperRequest payload. Empty optional fields
    // collapse to ``null`` so the backend sees a clean payload.
    const payload: PaperRequest = {
      title: form.title.trim(),
      authors: form.author_name.trim()
        ? [
            {
              full_name: form.author_name.trim(),
            },
          ]
        : [],
      journal: form.journal_name.trim()
        ? { name: form.journal_name.trim() }
        : null,
      year: form.year.trim() ? Number(form.year) : null,
      abstract: form.abstract.trim(),
      doi: form.doi.trim() || null,
      pmid: form.pmid.trim() || null,
      keywords: form.keywords
        .split(',')
        .map((k) => k.trim())
        .filter(Boolean),
      url: form.url.trim() || null,
    };

    try {
      // Dynamic import so the bundle only includes the API client
      // code when the user actually opens the form.
      const { api } = await import('../api/client');
      const response = await api.addPaper(workspaceId, payload);
      // Sync the local store with the updated workspace.
      addPapersToCurrent(response.papers);
      reset();
      setOpen(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to upload paper.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (!enabled) {
    return (
      <div className="paper-upload paper-upload--disabled" aria-disabled="true">
        <p>
          Manual paper upload is not available in the current state.
          Run a SEARCH first or finish the current step.
        </p>
      </div>
    );
  }

  if (!open) {
    return (
      <div className="paper-upload">
        <button
          type="button"
          className="paper-upload-toggle"
          onClick={() => setOpen(true)}
        >
          + Upload paper manually
        </button>
      </div>
    );
  }

  return (
    <form className="paper-upload paper-upload--open" onSubmit={handleSubmit}>
      <header className="paper-upload-header">
        <h4>Add a paper</h4>
        <button
          type="button"
          className="paper-upload-close"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          aria-label="Close upload form"
        >
          ×
        </button>
      </header>

      <label>
        Title *
        <input
          type="text"
          required
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="The Amyloid-β Pathway in Alzheimer's Disease"
        />
      </label>

      <div className="paper-upload-row">
        <label>
          First author
          <input
            type="text"
            value={form.author_name}
            onChange={(e) => setForm({ ...form, author_name: e.target.value })}
            placeholder="Maria Garcia"
          />
        </label>
        <label>
          Year
          <input
            type="number"
            min="1500"
            max="2200"
            value={form.year}
            onChange={(e) => setForm({ ...form, year: e.target.value })}
            placeholder="2025"
          />
        </label>
      </div>

      <label>
        Journal
        <input
          type="text"
          value={form.journal_name}
          onChange={(e) => setForm({ ...form, journal_name: e.target.value })}
          placeholder="Nature Neuroscience"
        />
      </label>

      <label>
        Abstract
        <textarea
          rows={3}
          value={form.abstract}
          onChange={(e) => setForm({ ...form, abstract: e.target.value })}
          placeholder="We review the major pathways…"
        />
      </label>

      <div className="paper-upload-row">
        <label>
          DOI
          <input
            type="text"
            value={form.doi}
            onChange={(e) => setForm({ ...form, doi: e.target.value })}
            placeholder="10.1038/s41593-025-00001-1"
          />
        </label>
        <label>
          PMID
          <input
            type="text"
            value={form.pmid}
            onChange={(e) => setForm({ ...form, pmid: e.target.value })}
            placeholder="40000001"
          />
        </label>
      </div>

      <label>
        Keywords (comma-separated)
        <input
          type="text"
          value={form.keywords}
          onChange={(e) => setForm({ ...form, keywords: e.target.value })}
          placeholder="Alzheimer, amyloid, clearance"
        />
      </label>

      <label>
        URL
        <input
          type="url"
          value={form.url}
          onChange={(e) => setForm({ ...form, url: e.target.value })}
          placeholder="https://example.org/papers/123"
        />
      </label>

      {error && <p className="paper-upload-error">{error}</p>}

      <footer className="paper-upload-footer">
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          disabled={submitting}
        >
          Cancel
        </button>
        <button type="submit" disabled={submitting}>
          {submitting ? 'Uploading…' : 'Add paper'}
        </button>
      </footer>
    </form>
  );
};

export default PaperUpload;