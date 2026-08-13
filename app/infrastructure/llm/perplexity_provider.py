"""
perplexity_provider.py

Perplexity implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Perplexity service exposes an OpenAI-compatible
``/chat/completions`` endpoint so the only differences are the
base URL, the default model, and the environment variable that
holds the API key.

Author
------
Guillermo Ramajo Fernández
"""


from __future__ import annotations

from app.infrastructure.llm._openai_compatible import (
    OpenAICompatibleProvider,
)


class PerplexityProvider(OpenAICompatibleProvider):
    """
    Perplexity provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``PERPLEXITY_API_KEY``
        Required: Perplexity API key.
    ``PERPLEXITY_MODEL``
        Optional: model name override. Defaults to
        ``llama-3.1-sonar-large-128k-online``.
    """

    base_url = "https://api.perplexity.ai/v1"
    default_model = "llama-3.1-sonar-large-128k-online"
    api_key_env = "PERPLEXITY_API_KEY"
    model_env = "PERPLEXITY_MODEL"
