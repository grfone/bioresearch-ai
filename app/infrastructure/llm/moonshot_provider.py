"""
moonshot_provider.py

Moonshot Kimi implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Moonshot Kimi service exposes an OpenAI-compatible
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


class MoonshotProvider(OpenAICompatibleProvider):
    """
    Moonshot Kimi provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``MOONSHOT_API_KEY``
        Required: Moonshot Kimi API key.
    ``MOONSHOT_MODEL``
        Optional: model name override. Defaults to
        ``moonshot-v1-32k``.
    """

    base_url = "https://api.moonshot.cn/v1"
    default_model = "moonshot-v1-32k"
    api_key_env = "MOONSHOT_API_KEY"
    model_env = "MOONSHOT_MODEL"
