"""
search_result.py

``SearchResult`` value object — a paper returned by one
specific source, with the source tag attached.

Why track source on the result?
--------------------------------
- The orchestrator dedupes papers across sources. Two
  papers from PubMed and OpenAlex about the same work
  collapse into one ``Paper`` (DOI is the primary key);
  but the deduper needs to know which source each
  candidate came from to rank by relevance (PubMed
  citations are usually stronger for clinical queries).
- The UI shows source provenance per paper (small badge
  in the PaperCard).
- For future metrics: count hits per source to learn which
  provider is best for which query shape.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums.search_source import SearchSource
from app.domain.entities.paper import Paper


@dataclass(frozen=True)
class SearchResult:
    """A paper returned by a specific literature source.

    ``confidence`` is the source's relevance score (0.0-1.0)
    if it exposes one (OpenAlex, Europe PMC); otherwise
    the provider assigns 0.5 by default. The orchestrator
    uses confidence to rank results across sources.
    """

    paper: Paper
    source: SearchSource
    confidence: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
