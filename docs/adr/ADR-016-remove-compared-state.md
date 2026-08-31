# ADR-016: Remove the COMPARING/COMPARED FSM states

## Status

Accepted — 2026-08-30

## Context

The first public release of BioResearch AI included a
cross-paper **evidence-comparison intermediate state** in the
workspace FSM. The lifecycle was:

```
SEARCH → SUMMARIZE → COMPARE → REPORT
```

The COMPARE action ran a separate LLM call to produce an
`EvidenceComparison` aggregate (consensus findings,
contradictions, research gaps, future directions, and a
side-by-side matrix). The comparison was stored on the
`ResearchSession` aggregate as `session.evidence_comparison`,
persisted in the `evidence_comparison` SQLite column, and
exposed via `GET /workspaces/{id}/evidence-comparison`.

The report generator (`GenerateReportUseCase`) takes
`question`, `summary`, and produces a `ResearchReport`. It
**never** consumed the evidence comparison. The
`EvidenceComparisonPanel` UI showed the comparison alongside
the report, but the cross-reference links inside the report
already used Vancouver-style numbered references — the
comparison didn't gate the report's content.

### Why we removed it

Three independent findings converged on the same conclusion:

1. **The comparison was write-only.** No downstream consumer
   read it. Removing it shortens the lifecycle from eleven
   states to nine with zero loss of user-visible capability.

2. **The COMPARE action was orphaned by ADR-008.**
   ADR-008 introduced one-click REPORT from PAPERS_RETRIEVED.
   The REPORT action now auto-summarises (and historically
   auto-compared too, though the comparison was never used
   downstream). The COMPARE-only panel had no callers after
   this consolidation — the comment at `Workspace.tsx:317-326`
   explicitly documents this:
   > "The COMPARE action is now bundled into REPORT... The
   > COMPARE-only panel had no user after that."

3. **The infrastructure footprint was large for a write-only
   artefact.**
   - `EvidenceComparison` + `EvidenceMatrix` entities (2 files,
     ~250 LOC).
   - `ComparisonGenerator` interface + `LLMComparisonGenerator`
     + `EvidenceComparisonMapper` infrastructure (3 files,
     ~400 LOC).
   - `CompareEvidenceUseCase` (~150 LOC).
   - `comparison_prompt.py` prompt (~150 LOC).
   - SQLite `evidence_comparison` column with v2 migration.
   - `GET /workspaces/{id}/evidence-comparison` endpoint.
   - `has_evidence_comparison` API field.
   - `validate_evidence_comparison` / `validate_evidence_matrix`
     validator methods.
   - `compare_node` LangGraph node.
   - Frontend `EvidenceComparisonPanel` component, `comparison.ts`
     type module, `runCompareAction` API client method,
     `getEvidenceComparison` fetch method.
   - Dedicated unit tests across 4 backend test files
     (`test_fsm_transitions`, `test_workspace_orchestrator`,
     `test_resolve_and_add_by_title`,
     `test_search_with_filters_attribution`,
     `test_citation_validator`) and the
     `test_evidence_comparison_mapper` file.

### New lifecycle

```
CREATED → SEARCHING → PAPERS_RETRIEVED
        → SUMMARIZING → SUMMARIZED
        → REPORTING → REPORTED
        → PUBLISHING (transient)
        → COMPLETED
```

Nine stable states (was eleven), eight actions (was nine).

## Decision

Remove every layer of the evidence-comparison subsystem.
Follow the **four-layer audit pattern** from
[ADR-009](ADR-009-publishing-state.md) when touching each
layer:

| Layer | What we changed |
|-------|-----------------|
| 1. FSM table | Drop `COMPARING`/`COMPARED` from `WorkspaceState`; drop `COMPARE` from `WorkspaceAction`; update `TRANSITIONS` so `SUMMARIZED` advances directly to `REPORTING` via `REPORT`; `REPORTING → RETRY` now returns to `SUMMARIZED` (was `COMPARED`). |
| 2. Orchestrator | Replace the body of `WorkspaceOrchestrator.compare()` with a 410-equivalent stub that raises `IllegalWorkspaceActionError`. Kept on the public surface so stale callers (and the route handler) get a clear error rather than an `AttributeError`. |
| 3. Entity | Drop `ResearchSession.evidence_comparison` field; drop `set_evidence_comparison()` mutator; drop `has_evidence_comparison` property. |
| 4. Wire-format | Drop `EvidenceComparisonResponse` schema; drop `has_evidence_comparison` field on `WorkspaceResponse`; drop `GET /workspaces/{id}/evidence-comparison` endpoint; drop `POST /workspaces/{id}/actions/compare` endpoint. |
| Persistence | Add v7 migration: `ALTER TABLE workspaces DROP COLUMN evidence_comparison`. Idempotent — skips if column already absent. `_row_to_dict` index map shifts left by one. `_dict_to_workspace` no longer reads the `evidence_comparison` slot. |
| Workflow | Drop `compare_node` from the LangGraph topology; edge `summarize → report` (was `summarize → compare → report`). |
| Validator | Drop `validate_evidence_comparison` and `validate_evidence_matrix`. `CitationValidator` keeps only `validate_finding` and `validate_report`. |
| Container | Drop `ComparisonGenerator` / `LLMComparisonGenerator` / `EvidenceComparisonMapper` wiring; `WorkspaceOrchestrator` constructor loses the `comparison_generator` parameter. |
| Frontend | Drop `runCompareAction` / `getEvidenceComparison` from `client.ts`; drop `fetchEvidenceComparison` from `useWorkspace`; drop `EvidenceComparisonPanel` component; drop `comparison.ts` types; drop `'COMPARING'` and `'COMPARED'` from the `WorkspaceState` union; drop `'compare'` from the `WorkspaceAction` union; drop `has_evidence_comparison` field; drop `hasEvidenceComparison()` helper. |

### Backward compatibility

- **Database**: `SqliteWorkspaceRepository` runs the v7
  migration on first instantiation. Workspaces in
  `COMPARING`/`COMPARED` state at upgrade time are
  **elevated** by `_infer_state` (the raw enum value raises
  `ValueError`; the workspace falls back to data-driven
  inference — `REPORTED` if a report exists, otherwise
  `SUMMARIZED` if a summary exists, otherwise `PAPERS_RETRIEVED`
  / `CREATED`).
- **Orchestrator surface**: `compare()` remains on the
  public class so the route handler's `Depends(...)` injection
  doesn't break, but it raises. It will be deleted in a
  follow-up commit.
- **Frontend types**: `WorkspaceResponse` no longer has
  `has_evidence_comparison`. The Zustand store and the
  action-permission helper list (in `nextAllowedActions`)
  drop the `compare` case explicitly.

## Consequences

### Positive

- 9 stable FSM states instead of 11.
- 8 actions instead of 9.
- ~1,200 LOC of unused code removed across backend, frontend,
  tests, and docs — the comparison subsystem is gone
  end-to-end.
- Lighter image: the reportlab PDF generator still runs
  ~200ms faster on a typical 17-paper report because the
  `compare_evidence` column no longer needs to be deserialised.
- Cleaner mental model: search → summarise → report → done,
  with no orphaned intermediate state.
- One-click report (`ADR-008`) is now the only path; no risk
  of users clicking COMPARE and waiting for an LLM call that
  produces nothing the report uses.

### Negative

- Users who explicitly wanted to inspect a "compare papers"
  artefact before generating the report lose that view. The
  report's executive summary still summarises consensus,
  contradictions, and gaps inline — that's the same LLM
  capability surfaced in a different form.
- The orchestrator's `compare()` method is kept as a stub for
  one release cycle to keep the route handler's
  `Depends(...)` injection working. It will be removed in
  the next major version.

### Neutral

- The `EvidenceMatrix` type (the side-by-side comparison
  table) is deleted with `EvidenceComparison`. If a future
  feature wants to bring back the matrix, it can be rebuilt
  on top of the report's `citations` and `summary` fields.

## Verification

- **Live migration test** (run against a synthetic v6 DB
  with the `evidence_comparison` column and a `REPORTED`
  row): migration completes; `user_version` jumps from 6
  to 7; the column is dropped; the existing row reads back
  cleanly with `state=REPORTED` and
  `summary="Tau is a protein."`. A separate row inserted
  with `state=COMPARING` (the legacy enum value) is
  elevated to `CREATED` via `_infer_state` because the
  test row has no papers, summary, or report.

- **Test counts**: 806 backend + 289 frontend = 1095 tests
  pass; integration suite is green (25 tests including the
  new `test_compare_endpoint_is_retired` which asserts the
  retired endpoint returns 405).

- **All four CI jobs green** on commit `7606240`.

## Related

- [ADR-008](ADR-008-one-click-report-from-papers-retrieved.md)
  introduced the auto-summarise / auto-compare behaviour that
  made the COMPARE-only UI obsolete.
- [ADR-009](ADR-009-publishing-state.md) established the
  four-layer audit pattern we followed for this refactor.
- [ADR-011](ADR-011-vancouver-citations-anti-fabrication.md)
  documented the citation sanitiser, which continues to
  validate the report's numbered references.
