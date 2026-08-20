# ADR-004: Section-based abstract extraction (preferred over meta tags)

## Status

Accepted

## Context

The abstract-enricher (`app/infrastructure/pubmed/abstract_enricher.py`)
is a fallback in the DOI resolution chain: when CrossRef and
OpenAlex both fail to return an abstract, the resolver fetches the
publisher's HTML landing page and scrapes the abstract out of it.

Historically the enricher only matched `<meta>` tags —
`citation_abstract`, `description`, `og:description` — because
those are the W3C- and HighWire-standardized surfaces and most
publishers populate them. The matching regexes were deliberately
permissive about attribute order and quote style so PLOS,
Frontiers, Royal Society, PNAS, and Oxford Academic all worked.

The bug we hit: Springer's landing page **does** populate
`<meta name="description">` but only with a short **teaser** that
ends in literal `"..."` — Springer's publisher convention is "see
the page for more". The teaser for `10.1007/978-3-031-64636-2_17`
is 267 chars and ends `"...This..."`. The **full** abstract is on
the same page, in `<section aria-labelledby="Abs1"><p>...</p></section>`,
roughly 1100 chars. Our regex never looked at the section, so the
user saw a 267-char truncated abstract with a literal trailing
`"..."` and assumed the system was buggy.

The Springer example is the canonical case but it's not the only
one. Nature, Oxford Academic, and IEEE also put the full abstract
in a labeled section; the meta description is at best a summary
and at worst a literal publisher teaser. Treating the section as
a first-class source — preferred over the meta tags — gives us
the canonical full text in all those cases.

The other half of the bug: even when we fall back to a meta
description that does end in `"..."`, the literal ellipsis
confuses the user (and the React `PaperCard` `Show more` button,
which checks `paper.abstract.length > 200` and so the user can
click it but nothing happens). We should strip the trailing
publisher ellipsis so the abstract reads as complete.

## Decision

Two changes to `app/infrastructure/pubmed/abstract_enricher.py`:

### 1. Section-based extraction (preferred path)

A new regex with three alternatives, tried before the existing
meta-tag regexes:

```
<section id="Abs[0-9]+">...</section>      # Nature, OUP, IEEE
<section aria-labelledby="Abs[0-9]+">...</section>
                                          # Springer Nature
                                          # (id is on the <h2>)
<section data-title="Abstract">...</section>
                                          # generic Springer
                                          # fallback
```

The regex captures the section body (up to 4 KB), then extracts
the **first** `<p>...</p>` block inside it. Subsequent `<p>`s in
a Springer Nature section are typically acknowledgements,
funding statements, or "© ..." paragraphs — not the abstract. Nested
tags inside the `<p>` (e.g. `<i>m/z</i>`, `<sup>2</sup>`) are
stripped to plain text so the result reads uniformly regardless
of whether the source was a section or a meta tag.

The `lastindex` of the multi-alternative pattern tells us which
alternative matched; the body group is always at that position
because each alternative's body group is its last group.

### 2. Trailing-`"..."` strip in `_clean_abstract`

A new step strips a trailing literal `"..."` (with or without
surrounding spaces) from the cleaned abstract, **before** the
40-char minimum-length check. Anchored at end-of-string with
`re.sub(r"\s*\.{3}\s*$", "", normalized)`, so mid-text ellipses
like `Eq. (1) ... (3)` are NOT touched — only publisher-supplied
teasers at the end of the abstract.

The strip is placed before the length check so a Springer-style
abstract like `"This is the abstract. ..."` (29 visible chars
+ 3 dots) doesn't fall below the 40-char floor and return
`""`. The dots are publisher boilerplate, not content.

## Consequences

**Positive**

- Springer's full abstract is recovered. Verified: 10.1007/978-3-
  031-64636-2_17 now returns 1498 chars (was 267). Nature's
  abstract is unchanged at 807 chars (the section-based regex
  matches `<section id="Abs1">` and the body has the same
  content as the meta tag).
- Oxford Academic and IEEE pages (which use `<section
  data-title="Abstract">`) now work without needing a custom
  regex.
- The trailing-`"..."` strip means the user never sees
  `"This..."` as if the abstract is truncated mid-sentence. The
  `Show more` button is also less likely to mislead — when the
  abstract is actually the full text, the button no longer
  appears (the 200-char threshold is still there, but a Springer
  abstract is now long enough that the 3-line clamp is the
  visual cue, not a click-to-expand cue).
- The meta-tag regexes remain as the fallback for publishers
  who use only meta tags (PLOS, Frontiers). No regression.
- The `TestSectionExtraction` test class pins the contract:
  prefers section over meta, falls back to meta when no
  section, returns `None` when neither is present, strips
  nested tags. 7 new tests, all passing.

**Negative**

- The 4 KB cap on the section body is a heuristic. We have not
  found a real abstract longer than that, but if a publisher
  ships a 5 KB abstract inside a labeled section we'd truncate
  the trailing portion. The 40-char minimum-length check would
  still pass, but the abstract would be partial. Mitigation:
  monitor the `AbstractEnricher | section extract length=N`
  log line (added in the same commit) and bump the cap if real
  abstracts start bumping against it.
- The regex's nested-tag strip is naive — it removes every
  `<...>` between the `<p>` open tag and the matching `</p>`.
  If an abstract contains a `<` or `>` character in plain
  text (extremely rare in biomedical literature), the strip
  would misbehave. We use `re.sub(r"<[^>]+>", " ", ...)` which
  is a non-greedy match on the `>` boundary; plain `<` not
  followed by `>` is left alone. The risk is low.
- Three pattern alternatives in one regex make the source
  slightly less readable. We added a long docstring above
  the pattern that documents each alternative's purpose and
  the `lastindex` lookup. Trade-off accepted for keeping all
  three patterns in one place (the `try in order, use the
  first match` semantic).

## Alternatives considered

- **LLM-only fallback** — skip the section-extraction work
  entirely and rely on the LLM extractor (which already does
  page-level extraction) to handle Springer. We have the LLM
  extractor as a third fallback but it's expensive (~3-5s +
  token cost) and the section regex gets the same answer in
  microseconds. LLM is the right tool for genuinely-novel
  HTML; the section regex is the right tool for these
  well-known publisher templates.
- **Publisher-specific templates** — write a per-publisher
  extraction function (`extract_springer`, `extract_nature`,
  `extract_oup`, ...). We rejected this because the three
  patterns above already cover every publisher we tested in
  less than 100 lines of code. Adding a new publisher means
  adding a new pattern alternative, not a new function.
- **Replace the meta-tag regexes entirely** — use the section
  regex as the only path. We rejected this because some
  publishers (PLOS, Frontiers) only populate meta tags and
  don't use a labeled section. The meta-tag fallback is still
  needed; we just demote it below the section regex.

## References

- `app/infrastructure/pubmed/abstract_enricher.py` — the
  regex and the trailing-`"..."` strip.
- `tests/unit/test_abstract_enricher.py` — the
  `TestSectionExtraction` class (7 tests) and
  `TestCleanAbstract` extensions (3 tests).
- The user-reported repro: `10.1007/978-3-031-64636-2_17`.
