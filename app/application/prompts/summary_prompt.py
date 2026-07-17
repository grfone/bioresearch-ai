"""
summary_prompt.py

Purpose
-------
Defines the prompt used to summarize a single scientific publication.

The generated summary should remain faithful to the source publication
and avoid unsupported conclusions.

Responsibilities
----------------
- Summarize objectives.
- Describe methodology.
- Highlight key findings.
- Mention limitations.
- Explain potential clinical relevance.

Author
------
Guillermo Ramajo Fernández
"""

SUMMARY_PROMPT = """
You are an expert biomedical researcher.

Summarize the following scientific paper.

Your summary should include:

1. Objective
2. Methodology
3. Main findings
4. Biological significance
5. Clinical relevance
6. Study limitations

Never hallucinate information.

If information is missing, explicitly state that it is not available.

Use concise scientific language.
"""