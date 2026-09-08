# ADR-021: Workspace corpus mutations are server-authoritative

## Status

Accepted — 2026-09-08

## Context

The user reported a corpus-resurrection bug on 2026-09-02:

> "Still, after generating report with 4 references, I still
> get ten in the executive report and 20 again when I come
> back to the workspace. Fix it!"

Symptom (reproducible end-to-end):
1. User starts at `INITIAL`, searches → `INTERMEDIATE` with 20 papers.
2. User removes 16 papers → UI shows 4 papers.
3. User clicks Generate Report → navigates to Report page →
   `FINAL` with a 20-paper executive report.
4. User clicks Back to Workspace → `INTERMEDIATE` shows 20
   papers again.

The expected behaviour: the corpus at the time of Generate is
authoritative. If the workspace contains 4 papers when Generate
is clicked, the executive report must be generated from those 4
papers; returning to the Workspace must show the same 4.

## Root cause

The Workspace page's ``handleRemovePaper``
(``frontend/src/pages/Workspace.tsx``) bound
``useWorkspaceStore.removePaper``, which was a **local-only**
Zustand action that filtered ``currentWorkspace.papers``
without ever calling ``DELETE
/workspaces/{id}/papers/{paper_id}``. The store mutation was
applied optimistically to the UI, but the **backend never
received the removal**.

Two paths then exposed the divergence:
1. **Report page mount** calls ``fetchWorkspace(id)`` →
   backend returns the original 20 papers → store is
   overwritten.
2. **Back to Workspace** → FSM transitions ``FINAL → INTERMEDIATE``,
   page mounts, ``fetchWorkspace`` again → store is overwritten
   again.

The bug was **purely frontend**. The backend repository,
orchestrator, ``ResearchSession.remove_paper``, and the
``/workspaces/{id}/papers/{paper_id}`` endpoint were all
correct. The frontend had a parallel corpus-mutation path that
diverged from the persisted workspace.

## Decision

**All workspace corpus mutations are server-authoritative.**
There is no longer any local-only path that can diverge from
the persisted workspace.

### What changed

1. **Removed** the local-only mutations from the Zustand
   store:
   - ``useWorkspaceStore.removePaper``
   - ``useWorkspaceStore.clearPapers``
   - ``useWorkspaceStore.addPapersToCurrent``

   These all mutated ``currentWorkspace.papers`` without an
   HTTP call. They are gone — the store is now a write-once
   mirror of the backend's canonical ``WorkspaceResponse``,
   updated exclusively via ``setCurrentWorkspace``.

2. **Added** server-authoritative mutations on the
   ``useWorkspace`` hook:
   - ``useWorkspace.removePaper(paperId)`` →
     ``DELETE /workspaces/{id}/papers/{paper_id}``, mirrors
     the canonical response via ``setCurrentWorkspace``.
   - ``useWorkspace.addPaper(paper)`` →
     ``POST /workspaces/{id}/papers``, mirrors the canonical
     response.

3. **Wired** ``Workspace.tsx::handleRemovePaper`` to call the
   hook's ``removePaperOnServer`` (renamed in the destructure
   to avoid clashing with the now-deleted store action).

4. **Disabled** the ``Clear All Papers`` UI handler that
   bound ``useWorkspaceStore.clearPapers``. There is no
   backend endpoint for clearing all papers. If the user
   wants a "Clear All Papers" affordance in the future, it
   must be added via a new backend endpoint and a matching
   server-authoritative hook action — not by re-introducing
   a local-only mutation.

5. **Deleted** the dead helpers that only existed to support
   the local-only mutations:
   - ``paperIdentity``
   - ``paperStrongIdentities``
   - ``nextAllowedActions``

   The three-tier dedup (PMID → DOI → title) that these
   helpers implemented on the frontend now lives exclusively
   on the backend (``ResearchSession._paper_identity``) and
   is already covered by the backend's existing test suite.

## Audit pattern

Every layer touched:

- **Frontend types** — ``WorkspaceStore`` interface removed
  ``addPapersToCurrent``, ``removePaper``, ``clearPapers``.
  Kept ``setSummary`` / ``setReportAvailable`` (cached-flag
  toggles that mirror fields already on the backend response
  and do NOT touch ``papers``).
- **Frontend store** — implementations removed.
- **Frontend hook** — ``useWorkspace.removePaper`` and
  ``useWorkspace.addPaper`` added, both calling
  ``api.removePaper`` / ``api.addPaper`` and mirroring via
  ``setCurrentWorkspace``.
- **Frontend Workspace page** — uses the hook, not the store.
- **Frontend tests** — mocks updated. The local-only store
  actions are gone from mocks. A new
  ``removePaperRegression.test.tsx`` file pins the contract.

## Consequences

Positive:

- **Single source of truth.** The persisted workspace's
  ``papers`` list is the authoritative corpus. The local
  Zustand store is always a mirror of it.
- **No more resurrection.** Removing a paper makes the
  ``DELETE`` call synchronously; the next
  ``fetchWorkspace`` returns the same corpus (the user's
  invariant: "INTERMEDIATE: [P1..P4], Generate, FINAL report:
  [P1..P4]").
- **No dangerous abstraction.** A future developer cannot
  accidentally call ``useWorkspaceStore.removePaper(id)`` and
  believe they have persisted a removal. The store no longer
  exposes any local-only corpus mutation.
- **Consistent error surface.** Backend rejections (404 paper
  not found, 409 illegal action) now propagate through the
  hook and surface in the hook's ``error`` field, which the
  Workspace page's toast handler reads. Pre-fix, the local
  filter silently swallowed errors.

Trade-offs:

- **Slower UI.** No optimistic update for removals — the
  user sees a brief loading state while the ``DELETE`` is in
  flight. The user explicitly asked for this: "I would
  rather have a slightly slower but correct UI than an
  instant UI that lies about the persisted state."
- **No "Clear All Papers".** The button was already hidden
  in the UI but the local-only action stayed behind as a
  footgun. Now both the UI and the action are gone. A
  future "Clear All Papers" feature would require a new
  backend endpoint.

## Out of scope

The user explicitly said not to touch:

- **Citation mapping** — ADR-019's subset invariant is
  correct and orthogonal to this fix. The corpus invariant
  is upstream of the citation invariant; fixing the corpus
  doesn't change which citations are valid.
- **Bibliography mapping** — ADR-020's "every workspace
  paper appears in the bibliography" invariant is also
  orthogonal. With the corpus now correctly persisting,
  the bibliography will continue to be the right size.
- **Report mapper** — no changes. The mapper reads
  ``session.papers`` at generate time, which is now the
  persisted corpus.

## Alternatives

- **Optimistic update + rollback.** Filter the local store
  first, fire the ``DELETE``, roll back on failure. Adds
  complexity for no user-visible benefit (the round-trip is
  already sub-200ms on localhost) and reintroduces a
  parallel-corpus surface that needs careful reconciliation.
  Rejected.
- **Reactive subscription** (e.g. WebSocket from backend
  pushing "papers removed" events). Out of scope for this
  bug; would require a substantial backend-side change.
  Rejected.
- **In-place mutation of the store via the hook** (i.e. the
  hook filters ``currentWorkspace.papers`` instead of calling
  ``setCurrentWorkspace``). This avoids the round-trip's
  loading state, but re-introduces a divergence: if the
  backend's canonical state differs (e.g. a concurrent
  request changed the corpus), the store lies. Rejected.

## Rollback

Reverting requires:

1. Restore ``addPapersToCurrent``, ``removePaper``,
   ``clearPapers`` to the store interface and implementation.
2. Restore the helpers (``paperIdentity``,
   ``paperStrongIdentities``, ``nextAllowedActions``).
3. Re-wire ``Workspace.tsx::handleRemovePaper`` to call
   ``useWorkspaceStore.removePaper`` instead of
   ``useWorkspace.removePaper``.
4. Delete the regression test file
   ``removePaperRegression.test.tsx``.

The behaviour reverts to the pre-fix state: removals are
optimistic UI mutations that disappear on the next
``fetchWorkspace``.

## Notes

This commit is frontend-only. The backend was already
correct; it was never told about the removals because the
frontend was hiding them. Once the frontend routes through
the hook, the existing backend ``DELETE`` endpoint and the
existing ``ResearchSession.remove_paper`` validation
(``_paper_identity`` dedup, FSM-aware ``allowed_actions``)
take over.
