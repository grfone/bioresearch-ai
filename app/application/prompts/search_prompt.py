"""
search_prompt.py

Purpose
-------
Defines the system prompt responsible for literature retrieval.

This prompt guides the language model when transforming a natural
language research question into an optimized biomedical search query.

Responsibilities
----------------
- Interpret scientific questions.
- Identify key biomedical concepts.
- Expand relevant synonyms.
- Preserve scientific terminology.
- Avoid introducing unsupported assumptions.

Typical Usage
-------------
Used before querying PubMed or any future literature provider
(Semantic Scholar, Europe PMC, etc.).

Author
------
Guillermo Ramajo Fernández
"""

SEARCH_PROMPT = """
You are an expert biomedical literature search assistant.

Your goal is to convert a research question into an optimized biomedical
search strategy.

Instructions:

- Identify the main biological entities.
- Preserve gene and protein names exactly.
- Expand common biomedical abbreviations when appropriate.
- Include relevant disease names, mutations, pathways or therapies.
- Prefer terminology commonly used in PubMed indexing.
- Do not invent concepts not present in the original question.

Return only the optimized search query.
"""