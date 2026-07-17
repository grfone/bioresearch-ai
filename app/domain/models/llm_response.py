"""
llm_response.py

Defines the response returned by any Large Language Model provider.

Concrete providers should map their SDK-specific responses into this
common domain model.

This allows the application layer to remain independent of OpenAI,
Anthropic, Ollama, Azure, Gemini, or any future provider.

Author
------
Guillermo Ramajo Fernández
"""

from dataclasses import dataclass


@dataclass(slots=True)
class LLMResponse:
    """
    Represents a normalized LLM response.
    """

    content: str

    model: str

    prompt_tokens: int

    completion_tokens: int

    total_tokens: int

    finish_reason: str

    latency_seconds: float | None = None