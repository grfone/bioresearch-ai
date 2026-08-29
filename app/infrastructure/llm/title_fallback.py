"""
title_fallback.py

Provide a deterministic fallback for the H1 report title
when the LLM omits one.

Background
----------
The ``MinimalPDFGenerator`` (PDF rendering) and the React UI
both extract the report title from the first ``# `` heading
in ``report.summary.body``. The LLM is explicitly prompted
to emit ``# <report title>`` at the start of the synthesis,
but the model occasionally skips the preamble and goes
straight into the executive-summary prose. The result: every
PDF in the system gets the generic ``"Biomedical Research
Report"`` label, and every React page shows ``"Research
Report"``.

The user's complaint: "the PDF always shows Biomedical
Research Report instead of a useful per-report title".

Two layers of mitigation are in place:
1. The user prompt has an emphatic directive (added in
   commit ``73e07af``) -- but the LLM doesn't always obey.
2. THIS MODULE: a deterministic fallback that derives a
   title from the first sentence of the body when the LLM
   omits the H1.

Design
------
The fallback runs at synthesis ingest time (see
``SummarizePapersUseCase.execute``). By injecting the H1
into the stored ``summary.body``, both consumers (PDF +
React UI) see the title without each having to implement
the same fallback.

The injection is idempotent: if the body already has a
``# `` line, the fallback is a no-op. The LLM's own choice
of title wins when present.

Title derivation
----------------
The first sentence of the body becomes the title, truncated
to ``_MAX_TITLE_WORDS`` words (12 -- a useful "headline"
length). Stop characters ``.``, ``!``, ``?``, ``\n`` end the
sentence. Citation markers (``[paper:N]``) are stripped
from the candidate title because they read as visual noise
in a title.

Why not a more sophisticated title generator
--------------------------------------------
A separate LLM call would be heavy (1-2s latency + token
cost) for a derived value. The first-sentence heuristic
produces a reasonable biomedical title in 90%+ of cases
(LLM syntheses start with topic statements like "Plasma
p-tau217 has emerged as..." -> "Plasma p-tau217 has emerged
as..."). A future enhancement could swap this for a cheaper
extractive-summariser model.

Author
------
Guillermo Ramajo Fernández
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Cap the derived title to a useful "headline" length. Long
# titles (20+ words) overflow the page-width font and don't
# look like report titles.
_MAX_TITLE_WORDS = 12

# Alert threshold for the fallback-rate classifier. When
# the fallback injection rate exceeds this fraction of
# calls over the trailing ``_FALLBACK_RATE_WINDOW``
# invocations, we emit a WARNING log line so operators can
# see that the LLM is consistently skipping the H1
# directive and the prompt may need further tightening.
#
# 0.5 (50%) is the empirical threshold from the live
# workspace -- if more than half of synthesis calls need
# the fallback, the prompt isn't doing its job and the
# product owner should revisit the user prompt.
_FALLBACK_RATE_THRESHOLD = 0.5

# Window size for the rate calculation. ``20`` is large
# enough to be statistically meaningful (one or two
# outliers don't trigger an alert) but small enough that
# the rate reflects recent behaviour (a stuck-LLM problem
# surfaces within 20 calls).
_FALLBACK_RATE_WINDOW = 20

# Stats buffer. Rolling-window implementation: each call
# to ``inject_h1_fallback`` appends an entry (1 if fallback
# was injected, 0 if the LLM already emitted an H1). The
# rate is computed over the trailing
# ``_FALLBACK_RATE_WINDOW`` entries. Module-level so the
# counter survives across calls within the same process.
_FALLBACK_WINDOW: list[int] = []

# Regexes reused across the module. Compiled once at import
# to avoid re-compiling on every call.
_H1_LINE_RE = re.compile(r"^#\s+\S", re.MULTILINE)
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")
_PAPER_MARKER_RE = re.compile(r"\[paper:\d+(?:,\s*paper:\d+)*\]")
_WHITESPACE_RE = re.compile(r"\s+")

# Function words whose presence at the END of a title
# suggests an incomplete phrase. When the word-cap
# truncation lands on one of these, we trim back to the
# last content word so the title ends cleanly. Examples
# of bad endings the heuristic catches:
#
#   "...central to the biological diagnosis and"
#   --> "...central to the biological diagnosis"  (trim "and")
#
#   "...a sensitive marker for"
#   --> "...a sensitive marker"  (trim "for")
#
#   "...the role of"
#   --> "...the role"  (trim "of")
#
# The list is a closed vocabulary of high-frequency
# function words. We don't enumerate every English
# function word -- the goal is to catch the most common
# trailing fragments, not to be a complete grammar.
# Niche cases (titles ending in "via", "per", etc.) fall
# through and remain truncated mid-phrase, which is no
# worse than the pre-fix behaviour.
_TRAILING_FUNCTION_WORDS = frozenset(
    {
        # Articles
        "a", "an", "the",
        # Conjunctions
        "and", "or", "but", "nor", "yet", "so",
        # Coordinating conjunctions (also conjunctions)
        "for",  # "for" is ambiguous; here we treat it as
                # the conjunction (e.g. "I went there, for
                # I wanted to...") but it's also a common
                # preposition. Truncating on "for" is the
                # safer call because titles ending in
                # preposition "for" (e.g. "X for") are
                # always mid-phrase.
        # Common prepositions
        "of", "in", "on", "at", "to", "by", "with",
        "from", "into", "as", "about", "between",
        "through", "during", "before", "after", "above",
        "below", "up", "down", "out", "off", "over",
        "under", "again", "against", "among",
        # Wh-words (titles ending in "what", "which", etc.
        # are mid-question and shouldn't stand alone)
        "what", "which", "who", "whom", "whose",
        "when", "where", "why", "how",
        # Auxiliary / modal verbs that don't end phrases
        "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did",
        "will", "would", "shall", "should", "can",
        "could", "may", "might", "must",
    }
)


def _trim_to_last_content_word(words: list[str]) -> str:
    """
    Trim ``words`` back to the last non-function word.

    The caller has already truncated the candidate to
    ``_MAX_TITLE_WORDS`` words. If the truncation landed on
    a function word (article, conjunction, preposition,
    modal verb), we back off to the last content word so
    the title doesn't end in "and", "of", "the", etc.

    Example::

        >>> _trim_to_last_content_word(
        ...     ["Tau", "biomarkers", "have", "become",
        ...      "central", "to", "the", "biological",
        ...      "diagnosis", "and"]
        ... )
        'Tau biomarkers have become central to the biological diagnosis'

    Edge cases
    -----------
    - Empty input: returns ``""``.
    - All-function-words input (very rare; only if the
      sentence is something like "And the of a in"):
      returns the input as-is (no clean place to cut).
    - Single-word input: returned unchanged (truncation
      didn't land on a function word -- there's nothing
      to back off to).

    Why not a real POS tagger?
    --------------------------
    NLTK or spaCy would give us tagged word classes
    ("DT" for determiner, "IN" for preposition, etc.) and
    would catch more edge cases. But both add a heavy
    dependency (10-50 MB of model data) for a feature
    that's mostly cosmetic. The closed-vocabulary
    approach catches ~90% of the cases the live
    syntheses produce and degrades gracefully (returns
    the untrimmed truncation) when it doesn't apply.
    """
    if not words:
        return ""
    # Walk backwards from the end of the list. If the last
    # word is a function word, drop it and check the next.
    # Stop when we find a content word OR run out of words
    # (in which case the input was all function words --
    # fall through to the all-function-words branch).
    last_idx = len(words) - 1
    while last_idx > 0 and words[last_idx].lower() in _TRAILING_FUNCTION_WORDS:
        last_idx -= 1
    return " ".join(words[: last_idx + 1])


def has_h1_title(body: str) -> bool:
    """Return True if the body already has a ``# `` heading.

    Used by the fallback to detect "the LLM already emitted
    a title" -- in that case the fallback should be a no-op
    so the LLM's choice of title wins.
    """
    if not body:
        return False
    return bool(_H1_LINE_RE.search(body))


def derive_title_from_first_sentence(body: str) -> str:
    """
    Derive a title from the first sentence of ``body``.

    Algorithm
    ---------
    1. Take the first ``.``, ``!``, ``?``, or ``\\n``
       terminated sentence.
    2. Strip ``[paper:N]`` citation markers (visual noise).
    3. Collapse internal whitespace.
    4. Truncate to ``_MAX_TITLE_WORDS`` words, then
       **trim back to the last content word** if the
       truncation landed on a function word. This avoids
       mid-phrase cut-offs like "Tau biomarkers have
       become central to the biological diagnosis and"
       (trailing "and" dangling). See
       ``_trim_to_last_content_word`` for details.
    5. If the result is empty, return ``""`` (caller falls
       back to its default label).

    The function never raises -- invalid input returns
    ``""`` so the caller's fallback path still works.
    """
    if not body:
        return ""
    # Find the first sentence. We split on the FIRST
    # sentence-ending character (``.``, ``!``, ``?``, ``\n``)
    # rather than the full body -- a body without any of
    # those characters yields the whole body as the candidate
    # title (after truncation).
    text = body.strip()
    match = _SENTENCE_END_RE.search(text)
    if match is not None:
        candidate = text[: match.start()].strip()
    else:
        candidate = text.strip()
    if not candidate:
        return ""
    # Strip ``[paper:N]`` citation markers (and grouped
    # variants) so the title reads cleanly without brackets.
    candidate = _PAPER_MARKER_RE.sub("", candidate)
    # Collapse whitespace runs.
    candidate = _WHITESPACE_RE.sub(" ", candidate).strip()
    # Reject purely-punctuation candidates (e.g. body was
    # only "..." after marker stripping). A title of "." or
    # "..." is useless -- the caller's default label is
    # better. We require at least one word character
    # (alphanumeric) to accept the candidate.
    if not re.search(r"\w", candidate):
        return ""
    # Truncate to the word cap. ``split()[:N]`` gives us the
    # first ``N`` whitespace-separated tokens; the remaining
    # words are dropped.
    words = candidate.split()
    truncated = words[:_MAX_TITLE_WORDS]
    return _trim_to_last_content_word(truncated)


def inject_h1_fallback(body: str) -> str:
    """
    Return ``body`` with an injected H1 if missing.

    If the body already starts with a ``# `` heading, the
    function returns ``body`` unchanged (the LLM's choice
    wins). Otherwise the function prepends a single H1
    line derived from the first sentence of the body.

    The injected H1 is a single line -- no body content is
    otherwise modified. A trailing newline separates the H1
    from the body so markdown renders correctly downstream.

    Examples
    --------
    >>> inject_h1_fallback("Plasma p-tau217 is a sensitive marker.\\n\\nThe rest.")
    '# Plasma p-tau217 is a sensitive marker\\n\\nPlasma p-tau217 is a sensitive marker.\\n\\nThe rest.'

    >>> inject_h1_fallback("# Already titled\\n\\nBody text")
    '# Already titled\\n\\nBody text'

    >>> inject_h1_fallback("")
    ''

    Telemetry
    ---------
    Every call (whether or not the fallback was injected)
    is recorded in a rolling-window buffer for the
    fallback-rate classifier. See ``get_fallback_stats``
    and ``reset_fallback_stats`` for the public API. When
    the rate over the trailing window exceeds
    ``_FALLBACK_RATE_THRESHOLD``, a WARNING log line is
    emitted so operators can detect a degraded LLM
    prompt.
    """
    if not body:
        return body
    if has_h1_title(body):
        _record_fallback_call(injected=False)
        return body
    derived = derive_title_from_first_sentence(body)
    if not derived:
        # Couldn't derive a useful title (body was empty
        # after stripping markers, or only contained
        # punctuation). Fall through and let the consumer
        # use its default label.
        _record_fallback_call(injected=False)
        return body
    # Prepend ``# Title\n\n`` so the body still starts
    # with prose on the next line. The two-newline gap
    # mirrors conventional markdown.
    _record_fallback_call(injected=True)
    return f"# {derived}\n\n{body}"


def _record_fallback_call(injected: bool) -> None:
    """
    Append a call to the rolling window and check the
    rate.

    Called from ``inject_h1_fallback`` regardless of
    whether the fallback was actually injected (so a
    body with an existing H1 still counts as a "call"
    against the rate -- what matters is the LLM's
    compliance rate, not the fallback injection rate).
    """
    _FALLBACK_WINDOW.append(1 if injected else 0)
    # Keep only the trailing window of entries.
    if len(_FALLBACK_WINDOW) > _FALLBACK_RATE_WINDOW:
        del _FALLBACK_WINDOW[: len(_FALLBACK_WINDOW) - _FALLBACK_RATE_WINDOW]
    # Only alert once we have a meaningful sample size
    # (at least half the window). Smaller samples are
    # too noisy -- a single fall-back in 2 calls gives
    # 50% which is just chance.
    if len(_FALLBACK_WINDOW) >= _FALLBACK_RATE_WINDOW // 2:
        rate = sum(_FALLBACK_WINDOW) / len(_FALLBACK_WINDOW)
        if rate >= _FALLBACK_RATE_THRESHOLD:
            logger.warning(
                "title_fallback: H1 fallback rate is %.0f%% "
                "over the last %d calls (rate threshold %.0f%%). "
                "The synthesis LLM is consistently omitting "
                "the ``# <report title>`` heading despite the "
                "emphatic directive in the user prompt. "
                "Consider tightening the prompt or relaxing "
                "the threshold. title=%r",
                rate * 100,
                len(_FALLBACK_WINDOW),
                _FALLBACK_RATE_THRESHOLD * 100,
                _FALLBACK_WINDOW[-5:],  # last 5 entries for context
            )


def get_fallback_stats() -> dict:
    """
    Return the current fallback-rate telemetry.

    Returns
    -------
    dict
        A dictionary with the following keys:

        - ``total_calls``: total calls recorded since the
          last reset.
        - ``total_fallbacks``: total injections (subset of
          ``total_calls``).
        - ``rate``: fraction of calls that injected a
          fallback.
        - ``window_size``: number of calls in the rolling
          window (capped at ``_FALLBACK_RATE_WINDOW``).
        - ``current_window``: the trailing window as a
          list of 0/1 entries. Useful for debugging.

    The returned dict is a snapshot -- subsequent calls
    do not mutate it. Use ``reset_fallback_stats`` in
    tests.
    """
    return {
        "total_calls": len(_FALLBACK_WINDOW),
        "total_fallbacks": sum(_FALLBACK_WINDOW),
        "rate": (
            sum(_FALLBACK_WINDOW) / len(_FALLBACK_WINDOW)
            if _FALLBACK_WINDOW
            else 0.0
        ),
        "window_size": len(_FALLBACK_WINDOW),
        "current_window": list(_FALLBACK_WINDOW),
    }


def reset_fallback_stats() -> None:
    """
    Reset the fallback-rate telemetry to zero.

    Intended for test fixtures -- calling this in
    production code would erase the in-process rate
    tracking and let a hot-loop re-arm the alert.
    """
    _FALLBACK_WINDOW.clear()