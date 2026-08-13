"""
baichuan_provider.py

Baichuan implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Baichuan service exposes an OpenAI-compatible
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


class BaichuanProvider(OpenAICompatibleProvider):
    """
    Baichuan provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``BAICHUAN_API_KEY``
        Required: Baichuan API key.
    ``BAICHUAN_MODEL``
        Optional: model name override. Defaults to
        ``baichuan4-turbo``.
    """

    base_url = "https://api.baichuan-ai.com/v1"
    default_model = "baichuan4-turbo"
    api_key_env = "BAICHUAN_API_KEY"
    model_env = "BAICHUAN_MODEL"
