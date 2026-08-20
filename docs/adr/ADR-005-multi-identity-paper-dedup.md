# ADR-005: Multi-identity paper deduplication (PMID / DOI / title)

## Status

Accepted

## Context

The workspace's `add_paper` action needs to be idempotent: a
user who pastes `10.1007/978-3-031-64636-2_17` into the DOI
input, clicks "Add", and then pastes the same DOI a second time
should see **one** paper card, not two.

The backend (`app/domain/entities/research_session.py::ResearchSession.add_papers`)
correctly handles this with a three-tier identity function:
**PMID** is preferred, **DOI** is the fallback, and a
normalized **title** is the last resort. A paper is a duplicate
of another if any of these identity strings match.

The frontend's mirror of that logic — in
`frontend/src/state/workspaceStore.ts::addPapersToCurrent` —
originally only checked `PMID`. The bug the user hit:

1. Add DOI `10.1007/978-3-031-64636-2_17` once → workspace has
   the paper with `pmid: null` and `doi: "10.1007/..."`.
2. Add the same DOI again → the new paper also has `pmid: null`.
   `existingPmids` (an empty `Set` of strings) doesn't contain
   `null` and the dedup filter `if (existingPmids.has(p.pmid))`
   is a no-op. The paper is added a second time.
3. The user now sees two identical paper cards in the
   workspace.

The same bug bit anyone adding a paper by arXiv ID, conference
DOI, or any other identifier that didn't map to a PMID.

Compounding the bug: `AddPapersPanel.handleCommitResolved` calls
`addPapersToCurrent(response.papers)` where `response.papers` is
the **entire workspace** (the backend returns the full
`WorkspaceResponse` after every add). Even when the backend
correctly dedup'd, the frontend silently re-added the existing
paper because it received the whole workspace list as input
to its own (broken) dedup. Fixing the dedup is the right fix —
no need to also change the call site.

The fix in the backend was already correct. The frontend
needed a parallel fix.

## Decision

Frontend (`frontend/src/state/workspaceStore.ts`):

### 1. New helper functions

- `paperIdentity(paper)` — single canonical identity string,
  PMID > DOI > title (or `null` if no identity). Mirrors the
  backend's `_paper_identity`.
- `paperStrongIdentities(paper)` — list of strong identity
  signals (PMID and/or DOI) only. **Title is intentionally
  excluded** from this set because two genuinely different
  papers can share a title (multiple "Letter to the Editor"
  replies; a generic preprint title; a typo in one source's
  title would silently break dedup).

### 2. Two-tier dedup algorithm

```
existing_ids = ∅
for existing in workspace.papers:
    for id in paperStrongIdentities(existing):
        existing_ids.add(id)
    if primary := paperIdentity(existing):
        existing_ids.add(primary)   # only for primary

for new_paper in incoming_papers:
    strong = paperStrongIdentities(new_paper)
    primary = paperIdentity(new_paper)
    if not strong and not primary:
        keep()   # no identity at all — pass through

    if primary in existing_ids or primary in seen_in_batch:
        skip()   # canonical dedup
    if any(strong_id in existing_ids or seen_in_batch
           for strong_id in strong):
        skip()   # cross-identity dedup
    keep()
    seen_in_batch.add(primary)
    for id in strong: seen_in_batch.add(id)
```

Why this design:

- **Single canonical identity per paper** — when both papers
  have a primary identity (PMID or DOI), the comparison
  happens at the primary level. Paper A: PMID=12345, DOI=null.
  Paper B: PMID=12345, DOI=null. Both primary = `pmid:12345`.
  Match.
- **Cross-identity dedup via the strong set** — when one
  paper has both PMID and DOI and the other has only the same
  DOI, the single-canonical check misses the match (A's
  primary is `pmid:12345`, B's primary is `doi:10.1/x`). The
  strong-set check catches it: A's strong set includes
  `doi:10.1/x` and B's primary is `doi:10.1/x`.
- **Title is not a strong signal** — it's only the primary
  identity when no PMID/DOI is available. We do not check
  title against the strong set of other papers. This is the
  critical asymmetry: a paper with both a PMID and a generic
  title (e.g. "Letter to the Editor") won't accidentally dedup
  with another paper that has the same generic title but a
  different PMID.

The test contract is pinned by 5 new tests in
`frontend/src/state/workspaceStore.test.ts`:

- `dedupes by DOI when PMID is absent` (the user's
  reproduction)
- `dedupes by DOI even when PMID is also present and matches`
  (the cross-identity case)
- `does NOT dedup papers with the same title but different
  DOI` (the title-as-false-positive guard)
- `dedupes by normalized title only when no PMID and no DOI`
- `treats case-only title differences as duplicates`

## Consequences

**Positive**

- The user's reproduction (`10.1007/978-3-031-64636-2_17`
  added twice) now produces exactly one paper card. The new
  `dedupes by DOI when PMID is absent` test pins this.
- arXiv preprints, conference papers, and any other
  PMID-less source now dedup correctly.
- Title-only papers (resolvers that returned a stub record
  with just a title) still dedup against each other — useful
  for the rare case where a paper has no DOI and no PMID.
- The contract is mirrored across frontend and backend, so a
  refactor that changes one side without the other will fail
  tests on at least one side. The existing
  `TestResearchSession::test_add_papers_dedupes_by_doi` test
  on the backend pins the backend contract.

**Negative**

- The dedup logic in the store is now ~30 lines instead of
  ~10. We've added a long docstring explaining the algorithm
  and the title-asymmetry, which the tests document
  behaviorally.
- `seenInBatch.add(primary)` is O(1) but the strong-set
  intersection is O(N×M) where N is the batch size and M is
  the strong-set size. In practice the strong set is at most
  2 elements per paper and the batch is at most ~20 (the UI
  caps batch size), so the worst case is 40 comparisons per
  incoming paper — negligible.
- The two-tier logic is subtle. The "strong vs primary"
  distinction is not obvious to a reader; the test class
  `workspaceStore.dedup` documents it behaviorally.

## Alternatives considered

- **Server-side only** — drop the frontend dedup entirely,
  trust the backend. Rejected: the API response is the full
  workspace, not the diff. To get the diff we'd need a new
  endpoint (`POST /workspaces/{id}/papers/bulk` returning
  `{added: [...], removed: [...], workspace: ...}`). That's
  a bigger API change than the dedup fix. We keep the
  frontend dedup as a defensive measure.
- **Title as a strong signal** — include title in the strong
  set. We rejected this because of the false-positive risk:
  two papers with the same generic title ("Letter to the
  Editor", "Erratum:", "Reply to: ...") would silently dedup
  to one. The test `does NOT dedup papers with the same
  title but different DOI` documents this rejection.
- **Strip the frontend dedup and trust `Set<DOI>` only** —
  even simpler, but it breaks the title-only-stub case. We
  keep title as the primary identity when nothing else is
  available, accepting the false-positive risk for title-only
  papers as the lesser evil (the alternative — silent data
  loss — is worse).

## References

- `frontend/src/state/workspaceStore.ts` — the implementation
  and the long docstring.
- `app/domain/entities/research_session.py::_paper_identity` —
  the backend contract.
- `frontend/src/state/workspaceStore.test.ts` — 5 new tests
  in the `dedup` describe block.
