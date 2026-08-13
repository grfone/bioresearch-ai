"""
tencent_provider.py

Tencent Hunyuan implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Tencent Hunyuan service exposes an OpenAI-compatible
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


class TencentProvider(OpenAICompatibleProvider):
    """
    Tencent Hunyuan provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``HUNYUAN_API_KEY``
        Required: Tencent Hunyuan API key.
    ``TENCENT_MODEL``
        Optional: model name override. Defaults to
        ``hunyuan-pro``.
    """

    base_url = "https://api.hunyuan.cloud.tencent.com/v1"
    default_model = "hunyuan-pro"
    api_key_env = "HUNYUAN_API_KEY"
    model_env = "TENCENT_MODEL"
