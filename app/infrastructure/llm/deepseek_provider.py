"""
deepseek_provider.py

DeepSeek implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The DeepSeek service exposes an OpenAI-compatible
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


class DeepSeekProvider(OpenAICompatibleProvider):
    """
    DeepSeek provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``DEEPSEEK_API_KEY``
        Required: DeepSeek API key.
    ``DEEPSEEK_MODEL``
        Optional: model name override. Defaults to
        ``deepseek-chat``.
    """

    base_url = "https://api.deepseek.com/v1"
    default_model = "deepseek-chat"
    api_key_env = "DEEPSEEK_API_KEY"
    model_env = "DEEPSEEK_MODEL"
