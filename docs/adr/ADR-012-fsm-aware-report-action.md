# ADR-012: FSM-aware REPORT action returns full ReportResponse

## Status

Accepted

## Context

The `REPORT` action is the central FSM transition
that turns a workspace's analytical state
(`PAPERS_RETRIEVED` after `SUMMARIZE` and/or
`COMPARE`) into a finalised report (`REPORTED`).

The original implementation routed the action through
the generic `runAction('report')` API which, like all
other actions, returned a `WorkspaceResponse`. The
frontend then had to **re-fetch** the workspace via
`fetchWorkspace(workspaceId)` to read the persisted
`report` field.

This was wrong for three reasons:

1. **Race condition.** Between the `REPORT` POST and
   the `GET /workspaces/{id}` re-fetch, another
   concurrent action could transition the workspace
   (e.g. `RETRY` on a sibling click), causing the UI
   to read a stale or empty `report` field.
2. **Round-trip waste.** The full `WorkspaceResponse`
   is ~50 KB for a 20-paper workspace (papers,
   citations, summaries, state history). The frontend
   only needs the freshly-built `ReportResponse` —
   it already has the rest of the workspace state in
   memory.
3. **Audit trail ambiguity.** A `WorkspaceResponse`
   return doesn't distinguish "this is the report
   you just generated" from "this is a re-read of
   the workspace". The frontend had to assume the
   report field would be populated, which it isn't if
   the FSM was already past `REPORTED`.

## Decision

The `REPORT` action returns a `ReportResponse`
(defined in `frontend/src/api/client.ts` as the
`runAction('report')` overload), distinct from the
`WorkspaceResponse` returned by every other action.
The frontend `useWorkspace` hook special-cases the
action: it casts the result to `ReportResponse` and
stores it in the `report` state without a re-fetch.

The backend route handler in
`app/api/routes/workspace_actions.py` resolves the
`ReportResponse` from the orchestrator's return
value (which is the typed result of the report
use-case) and returns it directly. No workspace
re-serialization happens.

### Type safety

`runAction('report')` in the API client has an
overload:

```ts
function runAction(action: 'report'): Promise<ReportResponse>;
function runAction(action: WorkspaceAction): Promise<WorkspaceResponse>;
```

The TypeScript compiler enforces the overload, so the
cast on the frontend is verified at build time
(running `tsc --noEmit` catches regressions). The
test `routes through the FSM-aware REPORT endpoint
(Layer-4 audit)` in `Report.test.tsx` covers the
end-to-end behaviour.

### Layer-4 audit pattern

The fix mirrors ADR-009's pattern. When adding a
previously-illegal action, audit four layers:

1. **FSM table** (`app/core/enums/workspace_state.py`)
   — does the new transition exist?
2. **Orchestrator** (`app/application/services/workspace_orchestrator.py`)
   — does the action handler exist?
3. **Structural** (route handler signature) — does
   the wire-format match?
4. **Frontend call-site** (`runAction(action)`) —
   does the frontend consume the right type?

The original REPORT action satisfied layers 1-3 but
not 4. This ADR formalises the pattern.

## Consequences

### Positive

- One round-trip per `REPORT` instead of two.
- No race condition with concurrent actions.
- Type-safe wire-format (overload catches
  regressions at build time).

### Negative

- The frontend has to know which actions return
  `WorkspaceResponse` vs `ReportResponse`. The
  overload pattern is documented in the API client's
  JSDoc.

## References

- Commit `b00b34a fix(report): REPORT action returns ReportResponse not WorkspaceResponse`
- Commit `1faf32e` follow-ups to wire the overload
- `frontend/src/api/client.ts` — `runAction` overload
- `app/api/routes/workspace_actions.py` — route
  handler signature
- `frontend/src/pages/Report.test.tsx` — audit test
