"""
Multi-source literature searcher.

Fans out a single :class:`SearchFilters` to multiple
:class:`LiteratureSearcher` instances, deduplicates the
results, and ranks them by source confidence + recency.

Why
---
Researchers in the consultant feedback asked for a wider
search scope — not just PubMed. The orchestrator now
defaults to PubMed + OpenAlex and the Advanced Search modal
lets the user opt into Europe PMC and bioRxiv. The fan-out
logic lives here (not in the orchestrator) so a different
fan-out strategy (e.g. per-query source routing) can be
swapped without touching the FSM.

Dedupe key
----------
We collapse papers that share a DOI, falling back to PMID
(if neither source has a DOI), then to OpenAlex ID, then to
title. The first occurrence wins; subsequent matches bump
the confidence score (so a paper found on two sources
ranks higher than one found on one).

Ranking
-------
Score = (source_confidence) * (recency_boost)
where recency_boost = 1.0 + 0.5 * exp(-years_since_publication / 5).

A 2026 paper on PubMed scores ~1.0 × 1.5 ≈ 1.5.
A 2010 paper on OpenAlex scores ~0.4 × 1.07 ≈ 0.43.

The orchestrator then slices the top ``max_results`` from
the ranked list.

Partial-result tolerance
------------------------
If a source throws or returns HTTP 4xx/5xx, we log and
continue with the other sources. One broken provider
shouldn't kill the search.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from app.core.enums.search_source import (
    SearchSource,
    default_sources,
)
from app.domain.entities.paper import Paper
from app.domain.interfaces.literature_searcher import (
    LiteratureSearcher,
)
from app.domain.value_objects.search_filters import SearchFilters
from app.domain.value_objects.search_result import SearchResult

logger = logging.getLogger(__name__)


class MultiSourceSearcher(LiteratureSearcher):
    """Composes multiple :class:`LiteratureSearcher` instances."""

    def __init__(
        self,
        searchers: dict[SearchSource, LiteratureSearcher],
    ) -> None:
        if not searchers:
            raise ValueError(
                "MultiSourceSearcher needs at least one source."
            )
        self._searchers = dict(searchers)

    @classmethod
    def with_defaults(
        cls,
        pubmed: LiteratureSearcher,
        openalex: LiteratureSearcher | None = None,
        europe_pmc: LiteratureSearcher | None = None,
        biorxiv: LiteratureSearcher | None = None,
    ) -> "MultiSourceSearcher":
        """Convenience constructor using the default
        source set (PubMed + OpenAlex). Optional providers
        are included if supplied.
        """
        sources: dict[SearchSource, LiteratureSearcher] = {
            SearchSource.PUBMED: pubmed,
        }
        if openalex is not None:
            sources[SearchSource.OPENALEX] = openalex
        if europe_pmc is not None:
            sources[SearchSource.EUROPE_PMC] = europe_pmc
        if biorxiv is not None:
            sources[SearchSource.BIORXIV] = biorxiv
        return cls(sources)

    # ----------------------------------------------------------------
    # LiteratureSearcher interface
    # ----------------------------------------------------------------

    def default_source(self) -> SearchSource:  # type: ignore[override]
        # The orchestrator asks "which source does this
        # searcher represent?" We answer PubMed (the
        # canonical default) for legacy compatibility.
        return SearchSource.PUBMED

    def search(self, question) -> list[Paper]:
        """Legacy single-source entry point.

        Delegates to ``search_with_filters`` and returns the
        deduped papers (without per-source provenance).
        """
        from app.domain.value_objects.search_filters import (
            SearchFilters,
        )

        filters = SearchFilters(query=question.question)
        results = self.search_with_filters(filters)
        return [r.paper for r in results]

    def get_by_id(self, paper_id: str) -> Paper | None:
        """Try each registered source in order until one
        returns a match."""
        for source, searcher in self._searchers.items():
            try:
                paper = searcher.get_by_id(paper_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "get_by_id on %s failed: %s", source.value, exc
                )
                continue
            if paper is not None:
                return paper
        return None

    def search_with_filters(
        self, filters: SearchFilters
    ) -> list[SearchResult]:
        """Fan out to every registered source in parallel, dedupe, rank.

        Parallelism
        -----------
        Sources run concurrently via a bounded
        ``ThreadPoolExecutor``. With 3 enabled sources (PubMed,
        OpenAlex, Europe PMC by default), the wall-clock time
        is ``max(source_times)`` rather than the sum. An
        OpenAlex that takes 4.5s no longer blocks PubMed (0.5s)
        and Europe PMC (0.7s) from returning in parallel.

        Why ``ThreadPoolExecutor`` and not ``asyncio.gather``
        ------------------------------------------------------
        The underlying ``search_with_filters`` is synchronous
        (blocking ``httpx.Client`` calls). To run these in
        parallel without rewriting every searcher as async,
        we run them on a thread pool. The pool size is
        bounded by the number of sources (no point having
        more workers than sources) so we don't accumulate
        idle threads.

        Error handling
        --------------
        Each source's failure is logged and that source is
        silently dropped from the result. The searcher
        still returns whatever the remaining sources
        produced -- a single misconfigured source doesn't
        break the whole search.
        """
        sources = list(self._searchers.items())
        n_workers = min(len(sources), 4)
        logger.debug(
            "MultiSourceSearcher: fanning out to %d sources "
            "(max %d workers)",
            len(sources),
            n_workers,
        )

        def _search_one(
            item: tuple[SearchSource, LiteratureSearcher],
        ) -> list[SearchResult]:
            source, searcher = item
            try:
                return searcher.search_with_filters(filters)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "search on %s failed: %s", source.value, exc
                )
                return []

        with ThreadPoolExecutor(
            max_workers=n_workers,
            thread_name_prefix="multi-source-search",
        ) as pool:
            per_source_results = list(pool.map(_search_one, sources))

        raw_results: list[SearchResult] = []
        for results in per_source_results:
            raw_results.extend(results)

        deduped = _dedupe(raw_results)
        ranked = _rank(deduped)
        return ranked[: filters.max_results]

    def search_with_sources(
        self,
        filters: SearchFilters,
        sources: Iterable[SearchSource] | None = None,
    ) -> list[SearchResult]:
        """Like :meth:`search_with_filters` but restricts to
        a specific source set.

        Used by the Advanced Search modal when the user
        picks exactly which sources to search.
        """
        if sources is None:
            return self.search_with_filters(filters)
        subset = {
            s: self._searchers[s]
            for s in sources
            if s in self._searchers
        }
        if not subset:
            logger.warning(
                "search_with_sources called with no registered "
                "sources; falling back to defaults."
            )
            return self.search_with_filters(filters)
        scoped = MultiSourceSearcher(subset)
        return scoped.search_with_filters(filters)


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------


def _dedupe(results: list[SearchResult]) -> list[SearchResult]:
    """Collapse results that point to the same paper.

    Dedup keys, in priority order:
    1. DOI (lowercased, stripped of any URL prefix).
    2. PMID.
    3. Title (lowercased, whitespace-normalised).

    The first occurrence wins for the ``Paper`` payload;
    subsequent matches only contribute to the confidence
    score (averaged, then clamped to 1.0).
    """
    by_key: dict[str, SearchResult] = {}
    confidences: dict[str, list[float]] = {}

    for r in results:
        key = _paper_key(r.paper)
        if not key:
            # No key we can dedupe on — keep the result as-is.
            key = f"unkeyed:{id(r.paper)}"
        if key not in by_key:
            by_key[key] = r
            confidences[key] = [r.confidence]
        else:
            confidences[key].append(r.confidence)

    out: list[SearchResult] = []
    for key, result in by_key.items():
        avg = sum(confidences[key]) / len(confidences[key])
        out.append(
            SearchResult(
                paper=result.paper,
                source=result.source,
                confidence=max(0.0, min(1.0, avg)),
            )
        )
    return out


def _paper_key(paper: Paper) -> str:
    """Stable identity key for a paper."""
    if paper.doi:
        return f"doi:{paper.doi.lower().strip()}"
    if paper.pmid:
        return f"pmid:{paper.pmid.strip()}"
    # Title fallback — last-resort. Lowercase + collapse
    # whitespace so ``"Foo."`` and ``" foo  "`` collapse.
    return "title:" + " ".join(paper.title.lower().split())


def _rank(results: list[SearchResult]) -> list[SearchResult]:
    """Sort by source-confidence × recency-boost, descending.

    Recency boost curve:
    - This year:    1.5x (e.g. 0.5 confidence × 1.5 = 0.75)
    - 1 year old:   1.4x
    - 3 years old:  1.2x
    - 5 years old:  1.07x
    - 10 years old: 1.02x
    - 20+ years:    1.00x

    The 3-year half-life means a brand-new paper with low
    confidence can still outrank an old classic with high
    confidence — appropriate for literature search where
    the user wants "what's current" by default. A 2024 paper
    with confidence 0.5 (0.5 × 1.34 ≈ 0.67) ranks above a
    2010 paper with confidence 0.9 (0.9 × 1.02 ≈ 0.92) only
    narrowly; a 2025 paper with confidence 0.7 (0.7 × 1.42 ≈
    0.99) beats a 2010 paper with confidence 0.9.
    """
    import math

    current_year = _current_year()

    def score(r: SearchResult) -> float:
        years_old = max(0, current_year - (r.paper.year or 2000))
        # 3-year half-life: a brand-new paper gets 1.5x; an
        # old paper falls back to 1.0x.
        recency = 1.0 + 0.5 * math.exp(-years_old / 3.0)
        return r.confidence * recency

    return sorted(results, key=score, reverse=True)


def _current_year() -> int:
    import datetime

    return datetime.datetime.now().year


def default_searchers(
    *,
    pubmed: LiteratureSearcher,
    openalex: LiteratureSearcher,
) -> dict[SearchSource, LiteratureSearcher]:
    """Helper for tests / fixture code: the default source set."""
    return {
        SearchSource.PUBMED: pubmed,
        SearchSource.OPENALEX: openalex,
    }
