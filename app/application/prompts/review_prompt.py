"""
review_prompt.py

Purpose
-------
Defines the prompt used to review AI-generated scientific reports.

This prompt acts as an internal quality assurance step before returning
results to the end user.

Responsibilities
----------------
- Detect hallucinations.
- Verify scientific consistency.
- Assess completeness.
- Evaluate citation support.
- Suggest improvements.

Author
------
Guillermo Ramajo Fernández
"""

REVIEW_PROMPT = """
You are acting as an independent scientific reviewer.

Review the generated report.

Evaluate:

- Scientific accuracy
- Internal consistency
- Citation support
- Possible hallucinations
- Missing evidence
- Confidence of conclusions

Return constructive feedback.

Flag unsupported statements explicitly.
"""