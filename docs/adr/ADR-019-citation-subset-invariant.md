# ADR-019: Citations are a strict subset of workspace.papers (structural invariant)

## Status

Accepted — 2026-08-31

## Context

The user has a hard rule:

> "the executive reports can contain only references available at INTERMEDIATE, not more (less is possible, but definitely not more!)"

Investigation (commit `4970bdf` is on `master`; this ADR-019 follows it) revealed that the **current code happens to honour this rule on the orchestrator's `generate()` happy path**, but the invariant is held by coincidence, not by structural enforcement.

The chain that keeps the invariant today:

1. `WorkspaceOrchestrator.generate()` always re-runs the summary step:
   ```python
   summary = self._summarize_use_case.execute(session.question, session.papers)
   session.set_summary(summary)
   ```
   `session.papers` is the source of truth for the summary's bibliography.
2. `GenerateReportUseCase.execute()` passes `summary` (with `papers_used = session.papers` by construction) to the report generator.
3. `LLMReportGenerator.generate()` builds the prompt with `bibliography_size = len(summary.papers_used)`, sanitises out-of-range `[paper:N]` markers, then maps the response via `ReportMapper`.
4. `ReportMapper._build_citations()` iterates `list(summary.papers_used)` and emits at most one citation per unique DOI. So `len(report.citations) ≤ len(summary.papers_used)`.
5. Chained: `len(report.citations) ≤ len(summary.papers_used) ≤ len(session.papers)`.

Reproduction with stub orchestrator confirms step 5 holds on the generate() happy path: remove 3 of 10 papers, regenerate, the new report has 7 citations (all matching the 7 remaining papers).

But the invariant is fragile. Three latent failure modes:

1. **`ResearchSession.remove_paper()` does not clear `self.summary` or `self.report`.** After removing papers, `session.papers` shrinks but `session.summary.papers_used` and `session.report.citations` are stale. If anything reads `session.report` before the next generate(), it sees citations for papers no longer in the corpus.
2. **`add_papers()` and `replace_papers()` (the search action) have the same problem.** A fresh search adds papers A, B, C, but `summary.papers_used` still references the previous search's papers D, E, F.
3. **`set_report()` accepts any report.** Nothing prevents future code (or a test, or a buggy integration) from writing a report whose citations reference papers outside `session.papers`.

The user's rule is a product-level invariant. Product invariants belong in the entity layer, not in the orchestrator's happy path.

## Decision

Enforce the invariant **structurally** at the entity layer:

1. **`ResearchSession._mutate_papers(...)`** (private helper) is the single point where `self.papers` changes. It always clears `self.summary` and `self.report` (and `self.published_report`) so stale state can never survive a corpus mutation.

2. **`ResearchSession.set_summary(summary)` validates** that every paper in `summary.papers_used` is in `self.papers` (using `_paper_identity` for dedup-aware comparison). If not, raise `ValueError`.

3. **`ResearchSession.set_report(report)` validates** that every `Citation` in `report.citations` references a paper in `self.papers`. If not, raise `ValueError`.

4. **`ResearchSession.set_published_report(...)`** validates the same way, since the PDF embeds the report.

5. **All three paper-mutation methods (`add_papers`, `remove_paper`, `replace_papers`) route through `_mutate_papers(...)`** so the invalidation happens uniformly. The state-machine effects (e.g. `remove_paper` regressing to INITIAL when papers empty, `replace_papers` advancing to INTERMEDIATE) move into the helper.

6. **Tests pin the invariant.** A new `TestCitationSubsetInvariant` class exercises:
   - add then remove: summary and report cleared
   - remove then read session.report: it is None
   - set_report with citations outside session.papers: ValueError
   - set_summary with papers_used outside session.papers: ValueError
   - replace_papers (search) clears stale summary and report
   - round-trip through SQLite repository: invariant survives serialization

The orchestrator's `generate()` continues to rebuild summary and report from `session.papers` (the happy-path invariant). The new entity-layer checks are **defence in depth**: if the happy path ever fails, the entity refuses to persist the violating state.

### Why a `ValueError`, not a `return None` / silent drop

The user said "executive reports can contain only references available at INTERMEDIATE, never more." If the orchestrator ever produced a report with extra citations and we silently dropped them, the user would notice missing citations and the failure mode would shift from "too many" to "missing." That's a worse user experience: the user would lose data without an error. A `ValueError` propagates up to the orchestrator's `_fail()` helper, which transitions the workspace to `ERROR` with a clear `last_error` message, and the user can `retry` (per ADR-018's retry contract).

### Why at the entity layer, not the orchestrator

The orchestrator already does the right thing. Adding a "belt-and-braces" check in the orchestrator would be redundant. The entity layer is the right place because:

- **The data is the invariant.** The user's rule is about what's stored on the workspace, not how the orchestrator happens to use it. Putting the check in the entity makes the rule a property of the data.
- **All callers benefit.** Today only the orchestrator writes summaries and reports. If a future entry point (e.g. a test fixture, a migration script, an admin tool) writes a summary or report, they get the same guarantee.
- **Symmetry with the FSM.** The FSM has its own invariants ("can only transition through allowed actions," "ERROR must record `last_known_state`"). Those are enforced at the entity layer too (`transition_to`, `_fail`). The citation subset invariant is in the same family.

## Audit pattern

Every layer touched:

- **Entity** (`research_session.py`):
  - New `_mutate_papers(new_papers, paper_sources=None)` helper that replaces `self.papers` and clears `self.summary` / `self.report` / `self.published_report` and `self.state_history` stays unchanged (state transitions are recorded separately).
  - `add_papers`, `remove_paper`, `replace_papers` now delegate to `_mutate_papers`.
  - `set_summary(summary)` validates `summary.papers_used ⊆ self.papers`. Raises `ValueError`.
  - `set_report(report)` validates every `Citation.paper ∈ self.papers`. Raises `ValueError`.
  - `set_published_report(...)` validates the embedded report's citations (the report field is the same `ResearchReport`, so the validation runs through `set_report`).
  - `_paper_identity` is reused for the dedup-aware comparison.

- **Orchestrator** (`workspace_orchestrator.py`):
  - `generate()` is unchanged on the happy path. It still re-derives `summary` and `report` from `session.papers`. The entity-layer checks now run as a by-product of `set_summary` and `set_report`. If a future refactor accidentally drops the re-derivation, the entity checks fire and the workspace transitions to ERROR.
  - `add_paper`, `remove_paper`, `add_papers_bulk`, `search`, `search_with_filters` are unchanged at the orchestrator level — they call the same entity methods that now do the invalidation.

- **Report mapper** (`report_mapper.py`):
  - No change. Citations are already drawn from `summary.papers_used`, which is now validated to be a subset of `session.papers`. The mapper is downstream of the check.

- **Tests** (`tests/unit/test_research_session.py` and a new `tests/unit/test_citation_subset_invariant.py`):
  - Six new tests pin the invariant.

- **ADR** (`docs/adr/ADR-019-citation-subset-invariant.md` — this file).

## Consequences

Positive:

- **The invariant is structural, not procedural.** Future code that touches `session.report` cannot accidentally violate the user's rule. The entity refuses.
- **Stale state is impossible.** Adding or removing papers always clears the stale summary and report. The next `generate()` rebuilds them.
- **Errors are loud, not silent.** If the invariant is violated (e.g. by a future refactor that forgets to re-derive), the workspace moves to ERROR and the user can `retry` — a much better experience than silently dropping citations.
- **Migration-safe.** Existing workspaces in production (with stale summary/report attached) load without the new check firing, because `set_summary`/`set_report` only run on writes, not on reads. The check is forward-looking.

Negative / trade-offs:

- **`_paper_identity` comparison is stringly-typed.** Two papers with the same PMID but slightly different titles or different DOI suffixes compare as the same paper. That's a feature for dedup but could surprise a reader of the validation code. The docstring on `set_summary` / `set_report` calls this out.
- **Validation cost.** `set_report` runs O(N×M) identity comparisons (N citations, M workspace papers). For typical N=20, M=20 that's 400 string comparisons — sub-millisecond. For pathological N=100, M=500 it's 50K comparisons — still milliseconds. Acceptable.
- **Slightly more bookkeeping in `add_papers`.** Today `add_papers` is a single method that just extends the list. After this commit, it routes through `_mutate_papers` which does the dedup, the invalidation, and the touch. Slightly more code, but each piece is small.

## Alternatives

- **Don't enforce, just add a test.** Status quo plus tests. Catches regressions in CI but not at runtime. Rejected: the user wants a hard rule.
- **Filter, don't raise.** Silently drop citations that reference papers outside `session.papers`. Rejected: shifts the failure mode from "too many" to "missing" — worse user experience, and the user can't tell what happened.
- **Enforce at the API layer.** Add a Pydantic validator on `WorkspaceResponse.citations` that drops extras. Rejected: too late — the bad state would already be persisted. The entity is the right layer.
- **Enforce at the use-case layer.** `GenerateReportUseCase.execute` validates the report it returns. Rejected: use cases are interchangeable adapters; the entity is the right layer for invariants that survive use-case swaps.

## Rollback

Reverting requires:

1. Remove the `_mutate_papers` helper and restore the three paper-mutation methods to their direct implementations.
2. Drop the validation in `set_summary` and `set_report`.
3. Delete `TestCitationSubsetInvariant`.

The behaviour reverts to the pre-commit state: invariants held by happy path, no structural enforcement.
