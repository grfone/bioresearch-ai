# ADR-018: Context-aware FSM transitions via callable resolvers

## Status

Accepted — 2026-08-31

## Context

[ADR-017](ADR-017-three-page-fsm.md) collapsed the FSM to four
states and introduced `last_known_state` so a subsequent `retry`
from `ERROR` could restore the pre-error state. The original
implementation (commit `7df2fd4`) made the FSM table fixed
(`ERROR + RETRY → INITIAL` literally) and compensated in the
orchestrator's `retry()` method:

```python
# ``7df2fd4`` retry implementation
target = session.last_known_state or (
    WorkspaceState.INTERMEDIATE if session.papers else WorkspaceState.INITIAL
)
session.transition_to(WorkspaceAction.RETRY)   # moves to INITIAL per the table
if session.state != target:
    session.force_state(target, reason="Retry: returning to ...")
```

This left a `TODO` comment in the code referencing this ADR. The
behaviour was correct but the architecture was wrong:

1. **The FSM table lied.** It claimed `ERROR + RETRY → INITIAL`,
   but the user-visible behaviour was `INTERMEDIATE` when
   papers exist. The audit trail showed two transitions
   (`ERROR → INITIAL` from the table, then `INITIAL →
   INTERMEDIATE` from the `force_state` override) instead of
   one.
2. **`force_state` was misused.** Its docstring describes it as
   "only used by the repository during deserialization and by
   the orchestrator when recording the outcome of an action."
   Using it to **correct** the FSM table was a documented-as-
   private escape hatch being used to compensate for a missing
   table feature.
3. **Context was computed twice.** The orchestrator computed
   the target state and the FSM computed a different state. The
   orchestrator's computation was the "correct" one but was
   applied as an override rather than as the primary mechanism.

## Decision

Make the FSM table **context-aware** by allowing transition
targets to be either a fixed `WorkspaceState` constant or a
callable resolver of the form
`Callable[[ResearchSession], WorkspaceState]`.

The single new entry is `ERROR + RETRY → _retry_target`, where
`_retry_target` reads `session.last_known_state` (set by the
orchestrator's `_fail()` helper when ERROR is entered) and
falls back to a papers-based heuristic for pre-v8 rows. The
orchestrator's `retry()` method drops the `force_state` override
and reduces to a single `transition_to(WorkspaceAction.RETRY)`
call.

### Type alias

```python
TransitionTarget = (
    "WorkspaceState "
    "| Callable[[ResearchSession], WorkspaceState]"
)
```

The chained forward-reference lets `from __future__ import
annotations` carry the type through Pyright without an
import cycle (the entity layer imports the FSM module, which
can't import the entity module back).

### `next_state` signature change

```python
def next_state(
    current: WorkspaceState,
    action: WorkspaceAction,
    *,
    session: Any | None = None,
) -> WorkspaceState:
```

`session` is required when the table entry is a callable
resolver. If omitted, `next_state` raises `TypeError` with a
clear message — a programmer error, not a runtime FSM
ambiguity. Fixed-target entries ignore `session`, so existing
callers and tests that omit it continue to work.

### Resolver contract

A session-aware resolver MUST be a **pure function** of its
input:

- It MAY read `session.last_known_state`, `session.papers`,
  `session.summary`, `session.report`, etc.
- It MUST NOT mutate the session.
- It MUST NOT call repository operations.
- It MUST return a `WorkspaceState` (or raise — but no
  existing resolver raises).

The orchestrator persists the resulting state via
`_repository.update()` after `transition_to` returns. The
resolver is not allowed to do that itself; this keeps the
side-effects in one place.

### Why a callable rather than a richer value

Two alternatives were considered:

1. **A tuple `(state, condition)`** — "transition to `state`
   if `condition(session)` else `state_default`". This
   generalises the callable form but adds a second concept
   (a "condition") without adding expressive power — any
   condition is just a function returning a state.
2. **A dict of contexts** — "transition to `state` for
   context X, `state2` for context Y". This bakes the
   contextual knowledge into the table at the wrong layer
   and makes the table harder to read.

The callable form is the **simplest extension** that captures
the use case: the table holds a pointer to the function that
decides, the function lives next to the FSM table so the
reader can see both at once, and the contract (pure, no side
effects) is enforceable by review.

## Audit pattern

Every layer touched:

- **FSM** — `app/core/enums/workspace_state.py`: added
  `Callable` and `Any` imports, `TransitionTarget` type
  alias, `_retry_target(session)` resolver function, and the
  `session=None` parameter on `next_state`. The
  `ERROR + RETRY` entry now points to `_retry_target` instead
  of `WorkspaceState.INITIAL`.

- **Entity** — `app/domain/entities/research_session.py`:
  `transition_to` now passes `session=self` to `next_state`.

- **Orchestrator** — `app/application/services/workspace_orchestrator.py`:
  `retry()` reduced from ~22 lines to ~5. The
  `force_state` override and the `target` computation are
  gone. The TODO comment is deleted.

- **Tests** — three new tests pin the new contract:

  1. `tests/unit/test_fsm_transitions.py::test_retry_recovers_from_error`
     — replaced: now asserts that omitting the session
     raises `TypeError` (programmer-error guard), and that
     `transition_to` via the entity correctly produces the
     destination state.
  2. `tests/unit/test_fsm_transitions.py::test_retry_resolver_uses_papers_heuristic_when_last_known_missing`
     — new: exercises the fallback path (no
     `last_known_state`, with / without papers) at the
     resolver level.
  3. `tests/unit/test_workspace_orchestrator.py::test_retry_records_single_transition_in_audit_trail`
     — new: pins the single-transition invariant. The
     audit trail records `ERROR → INTERMEDIATE` in one
     step, not two.

## Consequences

Positive:

- **The FSM table is the single source of truth.** It
  encodes `ERROR + RETRY → _retry_target` directly. No more
  orchestrator overriding it after the fact.
- **The audit trail is honest.** A `retry` action now
  records exactly one `StateTransition`, not two. A
  reviewer can read `ERROR → INTERMEDIATE` (or `INITIAL`)
  and trust it.
- **`force_state` is again reserved for its documented
  purpose.** No application-layer code uses it to
  compensate for FSM-table gaps.
- **Future context-aware transitions are a one-line table
  edit.** Any future entry that depends on session context
  can be expressed as a resolver — no orchestrator override
  required.

Negative / trade-offs:

- **`next_state` is no longer a pure function of
  `(current, action)`.** The signature gained an optional
  `session` argument. The 3 existing fixed-target tests
  don't pass it (default `None`) and continue to work, but
  anyone reading the function signature needs to know that
  some targets are session-aware.
- **`_retry_target` lives in the FSM module** even though it
  reads `ResearchSession.papers` and `last_known_state`
  (entity fields). The forward-reference (`TransitionTarget`
  type alias) keeps the import direction correct — entity
  imports FSM, not vice versa. The resolver itself is small
  enough (10 lines) that this is acceptable; if more
  resolvers grow to need entity internals, we can move them
  to a separate `app/core/enums/resolvers.py` module.
- **No validation that resolvers are pure.** The contract
  is enforced by code review, not by the type system. If a
  future resolver mutates the session, the audit trail will
  be inconsistent. A pure-function decorator could enforce
  this at runtime, but adds complexity for a contract that
  is currently held by a single function.

## Alternatives

- **Keep the static table + orchestrator override.** Status
  quo. Fixes nothing; leaves the TODO in place forever.
- **Move the retry logic into `_fail`'s inverse.** Make the
  orchestrator compute "where to go on retry" before the
  error is even recorded, so the destination is known at
  fail-time rather than retry-time. Doesn't work: at fail
  time we don't know if the user wants to keep the corpus
  (the question is whether the user retries at all).
- **Drop `last_known_state` entirely** and always use the
  papers heuristic. Simpler but wrong: a workspace that was
  mid-search and a workspace that was mid-generation would
  both retry the same way, losing the user's intent.
- **Make `WorkspaceState` a class with methods** rather than
  a string-enum. More expressive but a much larger refactor;
  not justified by a single context-aware transition.

## Rollback

Reverting to the previous behaviour is mechanical:

1. Change `WorkspaceAction.RETRY: _retry_target` back to
   `WorkspaceAction.RETRY: WorkspaceState.INITIAL` in
   `TRANSITIONS`.
2. Re-introduce the `target = ...; transition_to(RETRY); if
   state != target: force_state(target)` block in the
   orchestrator's `retry()` method.
3. Remove the `session` parameter from `next_state` and the
   `session=self` argument from `transition_to`.

The three new tests would fail; they document the new
contract and would need to be reverted alongside the code
changes. None of this affects the database schema or the
wire format, so a rollback doesn't require a migration.
