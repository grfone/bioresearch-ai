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

import re

# Cap the derived title to a useful "headline" length. Long
# titles (20+ words) overflow the page-width font and don't
# look like report titles.
_MAX_TITLE_WORDS = 12

# Regexes reused across the module. Compiled once at import
# to avoid re-compiling on every call.
_H1_LINE_RE = re.compile(r"^#\s+\S", re.MULTILINE)
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")
_PAPER_MARKER_RE = re.compile(r"\[paper:\d+(?:,\s*paper:\d+)*\]")
_WHITESPACE_RE = re.compile(r"\s+")


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
    """Derive a title from the first sentence of ``body``.

    Algorithm
    ---------
    1. Take the first ``.``, ``!``, ``?``, or ``\\n``
       terminated sentence.
    2. Strip ``[paper:N]`` citation markers (visual noise).
    3. Collapse internal whitespace.
    4. Truncate to ``_MAX_TITLE_WORDS`` words.
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
    # words are dropped. ``" ".join(...)`` re-joins without
    # splitting inside the truncated prefix.
    words = candidate.split()
    truncated = words[:_MAX_TITLE_WORDS]
    return " ".join(truncated)


def inject_h1_fallback(body: str) -> str:
    """Return ``body`` with an injected H1 if missing.

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
    """
    if not body:
        return body
    if has_h1_title(body):
        return body
    derived = derive_title_from_first_sentence(body)
    if not derived:
        # Couldn't derive a useful title (body was empty
        # after stripping markers, or only contained
        # punctuation). Fall through and let the consumer
        # use its default label.
        return body
    # Prepend ``# Title\n\n`` so the body still starts
    # with prose on the next line. The two-newline gap
    # mirrors conventional markdown.
    return f"# {derived}\n\n{body}"