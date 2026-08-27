"""
citation_sanitizer.py

Sanitises raw LLM output by stripping ``[paper:N]`` markers
that reference papers not in the supplied bibliography.

Background
----------
The Vancouver / ICMJE in-text citation convention requires the
LLM to emit markers like ``[paper:5]`` and ``[paper:5, paper:12]``
inline at sentence ends. The LLM is given the size of the
bibliography in the prompt, but in practice LLMs sometimes
hallucinate indices past the bibliography length (``[paper:19]``
when the bibliography only has 17 entries). This is a known LLM
failure mode -- the model "imagines" citing a paper that isn't
in the bibliography.

Why sanitize at ingest (not at render)
--------------------------------------
Sanitising at the LLM output boundary (right after
``provider.generate()`` returns) keeps the cleaned text in
persistent storage. The frontend linkifier still has its
defence-in-depth silent-drop policy for any marker that
slips past, but most cases are caught here. The contract:

  - Standalone ``[paper:N]`` with ``N > len(papers)``:
    silently dropped. Returns the surrounding prose
    unmodified (the marker is simply removed).

  - Grouped ``[paper:N, paper:M]``: each entry is checked
    independently. Valid entries are preserved in the
    canonical ``[paper:N, paper:M, ...]`` form (which
    ``report_mapper._build_citations`` then extracts via
    regex); invalid entries are silently dropped. The
    canonical form normalises the first element (which
    by regex construction has no ``paper:`` prefix) to
    match the rest of the group.

    Note: the sanitizer does NOT convert in-range entries
    to markdown links (``[N](#citation-N)``) -- that's the
    Frontend ``linkifyCitationMarkers`` job. Doing both
    would duplicate work and the Backend form
    ``[paper:N, paper:M]`` is what the report mapper's
    regex expects.

  - All-group-invalid: fall back to the original text.
    We don't want to silently erase the user's context if
    nothing useful can be rendered. (Frontend's
    ``linkifyCitationMarkers`` applies the same policy.)

  - Malformed markers (``[paper:]``, ``[paper:abc]``): pass
    through unchanged. They're not parseable as numbers
    and the regex never matches them.

Why the LLM error is logged
--------------------------
Out-of-range markers indicate the LLM hallucinated a citation.
We log a warning so developers see the data-quality issue
in the backend logs -- they can investigate whether the
prompt needs adjustment, whether the model needs a
temperature tweak, or whether the citation extraction
pipeline itself is producing the wrong count.

This module is intentionally stdlib-only (re, logging).
No new deps.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# Match a standalone ``[paper:N]`` marker. Requires a digit
# sequence (one or more digits) followed by ``]`` so we don't
# match the empty ``[paper:]`` form.
_STANDALONE_RE = re.compile(r"\[paper:(\d+)\]")
# Match a grouped ``[paper:N, paper:M, ...]`` marker. The
# capture group is the entire comma-joined number list (e.g.
# ``"5, paper:12, paper:17"``).
_GROUPED_RE = re.compile(r"\[paper:(\d+(?:,\s*paper:\d+)+)\]")


def sanitize_citation_markers(
    text: str,
    bibliography_size: int,
    *,
    logger_: Optional[logging.Logger] = None,
) -> str:
    """Strip ``[paper:N]`` markers with out-of-range N.

    Parameters
    ----------
    text : str
        Raw LLM output (synthesis or report body).
    bibliography_size : int
        Number of papers in the bibliography. Markers
        ``[paper:K]`` with ``K > bibliography_size`` (or
        ``K < 1``) are dropped as hallucinated indices.
    logger_ : logging.Logger, optional
        Logger for warning output. Defaults to this module's
        logger. Pass an explicit logger in tests for
        assertion-friendliness.

    Returns
    -------
    str
        ``text`` with out-of-range markers removed. In-range
        markers are preserved verbatim -- they're consumed
        by the downstream ``report_mapper`` regex to build
        the citation list. Out-of-range markers in the
        rendered page would be invisible artefacts to the
        user; sanitising at ingest keeps the persistent
        storage clean.

    Notes
    -----
    This function is a thin shim around the regex above. We
    keep it here (rather than inlining at the call sites) so
    the policy is in one place -- the summarizer and the
    report generator both call it, and a future change to
    the rule (e.g. "rewrite to closest valid index" instead
    of "drop") is a single-file edit.
    """
    log = logger_ if logger_ is not None else logger

    if not text:
        return text

    # Track how many hallucinated markers we stripped. We
    # log this as a single warning per call so a developer
    # watching the logs can see whether the LLM is
    # systematically hallucinating (a recurring warning
    # across calls) vs an isolated glitch (a one-off).
    hallucinated_count = 0

    def _is_in_range(index: int) -> bool:
        nonlocal hallucinated_count
        valid = 1 <= index <= bibliography_size
        if not valid:
            hallucinated_count += 1
        return valid

    # Process grouped citations first so the inner
    # ``[paper:N]`` tokens can't be picked up by the
    # standalone pass.
    sanitized = _GROUPED_RE.sub(
        lambda m: _process_grouped(m, _is_in_range),
        text,
    )
    # Then the standalone markers.
    sanitized = _STANDALONE_RE.sub(
        lambda m: _process_standalone(m, _is_in_range),
        sanitized,
    )

    if hallucinated_count > 0:
        log.warning(
            "citation_sanitizer: dropped %d hallucinated citation "
            "marker(s) from LLM output (bibliography size=%d). The "
            "LLM emitted [paper:N] with N > %d. This is a data-"
            "quality signal -- review the upstream prompt if "
            "this recurs.",
            hallucinated_count,
            bibliography_size,
            bibliography_size,
        )

    return sanitized


def _process_standalone(m: re.Match, is_in_range) -> str:
    index = int(m.group(1))
    if is_in_range(index):
        # In range -- preserve verbatim. The downstream
        # ``report_mapper`` regex consumes this marker.
        return m.group(0)
    # Out of range -- silently drop. Returning an empty
    # string collapses the bracket to nothing, so the user
    # just sees the surrounding prose without the broken
    # marker.
    return ""


def _process_grouped(m: re.Match, is_in_range) -> str:
    pieces = m.group(1).split(",")
    rendered: list[int] = []
    for piece in pieces:
        # Don't strip -- whitespace is significant because
        # the regex capture group ``\d+(?:,\s*paper:\d+)+``
        # captures the first element with no space prefix
        # and subsequent elements with a space. We strip
        # only after we've confirmed the piece is parseable
        # so we can reconstruct the canonical form.
        pm = re.match(r"\s*(?:paper:)?(\d+)\s*", piece)
        if not pm:
            # Malformed piece -- skip silently.
            continue
        index = int(pm.group(1))
        if not is_in_range(index):
            # Out of range -- skip silently.
            continue
        # In range: keep the index. We rebuild the marker
        # canonically below (``[paper:N, paper:M, ...]``).
        rendered.append(index)
    # If every entry was invalid or malformed, fall back to
    # the original text rather than silently erase it.
    if not rendered:
        return m.group(0)
    # Reconstruct in canonical form: first element as
    # ``[paper:N`` and subsequent elements joined by
    # ``, paper:``. We deliberately don't try to round-trip
    # the LLM's original whitespace inside the marker
    # (commas vs. ``", "``); the canonical form is what
    # the rest of the pipeline expects.
    return "[paper:" + ", paper:".join(str(i) for i in rendered) + "]"
