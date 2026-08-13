"""
azure_openai_provider.py

Azure OpenAI implementation of the LLMProvider interface.

This module is a thin specialization of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.

Azure OpenAI deployments expose an OpenAI-compatible endpoint whose
URL is ``https://<resource>.openai.azure.com/openai/deployments/<deployment>``.
The provider reads the endpoint from ``AZURE_OPENAI_ENDPOINT`` and
the deployment name (used as the model) from
``AZURE_OPENAI_DEPLOYMENT`` or falls back to the model field.

Environment Variables
----------------------
``AZURE_OPENAI_API_KEY``
    Required: Azure OpenAI API key.
``AZURE_OPENAI_ENDPOINT``
    Required: ``https://<resource>.openai.azure.com`` (no trailing slash).
``AZURE_OPENAI_DEPLOYMENT``
    Optional: deployment name. Overrides the model field.
``AZURE_OPENAI_API_VERSION``
    Optional: API version (default ``2024-08-01-preview``).

Author
------
Guillermo Ramajo Fernández
"""


from __future__ import annotations

import os

from app.infrastructure.llm._openai_compatible import (
    OpenAICompatibleProvider,
)


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """
    Azure OpenAI provider.

    Resolves the endpoint at construction time from
    ``AZURE_OPENAI_ENDPOINT`` and the deployment from
    ``AZURE_OPENAI_DEPLOYMENT``. The default model is the
    deployment name; the bootstrap GUI surfaces this to the user.
    """

    api_key_env = "AZURE_OPENAI_API_KEY"
    model_env = "AZURE_OPENAI_DEPLOYMENT"
    default_model = "gpt-4.1"

    def __init__(self, *args, **kwargs):
        # Resolve the base URL from the env if not explicitly set.
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        if endpoint and not kwargs.get("base_url"):
            api_version = os.getenv(
                "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"
            )
            kwargs["base_url"] = (
                f"{endpoint}/openai/deployments/"
                f"{os.getenv('AZURE_OPENAI_DEPLOYMENT', self.default_model)}"
                f"?api-version={api_version}"
            )
        super().__init__(*args, **kwargs)
