# ADR-008: One-click report from PAPERS_RETRIEVED

## Status

Accepted

## Context

The FSM transition table (historically documented in
`research_workflow.py` and centralised in
`app/core/enums/workspace_state.py::TRANSITIONS`) gates the
REPORT action on the workspace having gone through the full
preparation chain:

```
CREATED → SEARCHING → PAPERS_RETRIEVED →
    SUMMARIZING → SUMMARIZED →
    COMPARING → COMPARED →
    REPORTING → REPORTED
```

The user must run **summarize** (and historically also
**compare**) before the system will let them generate a
report. The orchestrator enforces this with a runtime check
in `WorkspaceOrchestrator.report()`:

```python
session = self._repository.get(workspace_id)
if session.summary is None:
    raise IllegalWorkspaceActionError(
        current_state=session.state.value,
        action=WorkspaceAction.REPORT.value,
        allowed=[a.value for a in allowed_actions(session.state)],
    )
```

The result, when the user clicks "Generate Report" from the
PAPERS_RETRIEVED state, is a 409 response:

> `Action 'report' is not allowed from state
> 'PAPERS_RETRIEVED'.`

The user-facing symptom: the report button is greyed out at
PAPERS_RETRIEVED. The user has to manually click "Summarize"
first, wait ~4-10s, then click "Generate Report" and wait
another ~5-15s. Two clicks and two waits for one
deliverable.

The intermediate steps (summarize, compare) are useful when
the user wants to inspect or edit them. They are not
prerequisites for the report: the report generator
(`GenerateReportUseCase.execute`) takes the question +
summary as input, and it tolerates a freshly-generated
summary as well as a cached one — the only failure mode is
`summary is None`. Compare isn't read at all by the report
generator today (it's a roadmap item).

The friction shows up in two real workflows:

1. **Researcher who pasted a DOI** — they have papers but
   not a summary. They want the report now, not after
   hitting Summarize.
2. **Researcher iterating on a question** — they added
   papers, generated one report, modified the question,
   added more papers, want a fresh report. The intermediate
   "stale" summary is fine for them — they care about the
   final output.

The simple "Summarize first" UX hint doesn't help because
the action is hidden — the user sees no signal that an
intermediate step is needed.

## Decision

Allow `REPORT` directly from `PAPERS_RETRIEVED`. Two
changes:

### 1. FSM transition table

`app/core/enums/workspace_state.py`:

```python
WorkspaceState.PAPERS_RETRIEVED: {
    WorkspaceAction.SEARCH: WorkspaceState.SEARCHING,
    WorkspaceAction.SUMMARIZE: WorkspaceState.SUMMARIZING,
    WorkspaceAction.REPORT: WorkspaceState.REPORTING,    # new
    WorkspaceAction.REMOVE_PAPER: WorkspaceState.PAPERS_RETRIEVED,
    WorkspaceAction.ADD_PAPER: WorkspaceState.PAPERS_RETRIEVED,
},
```

The state transitions to REPORTING (transient) and then to
REPORTED on success, exactly as it does from SUMMARIZED.

### 2. Auto-summarise in the orchestrator

`WorkspaceOrchestrator.report()` no longer raises
`IllegalWorkspaceActionError` when `session.summary is
None`. Instead it runs the summarisation step inline before
generating the report:

```python
def report(self, workspace_id: UUID) -> ResearchSession:
    session = self._repository.get(workspace_id)

    # Auto-summarise when the user skips the explicit
    # Summarize step. This makes the
    # PAPERS_RETRIEVED → REPORTED transition a single
    # action from the user's perspective; the state
    # machine records the intermediate
    # SUMMARIZING/SUMMARIZED transitions for audit.
    if session.summary is None:
        session = self.summarize(workspace_id)
        session = self._repository.get(workspace_id)

    self._enter_action(session, WorkspaceAction.REPORT)
    ...
```

Why not just `force_state(SUMMARIZED)` and generate the
report without summarising? Because the report generator
takes a real summary as input — an empty / stub summary
would yield a vacuous report. Running the real summarise
step preserves the report quality.

Why not skip the FSM and just produce a report? Because the
audit trail (state_history) matters for debugging and for
the `derived_from` chain: a report that's been correctly
summarised first is auditable to its source papers. The
intermediate state transitions (PAPERS_RETRIEVED →
SUMMARIZING → SUMMARIZED → REPORTING → REPORTED) appear in
`state_history` so a future maintainer can see exactly
which steps ran.

### What did NOT change

- **The `Session.summary is None → ERROR` guarantee**. If
  the auto-summarise fails, the orchestrator's existing
  `_fail` machinery flips the workspace to ERROR and
  persists the reason. The user sees the failure but
  doesn't see a half-generated report.
- **The `compare` action remains separate**. The user can
  still run compare independently to inspect the
  cross-paper evidence. The report generator does not
  consume compare output today.
- **The SUMMARIZED state's REPORT path is unchanged** —
  the orchestrator still honours the explicit
  "Summarize → Report" two-step workflow for users who
  want it. The auto-summarise is a fallback, not a
  replacement.

## Consequences

**Positive**

- The user can hit "Generate Report" exactly once and get
  a report — the most common workflow becomes one click
  instead of two.
- The action bar's Generate Report button is enabled at
  PAPERS_RETRIEVED, removing the "why is this greyed out?"
  confusion.
- The auto-summarise is invisible to the user; the FSM
  audit trail records the intermediate steps.
- No new env var, no new setting, no migration. The
  change is purely additive in the FSM table and the
  orchestrator method.

**Negative**

- A user who doesn't want a summary generated (e.g. they
  plan to add more papers and will summarise later)
  can't bypass it via the report action. Mitigation:
  they can click Summarize separately (the action is
  still in the FSM), so the auto-summarise never overrides
  the user's explicit choice.
- The audit trail includes the auto-summarise state
  transitions. If a future maintainer looks at the
  history and sees
  `PAPERS_RETRIEVED → SUMMARIZING → SUMMARIZED → REPORTING → REPORTED`
  in a single user action, they might be surprised. We add
  a `reason` field to the intermediate transitions so the
  history records "auto-summarised before report".
- The orchestrator is now responsible for one additional
  side effect (auto-summarise) inside the report
  handler. The unit tests must cover both the
  `summary is None` path and the `summary is not None`
  path; we add a dedicated test for this.

## Alternatives considered

- **Make the UI show a "Run Summarize first" hint on the
  disabled button**. Rejected because (a) the user has to
  remember the intermediate step, (b) two clicks for one
  deliverable is friction, (c) the hint doesn't help
  users who don't yet understand the FSM.
- **Make the report generator accept `summary is None`
  and produce a report from papers alone**. Rejected
  because the report quality drops noticeably without a
  summary — the report is supposed to *synthesise* the
  evidence, not just list papers. Running summarise first
  preserves the synthesis.
- **Add a new `GENERATE_FULL_REPORT` action that does
  summarize → compare → report in one transition**.
  Rejected because (a) it's a duplicate of the existing
  workflow with a different name, (b) it complicates the
  FSM table with three combinations (with/without
  compare, with/without summarize), (c) the simplest fix
  is to allow `REPORT` from `PAPERS_RETRIEVED` and let
  the orchestrator do the right thing.
- **Auto-summarise silently without state transitions**
  (call the use case directly, bypass the FSM).
  Rejected because (a) it breaks the audit trail, (b) it
  hides what ran from the `allowed_actions` view, (c) the
  state transitions ARE useful — they tell the future
  maintainer "yes, summarise ran, here's where it
  failed".

## References

- `app/core/enums/workspace_state.py::TRANSITIONS` — the
  FSM transition table, now allows `REPORT` from
  `PAPERS_RETRIEVED`.
- `app/application/services/workspace_orchestrator.py::report` —
  replaces the runtime gate with auto-summarise.
- Live verification: `POST /workspaces/{id}/actions/report`
  from `PAPERS_RETRIEVED` returns HTTP 200 with state
  `REPORTED`, with `state_history` showing the
  intermediate summarise transitions.
