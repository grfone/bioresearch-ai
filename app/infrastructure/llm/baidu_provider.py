"""
baidu_provider.py

Baidu Qianfan implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
The Baidu Qianfan service exposes an OpenAI-compatible
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


class BaiduProvider(OpenAICompatibleProvider):
    """
    Baidu Qianfan provider.

    Uses the OpenAI-compatible ``/chat/completions`` endpoint. The
    base URL, default model, and API key environment variable are
    configured here. The catalog
    (``app.application.services.llm_provider_catalog``) is the
    canonical source of these values for the GUI.

    Environment Variables
    ----------------------
    ``QIANFAN_API_KEY``
        Required: Baidu Qianfan API key.
    ``BAIDU_MODEL``
        Optional: model name override. Defaults to
        ``ernie-4.0-8k``.
    """

    base_url = "https://qianfan.baidubce.com/v2"
    default_model = "ernie-4.0-8k"
    api_key_env = "QIANFAN_API_KEY"
    model_env = "BAIDU_MODEL"
