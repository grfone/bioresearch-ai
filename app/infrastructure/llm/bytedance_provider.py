"""
bytedance_provider.py

ByteDance Doubao implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The ByteDance Doubao service exposes an OpenAI-compatible
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


class BytedanceProvider(OpenAICompatibleProvider):
    """
    ByteDance Doubao provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``BYTE_DANCE_API_KEY``
        Required: ByteDance Doubao API key.
    ``BYTEDANCE_MODEL``
        Optional: model name override. Defaults to
        ``doubao-pro-32k``.
    """

    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    default_model = "doubao-pro-32k"
    api_key_env = "BYTE_DANCE_API_KEY"
    model_env = "BYTEDANCE_MODEL"
