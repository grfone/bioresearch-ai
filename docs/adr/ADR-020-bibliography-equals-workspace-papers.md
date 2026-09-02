# ADR-020: Bibliography equals workspace.papers (no LLM-citation gap)

## Status

Accepted — 2026-08-31

## Context

ADR-019 enforced the user's hard rule "the executive reports
can contain only references available at INTERMEDIATE, not
more (less is possible, but definitely not more!)" at the
entity layer. The invariant is ``report.citations ⊆
workspace.papers``.

That commit (5310661) was correct on the upper-bound side,
but the report mapper at
`app/infrastructure/llm/report_mapper.py` still dropped
workspace papers the LLM chose not to mention in its body.
Specifically, ``ReportMapper._build_citations`` extracted
``[paper:N]`` markers and matched paper titles via
substring, but did NOT include any workspace paper that
neither marker-cited nor substring-matched.

The user reported this concretely:

> "after generating report with 4 references, I still get ten
> in the executive report and 20 again when I come back to
> the workspace. Fix it!"

Workspace with 20 papers, report with 10 citations. The user
expected ALL 20 papers to appear in the bibliography. Their
previous rule "less is OK" was based on the assumption that
the LLM might focus on a relevant subset. But after seeing
their actual workspace count was 20 and the report count was
10, they wanted every paper visible — partly for transparency
("I want to see all 20 references available to the LLM") and
partly for verification ("if I remove a paper, does it
actually disappear from the bibliography?").

The original ``_MAX_CITATIONS = 20`` cap was the apparent
intent of the pre-ADR-019 design ("real research sessions
routinely summarise 20+ papers and the report UI only has
room for a curated subset"). But:

- For workspaces with exactly 20 papers, the cap meant the
  mapper silently dropped papers when the LLM didn't cite
  all 20 in its body.
- For workspaces with 25 papers, the cap meant only 20
  appeared in the bibliography even when the user wanted
  to see them all.
- The cap was below the workspace count, so the bibliography
  could never equal the corpus.

## Decision

Remove the cap and **always include every workspace paper in
the bibliography**, dedup-aware, in this order:

1. **Phase 1**: Papers cited via ``[paper:N]`` markers in the
   body, in the order the markers first appear (the LLM's
   natural ordering, which is the best signal of
   "relevance").
2. **Phase 2**: Papers substring-matched (title or DOI) in
   the body, in first-appearance order. Some models
   paraphrase titles instead of citing the bibliography
   index.
3. **Phase 3**: Remaining workspace papers, in corpus order
   (the order they were added to ``workspace.papers``).

Dedup happens across all three phases using a stable paper
identity (PMID → DOI → title) so an LLM that mentions the
same paper twice (once via marker, once via substring)
produces a single citation. The dedup uses a new helper
``ReportMapper._paper_identity`` mirroring the entity's
``_paper_identity`` to keep the comparison stable even when
the LLM has rewritten titles.

The ``_MAX_CITATIONS`` constant is renamed to
``_MAX_CITATIONS_LEGACY`` and retained (unused) so tests
that pin the legacy "≤ 20" contract still import cleanly. The
constant is documented as deprecated and removed in spirit;
the ``max_count`` parameter on ``_build_citations`` is
silently ignored.

## Audit pattern

Every layer touched:

- **Mapper** (`report_mapper.py`):
  - ``_build_citations`` rewrote with the 3-phase logic
    above. ``_paper_identity`` added as a static helper.
  - The ``@staticmethod`` decorator was removed (the method
    now needs ``self`` to call ``_paper_identity``).
  - The ``_MAX_CITATIONS`` constant renamed to
    ``_MAX_CITATIONS_LEGACY``. The call site at line 158
    updated to use the renamed constant.
  - Module docstring updated to note that "every workspace
    paper is included regardless of LLM citation behaviour".

- **Tests** (``tests/unit/test_report_mapper.py``,
  ``tests/unit/test_report_mapper_markers.py``,
  ``tests/unit/test_report_mapper_marker_priority.py``):
  - ``test_mapper_caps_citation_count`` →
    ``test_mapper_includes_all_workspace_papers_no_cap``:
    asserts that 25 papers produce 25 citations.
  - ``test_mapper_skips_papers_not_mentioned_in_summary`` →
    ``test_mapper_includes_papers_not_cited_by_llm``: asserts
    that workspace papers not cited by the LLM still appear.
  - ``test_no_citations_when_summary_does_not_mention_papers``
    → ``test_no_citations_when_no_papers_at_all``: distinguishes
    the "no corpus" case (empty citation list) from the
    "non-empty corpus, LLM didn't cite anything" case (full
    citation list).
  - ``test_markers_out_of_range_are_ignored``: updated to
    include all workspace papers (out-of-range markers are
    still dropped, but Phase 3 fills the rest).
  - ``test_uncited_papers_are_dropped`` →
    ``test_uncited_papers_are_included_in_bibliography`: asserts
    Phase 3 inclusion.
  - ``test_mixed_marker_and_substring_signals` updated to
    expect all 3 workspace papers (marker, substring, and
    uncited).
  - ``test_same_paper_deduped_across_signals` updated to
    expect all 3 workspace papers, each exactly once.

## Consequences

Positive:

- **Bibliography matches workspace.** The user sees exactly
  ``len(workspace.papers)`` citations (subject to PMID/DOI
  dedup). When they remove a paper, the bibliography shrinks
  by exactly one. When they add a paper, it grows by exactly
  one. The user's invariant is now visible in the UI.
- **Transparency.** The user can tell whether a paper was
  "actually used by the LLM" (cited in body via markers) or
  "merely available" (in bibliography but not cited in body).
- **No silent truncation.** The ``_MAX_CITATIONS = 20`` cap
  used to silently drop papers; now every paper in
  ``workspace.papers`` appears.
- **Ordering is principled.** Marker-cited papers first
  (Phase 1, in citation order), then substring-matched
  (Phase 2, in first-appearance order), then the rest
  (Phase 3, in corpus order). The bibliography reads in the
  order the LLM cared about, with "everything else" appended
  at the end.

Negative / trade-offs:

- **Long bibliographies.** A workspace with 200 papers now
  produces a 200-entry bibliography. The PDF and Report
  pages already render this fine (no layout change needed),
  but the user might want a paginated / collapsible view in
  the future. Out of scope for this commit.
- **No dedup-by-title.** The dedup uses PMID → DOI → title
  fallback. Two papers with no PMID/DOI but the same
  title (rare, but possible) would both appear. This matches
  the entity's existing dedup semantics; out of scope for
  this commit.

## Alternatives

- **Add a small cap (e.g. 100).** Keeps the bibliography
  bounded but at 100. Rejected: the user wants the full
  bibliography, and 100 isn't enough for very large
  workspaces anyway. Better to keep the cap at
  ``len(workspace.papers)`` (no actual cap in practice).
- **Pagination.** Truncate the visible bibliography to top
  20 with a "show all" button. Rejected: adds UI complexity
  for a fix that doesn't need it. The PDF bibliography
  already handles long lists fine.
- **Render ``[paper:N]`` in body so the LLM cites everything.**
  Prompt-engineer the LLM to cite every paper. Rejected:
  doesn't help when the LLM genuinely focuses on a subset
  for narrative reasons (the user accepted that as "less is
  OK"). The fix at the mapper level is more robust.

## Rollback

Reverting requires:

1. Restore ``_MAX_CITATIONS = 20`` (rename back).
2. Replace the 3-phase logic with the 2-phase (marker +
   substring) + cap logic.
3. Restore the test expectations for "uncited papers are
   dropped" and "marker cap = 20".

The behaviour reverts to the pre-fix state: bibliography
includes only papers cited by markers or substring, capped
at 20.

## Notes

This is a behavioural change: the bibliography now equals
``len(workspace.papers)`` (after dedup). The user wanted
this; their previous "less is possible" comment was about
the upper-bound invariant ("don't cite papers NOT in
INTERMEDIATE"), not about the lower bound. After seeing the
discrepancy between workspace count and report count, they
want the lower bound too: every paper available at
INTERMEDIATE is in the report.
