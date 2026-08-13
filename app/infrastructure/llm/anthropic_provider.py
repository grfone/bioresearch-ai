"""
anthropic_provider.py

Anthropic implementation of the LLMProvider interface.

Anthropic exposes an OpenAI-compatible ``/chat/completions`` endpoint
at https://api.anthropic.com/v1 starting with the 2024-10-22 release.
This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.

Author
------
Guillermo Ramajo Fernández
"""


from __future__ import annotations

from app.infrastructure.llm._openai_compatible import (
    OpenAICompatibleProvider,
)


class AnthropicProvider(OpenAICompatibleProvider):
    """
    Anthropic provider.

    Uses the OpenAI-compatible endpoint at
    ``https://api.anthropic.com/v1``. API key is read from
    ``ANTHROPIC_API_KEY``. The model defaults to
    ``claude-3-5-sonnet-latest``.

    Environment Variables
    ----------------------
    ``ANTHROPIC_API_KEY``
        Required: Anthropic API key.
    ``ANTHROPIC_MODEL``
        Optional: model name override.
    """

    base_url = "https://api.anthropic.com/v1"
    default_model = "claude-3-5-sonnet-latest"
    api_key_env = "ANTHROPIC_API_KEY"
    model_env = "ANTHROPIC_MODEL"
