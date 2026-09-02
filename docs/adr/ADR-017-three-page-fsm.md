# ADR-017: Collapse the FSM to four states mapped 1:1 to the three pages

## Status

Accepted — 2026-08-31

## Context

After [ADR-016](ADR-016-remove-compared-state.md) removed the
`COMPARING` / `COMPARED` cross-paper evidence-comparison
intermediate, the FSM was linear but still wide:

```
CREATED ─search─▶ SEARCHING ─▶ PAPERS_RETRIEVED
                                    │
                                    ├─summarize─▶ SUMMARIZING ─▶ SUMMARIZED
                                    │
                                    └─report (one-click, auto-summarises)
                                                │
                                                ▼
                                            REPORTING ─▶ REPORTED ─publish─▶ PUBLISHING ─▶ COMPLETED
```

Nine stable / transient states. The frontend only has **three
pages** (Home, Workspace, Report) and the user's flow is:

1. Land on Home, type a question.
2. Click Search → arrive on Workspace, curate the corpus.
3. Click "Generate Report" → arrive on Report, read / download.

The user asked (2026-08-31) for a FSM that maps 1:1 to the three
pages, with three named actions: `search` (Home → Workspace),
`generate` (Workspace → Report), and `regress` (Report → Workspace,
Workspace → Home).

## Decision

Collapse the FSM to **four states**: `INITIAL`, `INTERMEDIATE`,
`FINAL`, `ERROR`. The three stable states map 1:1 to the three
pages; `ERROR` is the recoverable failure page.

Drop the four transient states (`SEARCHING`, `SUMMARIZING`,
`REPORTING`, `PUBLISHING`). The UI's spinner is the source of
truth for "an operation is in flight" — there's no need to model
that in the backend FSM.

Collapse `SUMMARIZE`, `REPORT`, `PUBLISH`, `COMPLETE` into a single
`generate` action that runs the full pipeline in one HTTP call:

```
INITIAL ──search──▶ INTERMEDIATE ──generate──▶ FINAL
                       │                            │
                       ├─back_to_home──▶ INITIAL    └─back_to_workspace──▶ INTERMEDIATE
                       └─ERROR (recoverable: retry, add_paper, remove_paper)
```

The state name `INITIAL` corresponds to page `home`;
`INTERMEDIATE` to `workspace`; `FINAL` to `report`; `ERROR` to
`error`. The mapping is exposed on the wire via a new
`page: str` field on `WorkspaceResponse` so the SPA can route
without parsing the FSM state.

The `generate` action is legal only from `INTERMEDIATE`; it runs
the full pipeline server-side (summarise → report → PDF → LaTeX)
and returns a `ReportResponse` with the rendered PDF / TeX bytes
already on the session. There is no separate PUBLISH action any
more.

`add_paper` and `remove_paper` are legal from any state (including
`ERROR`) — they don't drive the FSM, they just modify the corpus
in place. `retry` is legal only from `ERROR` and restores the
previous state via `session.last_known_state` (a new v8-migrated
column).

`back_to_workspace` (`FINAL → INTERMEDIATE`) and `back_to_home`
(`INTERMEDIATE → INITIAL`) let the user navigate the FSM in
reverse when they want to refine the corpus or change the
question. The `remove_paper` regression that drops the last paper
(`INTERMEDIATE → INITIAL`) is the legacy path that handles the
same scenario organically.

**Client-side expectation for `back_to_workspace`.** The
"Back to Workspace" button on the Report page (`src/pages/Report.tsx`)
MUST call `runAction('back_to_workspace')` *before* navigating
to `/workspace/{id}`. A pure client-side `navigate('/workspace/...')`
would leave the workspace in `FINAL`, and the Workspace page's
``can('generate')`` check (which reads ``allowed_actions`` from
the FSM table) would return `false`, greying out the Generate
Report button. The user would land on the Workspace page
unable to do anything useful. This was a real bug introduced
when the FSM was collapsed (commit `5310661` made the bug
possible but not visible; the subsequent `4970bdf` + the
generate action made it observable by the user). The fix
lives at the SPA layer — the orchestrator and FSM are
correct — and the regression is pinned by three tests in
`src/pages/Report.test.tsx > Report > back-to-workspace
navigation (FSM regressive action)`.

## Audit pattern

This refactor touches every architectural layer (the audit
pattern from [ADR-009](ADR-009-publishing-state.md)):

- **FSM** — re-enumerated `WorkspaceState` to four values; dropped
  `WorkspaceAction` members `SUMMARIZE`, `REPORT`, `COMPLETE`,
  `PUBLISH`; added `GENERATE`, `BACK_TO_WORKSPACE`, `BACK_TO_HOME`.
  Added `page: str` to `WorkspaceState` for the wire-format page
  token.
- **Orchestrator** — `compare()` already a stub from ADR-016;
  `summarize()`, `publish()`, `complete()`, `summarize_with_state_history()`
  now raise `IllegalWorkspaceActionError`. Added a single
  `generate(workspace_id)` that runs summarise + report + PDF in
  one shot. Added `back_to_workspace()` and `back_to_home()`.
- **Entity** — `ResearchSession` no longer has `summary`-first
  vs `report`-first branching. New `last_known_state` column
  (v8 migration) lets `retry` restore the pre-`ERROR` state.
  `force_state` simplified (no transient-state special case).
- **Wire format** — `WorkspaceResponse` gained `page: str`. The
  `/actions/summarize`, `/actions/report`, `/actions/complete`,
  `/actions/publish` routes are gone; `/actions/generate`,
  `/actions/back_to_workspace`, `/actions/back_to_home` are the
  new verbs.
- **Persistence** — schema version bumped 7 → 8. v8 migration:
  `ALTER TABLE workspaces ADD COLUMN last_known_state TEXT`
  (idempotent — only if the column is missing). `_row_to_dict`
  shifts left by zero (no DROP this time); `_infer_state` elevates
  legacy `SEARCHING` / `SUMMARIZING` / `REPORTING` / `PUBLISHING`
  enum values to the corresponding final state via
  `data-driven` inference.
- **Validator** — no citation-related changes.
- **Workflow** — `research_workflow.py` rewritten; the
  LangGraph is now three nodes (`search` → `summarise` → `report`)
  wired into one state but the orchestrator is authoritative
  (the graph is documentation).
- **Container** — dropped `SummarizePapersUseCase`-as-distinct
  wiring; it's now called from inside `GenerateReportUseCase`.
- **Frontend** — `WorkspaceState` union collapsed to
  `'INITIAL' | 'INTERMEDIATE' | 'FINAL' | 'ERROR'`;
  `WorkspaceAction` collapsed to
  `'search' | 'generate' | 'retry' | 'add_paper' | 'remove_paper' |
  'back_to_workspace' | 'back_to_home'`. `client.ts` exposes
  `runGenerateAction()` and `runRegressionAction()`. The
  `nextAllowedActions()` selector mirrors the backend table.

## Consequences

Positive:

- **Mental model matches the UI.** A new contributor can read
  the FSM in 30 seconds. The three pages and three "happy path"
  actions (`search`, `generate`, `retry`) are the entire surface
  area for end users.
- **Wire format is smaller.** `WorkspaceResponse` is simpler.
  `WorkspaceState` enum drops from nine values to four.
- **No transient races.** The frontend spinner replaces the
  FSM's transient states. We no longer have to worry about the
  user double-clicking "Generate Report" while the workspace is
  in `SUMMARIZING` — the button is just disabled while the
  spinner is up.
- **Recovery is straightforward.** `retry` from `ERROR` restores
  the previous state via `last_known_state`. The regression
  actions (`back_to_*`) let the user navigate the FSM in reverse
  to fix problems.

Negative / trade-offs:

- **Loss of in-flight visibility.** A user can't see "summarizing
  in progress" as a discrete state in the FSM, only as a UI
  spinner. Operators looking at the database see only
  `INITIAL`/`INTERMEDIATE`/`FINAL`, not "the LLM is working
  right now." This is fine for our scale but worth flagging if
  we ever want to add a "operations dashboard."
- **`generate` is now a long-running call** (10–60 s for the
  full pipeline including the PDF render). We mitigate this
  with a UI spinner and the existing `/metrics` Prometheus
  counters; the failure mode is well-understood.
- **PDF download is a side effect of `generate`.** A user who
  navigates to `FINAL` and clicks "Generate Report" again on
  the Workspace page would have to remove all papers and search
  again (regression to `INITIAL`). This matches the original
  intent — `generate` is destructive of any pre-existing report.

## Notes on transient-in-flight handling

The previous FSM had four transient states (SEARCHING,
SUMMARIZING, REPORTING, PUBLISHING) that the orchestrator
entered and exited during a multi-step operation. The UI's
spinner replaces this — `handleGenerateReport` and `handlePublish`
both set local `generating` / `publishing` flags, and the
`WorkspaceActionBar` button is disabled while either is true.

For operators that want to see "what's happening" at the DB
level, the Prometheus `/metrics` endpoint exposes the LLM
counters (`bioresearch_llm_call_total`,
`bioresearch_llm_duration_seconds`) and the in-process queue
size, which is enough telemetry for any reasonable diagnostic.

## Migration

v7 → v8:

```sql
ALTER TABLE workspaces ADD COLUMN last_known_state TEXT;
```

Idempotent — only runs if the column is missing. The
`last_known_state` is `None` for workspaces that never entered
ERROR; for workspaces that did enter ERROR, it captures the
pre-ERROR state so `retry` can restore it.

Legacy FSM values (`SEARCHING`, `SUMMARIZING`, `REPORTING`,
`PUBLISHING`, `CREATED`, `PAPERS_RETRIEVED`, `SUMMARIZED`,
`REPORTED`, `COMPLETED`) are elevated by `_infer_state`:

- Transient states → "the post-state I'd have transitioned to"
  (SEARCHING → INITIAL, SUMMARIZING → INTERMEDIATE, REPORTING →
  FINAL, PUBLISHING → FINAL).
- `CREATED` → `INITIAL`.
- `PAPERS_RETRIEVED` / `SUMMARIZED` → `INTERMEDIATE`.
- `REPORTED` / `COMPLETED` → `FINAL`.
- `ERROR` → `ERROR` (no elevation).

This is the same "data-driven" inference pattern ADR-009 used
for the `publishing` state elevation — see that ADR for the
rationale.

## Rollback

The transition is one-way: dropping the v8 migration would
leave existing DB rows with the `last_known_state` column, and
the orchestrator's `_fail()` would silently not record it.
Rollback requires:

1. Keep the `last_known_state` column in the schema (NULL-safe
   in v8).
2. Restore the four transient states and the corresponding
   actions in the FSM enum.
3. Rewrite `WorkspaceOrchestrator.generate` to call the four
   sub-actions (`summarize → report → publish → complete`) with
   the transient state transitions in between.

This is unlikely to be needed in practice — the four-state
design is simpler and matches the user-facing product flow
exactly.
