# ADR-009: PUBLISHING FSM state for PDF export

## Status

Accepted

## Context

The workspace FSM (documented in ADR-001 and ADR-008) has
eleven stable states — `CREATED`, `SEARCHING`,
`PAPERS_RETRIEVED`, `SUMMARIZING`, `SUMMARIZED`, `COMPARING`,
`COMPARED`, `REPORTING`, `REPORTED`, `COMPLETED`, `ERROR` —
and a corresponding set of allowed actions (`SEARCH`,
`SUMMARIZE`, `COMPARE`, `REPORT`, `COMPLETE`, `RETRY`,
`ADD_PAPER`, `REMOVE_PAPER`).

The product surface has grown beyond the analytical
workflow: the user needs to be able to **export the final
report as a PDF** so they can email it to colleagues,
archive it alongside the underlying papers, or upload it to
a reference manager. The PDF is not part of the analytical
chain (no LLM call, no literature search), but it is a
real workflow step with its own audit-trail and its own
terminal-ish state.

The naive approach — add a `download_pdf` endpoint that
re-renders the report on demand — is wrong for three
reasons:

1. **Determinism.** A re-rendered PDF can drift between
   requests if the renderer changes; the user expects the
   file they downloaded last Tuesday to be byte-identical
   to the file they download today.
2. **Audit trail.** A standalone download endpoint has no
   state transition, so the audit log shows no record that
   the user exported the artefact. The FSM is the canonical
   audit trail in this codebase.
3. **Clean Architecture.** The orchestrator is the single
   mutation surface for the FSM. A standalone endpoint
   would bypass the orchestrator and re-introduce the same
   anti-pattern that ADR-008 fixed for the `report` action.

We need a twelfth state — `PUBLISHING` — that sits between
`REPORTED` and `COMPLETED`. The state is transient (the PDF
render is fast — single-digit milliseconds for a 20-paper
report — so users will rarely see it), but it MUST be a
real state in the FSM table because the audit trail is the
audit trail.

## Decision

Add `PUBLISHING` as a twelfth FSM state and `PUBLISH` as a
new `WorkspaceAction`. Render the PDF on the server, persist
the bytes on the session, and serve them via a dedicated
`GET /workspaces/{id}/published-report.pdf` endpoint.

### Four-layer audit pattern

This decision is structured as a **four-layer audit** of the
existing FSM surface, with one fix per layer. The pattern
comes from the `fsm-action-expansion` skill and is the
recipe for any new FSM action.

| Layer | Location                                  | Before                                  | After                                            |
|-------|-------------------------------------------|-----------------------------------------|--------------------------------------------------|
| 1     | `app/core/enums/workspace_state.py`       | No `PUBLISH` action, no `PUBLISHING` state, no `REPORTED → PUBLISHING` transition | Enum values + transition row + `_TRANSIENT_STATES` updated + ASCII diagram updated |
| 2     | `app/application/services/workspace_orchestrator.py` | No `publish()` method, no `pdf_generator` DI | New `publish()` method with FSM gate (`transition_to(PUBLISH, reason=...)`) + structural guard + auto-`force_state(COMPLETED, reason=...)` |
| 3a    | `app/domain/entities/research_session.py` | No `published_report` slot              | New `published_report: PublishedReport \| None` field + `set_published_report()` method |
| 3b    | `app/domain/entities/published_report.py` | File did not exist                      | New `PublishedReport` dataclass with PDF magic-header validation (`%PDF-` prefix), byte-size caps, and a `create()` factory that stamps `published_at` |
| 3c    | `app/domain/interfaces/pdf_generator.py`  | File did not exist                      | New ABC + `generate(report) -> bytes` contract (Clean Architecture: use case depends on the interface, infrastructure implements it) |
| 3d    | `app/infrastructure/pdf/minimal_generator.py` | File did not exist                  | Hand-rolled PDF 1.4 generator (~370 lines, no third-party dependency). Produces valid single-page PDFs with title, summary, citations, limitations, and future-work sections |
| 3e    | `app/api/routes/workspace_actions.py`     | No `POST /actions/publish`, no `GET /published-report.pdf` | Two new endpoints. The POST runs the FSM action; the GET serves the persisted bytes (`Content-Type: application/pdf`, `Content-Disposition: attachment`, `Cache-Control: no-store`) |
| 3f    | `app/api/schemas/workspace_response.py`   | No `published_report_available` flag    | New boolean field exposing whether the workspace has a downloadable PDF. Independent of `report_available` |
| 4     | `frontend/src/{api/client.ts, hooks/useWorkspace.ts, models/workspace.ts, pages/Report.tsx}` | No `api.runPublishAction`, no `'publish'` in `WorkspaceAction`, no Publish-as-PDF button | New client method + hook switch case + Report page button + Download PDF link with belt-and-braces `publishedAt` state slot for stale-render prevention |

The four-layer pattern is significant because each layer
pins a different invariant:

- **Layer 1** pins the FSM contract (transition table).
- **Layer 2** pins the runtime gate (the orchestrator's
  `transition_to` call raises `IllegalWorkspaceActionError`
  on a wrong starting state).
- **Layer 3** pins the structural assumptions (the entity,
  the schema, the route) — the things the orchestrator
  silently assumes are true about its inputs and outputs.
- **Layer 4** pins the wire-format — the frontend MUST call
  the FSM-aware endpoint, NOT a legacy shortcut that
  bypasses the orchestrator.

If any layer is missed, the action either fails in
production (Layer 1/2) or silently produces wrong artefacts
(Layer 3/4). The audit ensures all four are wired.

### FSM walk

The user-visible path is a single click on the
**"Publish as PDF"** button. Internally:

```
REPORTED ──[PUBLISH]──> PUBLISHING ──[force_state]──> COMPLETED
                              │
                              └─ renders PDF (MinimalPDFGenerator)
                              └─ persists on session (PublishedReport.create)
                              └─ records audit-trail entries:
                                 PUBLISHING: reason="PDF export in flight"
                                 COMPLETED: reason="PDF published"
```

`PUBLISHING` is transient — added to
`_TRANSIENT_STATES` so the workspace-status strip (when it
exists) treats it like `SEARCHING` or `REPORTING`: visible
during the action, but the user only sees `COMPLETED` once
the network round-trip resolves.

The transition from `PUBLISHING` → `COMPLETED` uses
`force_state`, not `transition_to`, because no
`WorkspaceAction` corresponds to it (the user is not
initiating the move — the orchestrator is). The
`reason="PDF published"` argument is the audit trail's
distinguishing signal: a `transition_to` would record a
`WorkspaceAction` value, but `force_state` records only
the reason. Future forensic analysis can tell auto-triggered
state moves from user-initiated ones by checking whether
the `StateTransition.action` field is null.

### Why a hand-rolled PDF generator, not a library?

We considered:

- **`reportlab`** — heavyweight, pulls in Pillow (~30 MB
  image bloat).
- **`weasyprint`** — needs Cairo + Pango system libs,
  fiddly to install in the minimal image.
- **`fpdf2`** — lighter, but still a third-party dep for
  what is intentionally a minimal feature (the report is
  mostly text).

PDF 1.4 is well-documented; ASCII-only text rendering is a
few hundred lines. We produce a single-page Helvetica
layout with one of the 14 base 14 fonts (no embedding
required). Limitations — no multi-page flow, no non-Latin
scripts — are acceptable for v1 (the report is
overwhelmingly ASCII in the biomedical domain).

If we later need richer rendering (embedded charts, custom
fonts, multi-page flow), we can swap the implementation
behind the `PDFGenerator` interface without changing the
FSM, the API, or the frontend.

### Frontend wire-format contract

The Publish-as-PDF button MUST route through
`runAction('publish')` in `useWorkspace.ts`, which dispatches
to `POST /workspaces/{id}/actions/publish`. The legacy
`api.complete` shortcut would advance to `COMPLETED` but
leave `session.published_report` empty, breaking the PDF
download.

The button has a `data-action="publish-pdf"` attribute so
end-to-end tests can target it without coupling to the
button label. The "Download PDF" link visible after a
successful publish points to the GET endpoint constructed
via `api.getPublishedReportUrl(workspaceId)`.

A `publishedAt` local state slot bumps on every successful
publish to force a re-render even when the Zustand
subscriber hasn't yet flushed. The cost is one extra
`setState` per publish; the benefit is a stale-render
guard that catches both the production edge case AND any
test mocks that don't subscribe to store updates.

### Four-state test discipline

Per the `fsm-action-expansion` skill, every layer-4 fix
needs four test cases. We applied the discipline twice (once
for the backend, once for the frontend):

**Backend (`tests/unit/test_workspace_orchestrator.py`):**

1. **Positive** — `test_publish_advances_reported_to_completed_via_publishing`:
   `REPORTED → PUBLISHING → COMPLETED` walk with PDF
   persisted on the session.
2. **Audit trail** —
   `test_publish_records_audit_trail_through_publishing_state`:
   `state_history` records both transitions with the
   correct `reason` strings.
3. **Negative** — `test_publish_from_other_states_raises_illegal_action`:
   PUBLISH from CREATED, PAPERS_RETRIEVED, SUMMARIZED, and
   COMPARING all raise `IllegalWorkspaceActionError` with
   `"publish"` absent from `allowed_actions`.
4. **Structural pin** — `test_publish_persists_pdf_in_repository`:
   PDF bytes survive a refetch through the repository's
   `update → get` cycle.

**Backend API (`tests/integration/test_api_fsm.py`):**

1. **Positive** — `test_publish_action_from_reported_advances_to_completed`:
   POST returns 200 with state=COMPLETED and
   `published_report_available=true`.
2. **Negative** — `test_publish_action_from_papers_retrieved_returns_409`:
   POST returns 409 with the standard FSM error envelope.
3. **Wire-format (success)** —
   `test_published_report_pdf_endpoint_returns_pdf_after_publish`:
   GET returns 200 with `Content-Type: application/pdf`,
   valid PDF bytes, and `Content-Disposition: attachment`.
4. **Wire-format (404)** —
   `test_published_report_pdf_endpoint_returns_404_before_publish`:
   GET before publish returns 404 with an actionable
   error message.

**Frontend (`frontend/src/pages/Report.test.tsx`):**

1. **Positive** — `renders the "Publish as PDF" button when
   a report is available`: button is in the DOM with the
   `data-action="publish-pdf"` attribute.
2. **Negative** — `does NOT render the "Download PDF" link
   before publish`: the wire-format guard that catches
   Layer-4 regressions.
3. **Wire-format** — `renders the "Download PDF" link
   AFTER publish`: the link appears with the correct
   `href` and `download` attributes.
4. **Layer-4 audit** — `routes through the FSM-aware
   PUBLISH endpoint`: asserts `runAction('publish')` is
   called AND `api.runPublishAction` is NOT called
   directly (the false-positive guard from the skill).

**Backend suite**: 492/492 pass (was 488 + 4 new FSM tests).
**Frontend suite**: 228/228 pass (was 223 + 5 new
Publish tests).

### File-level diff

- `app/core/enums/workspace_state.py` — added
  `WorkspaceState.PUBLISHING` (and `_TRANSIENT_STATES`),
  `WorkspaceAction.PUBLISH`, `REPORTED → PUBLISHING`
  transition row. Updated the ASCII state diagram.
- `app/domain/entities/published_report.py` — **new**.
  ~150 lines including the PDF magic-header validator.
- `app/domain/entities/research_session.py` — added
  `published_report` slot + `set_published_report()`
  method.
- `app/domain/interfaces/pdf_generator.py` — **new**.
  Abstract `PDFGenerator` interface.
- `app/infrastructure/pdf/__init__.py` — **new**.
- `app/infrastructure/pdf/minimal_generator.py` — **new**.
  ~370-line hand-rolled PDF 1.4 generator.
- `app/application/services/workspace_orchestrator.py` —
  imported `PDFGenerator` and `PublishedReport`, added
  `pdf_generator` constructor parameter, wrote
  `publish()` method.
- `app/config/container.py` — wired
  `MinimalPDFGenerator()` into the orchestrator's DI.
- `app/api/routes/workspace_actions.py` — added
  `POST /{id}/actions/publish` and
  `GET /{id}/published-report.pdf`. Imported `Response`
  from `fastapi`.
- `app/api/schemas/workspace_response.py` — added
  `published_report_available` field + wired it through
  `from_domain`.
- `frontend/src/api/client.ts` — added
  `api.runPublishAction` and `api.getPublishedReportUrl`.
- `frontend/src/hooks/useWorkspace.ts` — added `case
  'publish'` to the `runAction` switch.
- `frontend/src/models/workspace.ts` — added `'publish'`
  to the `WorkspaceAction` union, added
  `published_report_available` to `WorkspaceResponse`.
- `frontend/src/pages/Report.tsx` — imported `api` and
  `Download` icon; added `publishing`, `pubError`,
  `publishedAt` state; added `handlePublish` function;
  added Publish-as-PDF button (with `data-action="publish-pdf"`)
  and Download PDF link (gated by `publishedReportAvailable` ||
  `publishedAt > 0`); added error display block.
- `frontend/src/state/workspaceStore.test.ts` — added
  `published_report_available: false` fixture field.

### Test additions

- `tests/unit/test_workspace_orchestrator.py` — 4 new
  tests for PUBLISH (positive, audit-trail, negative across
  4 illegal states, structural persistence). Also added a
  `_make_report()` helper used by these tests.
- `tests/integration/test_api_fsm.py` — 4 new tests for
  the POST publish and GET pdf endpoints. Added a
  `StubOrchestrator.publish()` that mirrors the real
  orchestrator's flow.
- `tests/unit/test_resolve_and_add_by_title.py` — added
  `StubPDFGenerator` (no LLM-related changes; required
  because the orchestrator constructor needs the
  `pdf_generator` dependency).
- `tests/unit/test_search_with_filters_attribution.py` —
  same as above (`_StubPDFGenerator`).
- `frontend/src/pages/Report.test.tsx` — 5 new tests for
  the Publish-as-PDF and Download PDF behavior (positive
  button render, no link before publish, link after
  publish with wire-format attributes, Layer-4 audit
  through `runAction('publish')`, error surfacing with
  button still enabled).
- `tests/unit/test_openai_compatible_provider.py` — already
  added in the pick-up 1 fix (related but not directly
  part of this ADR).

## Consequences

### Positive

- **Audit trail** for the export step. The state history
  shows the full lifecycle of the workspace through the
  PDF export.
- **Deterministic downloads**. The bytes the user
  downloads are exactly what the publish step produced.
  Re-publishing produces new bytes; the previous bytes
  remain in the audit trail.
- **Layered change**. The orchestrator's `publish()` method
  follows the same pattern as `complete()` — single
  transaction, single audit-trail entry, single
  repository update. The new state fits cleanly into the
  existing FSM surface.
- **Clean Architecture intact**. The orchestrator depends
  on the `PDFGenerator` interface, not on the concrete
  `MinimalPDFGenerator`. Swapping implementations (e.g.
  adding a `ReportLabPDFGenerator` later for richer
  rendering) is a one-line change in the DI container.
- **Frontend wire-format pinned**. The four frontend tests
  catch the regression where a future contributor might
  wire the button through the legacy `api.complete`
  shortcut.

### Negative

- **New transient state in the FSM**. Adds one more row
  to `TRANSITIONS`, one more entry in
  `WorkspaceState.__members__`, and one more entry in
  `_TRANSIENT_STATES`. Slight increase in test surface
  for any future action audit.
- **No multi-page flow in the minimal generator**. The
  hand-rolled PDF generator produces a single-page layout
  and silently truncates content that overflows. For
  20-paper summaries this is fine; for 100+ papers the
  generated PDF could lose content. Future work: add a
  streaming text-layout loop with multi-page support.
- **No non-Latin script support**. The minimal generator
  uses Helvetica + WinAnsiEncoding. Real biomedical
  content is overwhelmingly ASCII, so this is acceptable
  for v1, but a future contributor adding non-Latin
  support will need to either embed a Unicode-capable
  font (ReportLab path) or constrain the input to Latin-1.
- **`.env` is currently in the repo** from this session's
  live-verify work. The standing rule requires it be
  removed before the final commit. (See the
  "Recommended next-session picks-up" section for the
  cleanup steps.)

## Alternatives considered

### Alternative A: Standalone download endpoint, no FSM change

A `GET /workspaces/{id}/report.pdf` endpoint that re-renders
the PDF on demand.

- Pros: simpler; no FSM change.
- Cons: no audit trail (no state transition), bytes drift
  if the renderer changes, bypasses the orchestrator
  (anti-pattern flagged by ADR-008 for `report`).

### Alternative B: New COMPLETED state distinct from published

Add `PUBLISHED` as a terminal state distinct from
`COMPLETED`. The user publishes once; the workspace goes
REPORTED → COMPLETED → PUBLISHED.

- Pros: clean separation; `COMPLETED` means "report done,
  can keep editing" and `PUBLISHED` means "exported, do
  not touch".
- Cons: the user can still edit a workspace after it's
  PUBLISHED in practice (regenerating the report, adding
  more papers). The model doesn't match the reality.
  Adding a true terminal state would require a new "edit"
  action to unblock the user, which is a bigger change
  than the PDF export is worth.

### Alternative C: Use reportlab / fpdf2 / weasyprint

- Pros: less code to maintain in `minimal_generator.py`.
- Cons: heavyweight deps; one of them (weasyprint)
  requires system libs that aren't in the minimal image.

The audit chose the chosen path: hand-rolled PDF + new
`PUBLISHING` transient state + `COMPLETED` terminal reuse.

## Related ADRs

- ADR-001 — Adopt Clean Architecture. The
  `PDFGenerator` interface lives in `domain/interfaces/`
  with `MinimalPDFGenerator` as the infrastructure
  implementation.
- ADR-008 — One-click report from PAPERS_RETRIEVED.
  Established the pattern of auto-triggering
  intermediate steps inside the orchestrator's
  `report()` method. `publish()` follows the same
  pattern (auto-`force_state` after the generator call).
- ADR-008 follow-up (`306772c`) — "Lesson for future
  ADRs" note. This ADR follows that lesson: the four-layer
  audit was performed BEFORE writing any code, and the
  same pattern is now the standing recipe for any new FSM
  action.