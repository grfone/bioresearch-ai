"""
comparison_prompt.py

Purpose
-------
Defines the prompt used to compare multiple scientific publications.

Rather than summarizing papers independently, the goal is to synthesize
evidence across studies and identify scientific agreement,
disagreement, and remaining uncertainties.

The prompt asks for a structured JSON response so the result can be
parsed deterministically into the domain
:class:`EvidenceComparison`. The JSON schema is documented below.

JSON schema
-----------
::

    {
      "consensus": [
        {
          "claim": "<short factual statement>",
          "paper_ids": ["pmid:12345", "doi:10.1234/..."],
          "evidence_strength": "strong|moderate|weak",
          "notes": "<optional>"
        }
      ],
      "contradictions": [
        {
          "topic": "<short label>",
          "description": "<human-readable description>",
          "paper_ids": ["pmid:..."],
          "severity": "major|minor"
        }
      ],
      "research_gaps": ["..."],
      "future_directions": ["..."],
      "matrix": {
        "columns": ["Methods", "Sample size", "Outcome"],
        "rows": [
          {
            "paper_id": "pmid:12345",
            "Methods": "...",
            "Sample size": "...",
            "Outcome": "..."
          }
        ]
      },
      "confidence": 0.0
    }

Anti-fabrication contract
-------------------------
The prompt explicitly forbids citing papers that are not in the
input set. The :class:`CitationValidator` (in the application
layer) enforces the same invariant on the parsed output.
"""

COMPARISON_PROMPT = """
You are an expert in evidence synthesis for biomedical research.

Compare the provided scientific publications and produce a structured
cross-paper comparison.

Identify:
- Areas of consensus (findings supported by multiple papers)
- Contradictory findings (disagreements between papers)
- Differences in methodology
- Strength of evidence
- Research gaps
- Future research directions

Avoid averaging conclusions. Clearly distinguish established evidence
from speculation. Support every conclusion using the supplied
publications only — NEVER cite a paper that was not in the input
set. If a paper ID is unknown, omit it.

Respond with a JSON object that follows EXACTLY this schema:

{
  "consensus": [
    {
      "claim": "<short factual statement>",
      "paper_ids": ["pmid:12345"],
      "evidence_strength": "strong|moderate|weak",
      "notes": "<optional free-text>"
    }
  ],
  "contradictions": [
    {
      "topic": "<short label>",
      "description": "<human-readable description>",
      "paper_ids": ["pmid:12345"],
      "severity": "major|minor"
    }
  ],
  "research_gaps": ["<open question>"],
  "future_directions": ["<grounded suggestion>"],
  "matrix": {
    "columns": ["Methods", "Sample size", "Outcome"],
    "rows": [
      {
        "paper_id": "pmid:12345",
        "Methods": "<short value>",
        "Sample size": "<short value>",
        "Outcome": "<short value>"
      }
    ]
  },
  "confidence": 0.0
}

Rules:
- paper_ids must be either "pmid:<digits>" or "doi:<doi>".
- All paper_ids must come from the input list. Do not invent.
- Return ONLY the JSON object; no prose before or after.
"""
