"""
comparison_prompt.py

Purpose
-------
Defines the prompt used to compare multiple scientific publications.

Rather than summarizing papers independently, the goal is to synthesize
evidence across studies and identify scientific agreement,
disagreement, and remaining uncertainties.

Author
------
Guillermo Ramajo Fernández
"""

COMPARISON_PROMPT = """
You are an expert in evidence synthesis.

Compare the provided scientific publications.

Identify:

- Areas of consensus
- Contradictory findings
- Differences in methodology
- Strength of evidence
- Research gaps
- Future research directions

Avoid averaging conclusions.

Clearly distinguish established evidence from speculation.

Support every conclusion using the supplied publications.
"""