"""
sensetime_provider.py

SenseTime implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The SenseTime service exposes an OpenAI-compatible
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


class SensetimeProvider(OpenAICompatibleProvider):
    """
    SenseTime provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``SENSENOVA_API_KEY``
        Required: SenseTime API key.
    ``SENSETIME_MODEL``
        Optional: model name override. Defaults to
        ``SenseChat-5``.
    """

    base_url = "https://api.sensenova.cn/compatible-mode/v1"
    default_model = "SenseChat-5"
    api_key_env = "SENSENOVA_API_KEY"
    model_env = "SENSETIME_MODEL"
