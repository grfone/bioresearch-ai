# ADR-022: Execute the workspace FSM as a LangGraph StateGraph

## Status

Accepted — 2026-11-26

## Context

The workspace lifecycle was described by a four-state finite state
machine (`INITIAL`, `INTERMEDIATE`, `FINAL`, `ERROR`) whose
specification lives in
`app/core/enums/workspace_state.py` as the `TRANSITIONS` table.
Two things implemented that specification at runtime:

1. **The orchestrator's imperative dispatcher.** Every workspace
   action (`search`, `generate`, `retry`, `back_to_workspace`,
   `back_to_home`) called `session.transition_to(action)`, and the
   legality check and destination resolution happened inside the
   domain aggregate.

2. **`app/application/workflows/research_workflow.py`** — a
   hand-written LangGraph `StateGraph` that was *supposed* to be
   the FSM expressed as a graph. It was not. It modelled a linear
   `START → search → generate → END` pipeline with two nodes, had
   no edges for `ERROR`, `RETRY`, `back_to_home` or
   `back_to_workspace`, and — being dead code — had **drifted** from
   the real FSM without anything noticing. Its own docstring
   conceded the point: *"The orchestrator is the authoritative
   driver today. The graph is exposed for documentation and for
   future checkpointing."*

So the project claimed a LangGraph-based FSM while shipping a
hand-written `if`/`elif` dispatcher and a decorative graph beside
it. The two were free to disagree, and did.

The project charter also imposes a constraint that shapes any
solution. `docs/architecture.md` §5 states:

> LangGraph, CrewAI, MCP, FastAPI, Streamlit, OpenAI, or any
> future framework should never define the project architecture.

and `ARCHITECTURE.md` §2 places "LangGraph workflows" in the
**application** layer, with the rule that dependencies point
downward — the domain layer contains no framework-specific code.

## Decision

Replace the decorative graph with a **real** LangGraph
`StateGraph` that the orchestrator actually executes, and remove
the hand-written mirror so there is exactly one description of the
FSM's topology.

### The transition table stays the single source of truth

`app/core/enums/workspace_state.py` keeps the `TRANSITIONS` table
and `next_state()`. It is pure data plus pure functions, with no
framework import, which is what lets the domain aggregate enforce
its own invariants without depending on a framework.

The graph does **not** restate the table. It is *derived* from it:

```python
for state in WorkspaceState:
    graph.add_node(_source_node_name(state), source_node)
    graph.add_conditional_edges(
        _source_node_name(state),
        router,
        _build_path_map(state),   # built from TRANSITIONS[state]
    )
```

The path map for each state is computed from that state's table
entry, and the router resolves the destination by calling the same
`next_state()` the aggregate calls. A change to the table therefore
changes the graph — there is no second copy to forget.

### Topology: source nodes and destination nodes

Each state appears twice in the graph:

- `state_<name>` — the state as a **source**: you are here, about
  to take an action.
- `land_<name>` — the state as a **destination**: the action
  succeeded, the workspace is now here.

A run is `START → state_<current> → [action] → land_<target> →
END`.

The split is what makes the graph terminate. LangGraph follows
every outgoing edge of a node it lands on, so a single node per
state would send the graph round the FSM indefinitely. With the
split, the destination nodes are terminal.

The conditional edge out of each source node is the *decision*: it
calls `next_state()`, which raises `IllegalWorkspaceActionError`
for an illegal action **before** the aggregate is touched, and
otherwise returns the edge key for the destination. The destination
node is the *mutation*: it calls `session.transition_to(action)`,
which re-validates (an aggregate must never trust its caller),
appends to the audit trail, and clears or sets `last_error`.

Edge labels are the action names, so `WORKSPACE_GRAPH.get_graph()
.draw_mermaid()` renders a labelled diagram of the FSM.

### Error entry stays outside the graph

`ERROR` is entered by `ResearchSession.force_state(ERROR)` when an
action fails, never by a legal action. It is therefore not a
reachable *destination* in the action-driven lifecycle, and the
graph does not model the failure path — the orchestrator's `_fail()`
helper does. `ERROR` is still a reachable *source*, so `retry`
routes correctly out of it.

The session-aware `ERROR + RETRY` transition (ADR-018) is resolved
through `next_state(..., session=session)`, which reads
`last_known_state` and falls back to the papers heuristic. Because
the graph asks the resolver rather than assuming a destination, the
single-transition audit trail ADR-018 introduced is preserved: one
`ERROR → <destination>` entry, not two.

### Layering

`app/application/workflows/workspace_graph.py` lives in the
application layer. `app/domain` and `app/core` contain no LangGraph
import — enforced by a test, not by convention. The aggregate keeps
using the pure `TRANSITIONS` table directly and knows nothing about
the graph.

### Bug found and fixed: the retry destination

The migration surfaced a **pre-existing bug**, confirmed by
reproducing it against the original pre-migration code.

`_fail()` recorded `last_known_state` from `session.state` at the
moment of the failure. By then the failing action's own transition
had already moved the session on — `SEARCH` moves `INITIAL →
INTERMEDIATE` *before* the search runs, and `GENERATE` moves
`INTERMEDIATE → FINAL` *before* the pipeline runs. The recorded
value was therefore the **post-transition** state, not the state the
user was on:

| Failure | Recorded (wrong) | Documented intent |
|---|---|---|
| SEARCH from `INITIAL` | `INTERMEDIATE` | `INITIAL` |
| GENERATE from `INTERMEDIATE` | `FINAL` | `INTERMEDIATE` |

The effect: `RETRY` sent the user to the wrong page. A failed
search landed them on the Workspace page — which implies "search
returned at least one paper", but the search failed, so there are
none. A failed generation landed them on the **Report page, for a
report that was never produced**.

Four separate docstrings described the intended behaviour
(*"INITIAL for a failed search, INTERMEDIATE for a failed
generation"*; the `ERROR + RETRY` comment in the transition table;
the `_retry_target` docstring; the ADR-018 description) and none of
them matched the code. The existing tests did not catch it because
they exercised `_fail()` directly on a session already in the
pre-error state, rather than through a failing action.

The fix: `_enter_action()` now returns the state the workspace was
in *before* the action ran, and `_fail()` takes it as
`origin_state`. The post-transition state is no longer mistaken for
the pre-action one.

### Verification

Behaviour preservation was proven with a deterministic behavioural
snapshot (`scripts/fsm_behaviour_snapshot.py`) covering legal
actions, resolved targets, rejected-action payloads, retry
resolution, audit trails, forced transitions, terminality and
paper-corpus effects. The snapshot generated **before** the
migration and the snapshot generated **after** it are
byte-identical.

New tests in `tests/unit/test_workspace_graph.py` pin the graph's
own contract: the topology matches the transition table, every
action the table rejects is rejected by the graph with an identical
error payload, a rejected action does not mutate the session, the
audit trail gains exactly one entry per transition, and the domain
and core layers contain no framework import.

## Consequences

**Positive**

- The FSM has one executable description. The table and the graph
  cannot drift, because the graph is built from the table.
- The diagram in the README is generated from the running code, not
  drawn by hand.
- LangGraph is now a declared, tested runtime dependency rather than
  an aspirational import in a dead module.
- The retry destination bug is fixed and pinned by regression tests.
- Checkpointing, tracing and graph-native retry become available
  later without another topology migration — the graph is already
  the thing that executes.

**Negative**

- LangGraph becomes a hard runtime dependency of the FastAPI
  backend. It is declared in `requirements/minimal-requirements.txt`
  and `environment.yaml`.
- `ResearchSession.transition_to()` is now called from inside a
  graph node rather than directly by the orchestrator. The
  orchestrator's public API is unchanged; only `_enter_action` and
  `_fail` gained parameters.
- The graph's source/destination node split is a LangGraph
  implementation detail. It reads slightly oddly next to the
  four-state diagram in the README, but it is the only topology that
  both terminates and preserves the labelled-edge rendering.

**Neutral**

- The four serialized workspace states and their API contracts are
  unchanged.
- The illegal-action error payload, and therefore the HTTP 409
  response body, is unchanged.

## Alternatives considered

1. **Keep the hand-written dispatcher, add a graph beside it.**
   Rejected — this is the status quo ante, and it is what produced
   the drifted decorative module.

2. **Move the transition table into the application layer.**
   Rejected — the domain aggregate needs it to enforce its own
   invariants, and the domain must not import the application layer.

3. **Let the domain import LangGraph** so `transition_to` could be
   a graph node. Rejected — it violates
   `docs/architecture.md` §5, which says a framework must never
   define the project architecture. The framework stays an
   implementation detail in the application layer.

4. **Model the failure path in the graph too** (an `error` node
   reached when a node raises). Deferred — the failure semantics
   differ per action (`generate` has three independently-failing
   stages), and the failure path's durable record is
   `force_state(ERROR)` plus `last_known_state`, which the graph's
   action-edge model does not express. Doing it properly is a
   separate change.

## Audit pattern

Every layer touched:

- **Core** — `app/core/enums/workspace_state.py`: unchanged. The
  transition table and `next_state()` remain the specification.

- **Application** —
  `app/application/workflows/workspace_graph.py`: **new**. The
  compiled `WORKSPACE_GRAPH`, `run_transition()`, the transition
  router, the path-map builder, and the resolver prober.
  `app/application/workflows/research_workflow.py`: **deleted**
  (decorative, drifted, uncalled).
  `app/application/services/workspace_orchestrator.py`: `_enter_action`
  routes through `run_transition()` and returns the pre-action
  state; `_fail()` accepts `origin_state`; the five failure sites
  pass it.

- **Domain** — unchanged. `ResearchSession` keeps using the pure
  `TRANSITIONS` table.

- **Tests** — `tests/unit/test_workspace_graph.py`: **new** (22
  tests). `tests/unit/test_workspace_orchestrator.py`: four
  regression tests for the retry destination.
  `scripts/fsm_behaviour_snapshot.py`: **new**, the behaviour
  oracle.

- **Docs** — `README.md` (workflow section, capabilities, feature
  table, ADR index), `ARCHITECTURE.md`, `docs/architecture.md`,
  this ADR.

- **Dependencies** — `requirements/minimal-requirements.txt` and
  `environment.yaml` declare LangGraph and its transitive
  LangChain packages.

## References

- [ADR-017](ADR-017-three-page-fsm.md) — the four-state FSM.
- [ADR-018](ADR-018-context-aware-fsm-transitions.md) — the
  session-aware `ERROR + RETRY` transition.
- [ADR-021](ADR-021-workspace-corpus-server-authoritative.md) —
  server-authoritative workspace corpus.
- `docs/architecture.md` §5 — frameworks never define the
  architecture.
- `ARCHITECTURE.md` §2 — layer responsibilities and dependency
  direction.

---

Guillermo Ramajo Fernández
