"""
llm.py

Large Language Model (LLM) configuration.

Purpose
-------
This module defines the runtime configuration required for interacting
with Large Language Model providers.

Configuration values are automatically loaded from environment variables
defined in the project's `.env` file. The remainder of the application
interacts with this module through domain-oriented attributes rather than
environment variable names.

Using a dedicated configuration object isolates provider-specific details
from the rest of the codebase and simplifies switching between different
LLM vendors.

Example
-------
>>> from app.config.settings import settings
>>>
>>> settings.llm.provider
'openai'
>>>
>>> settings.llm.model
'gpt-4.1'
>>>
>>> settings.llm.api_key

Environment Variables
---------------------
DEFAULT_LLM_PROVIDER
DEFAULT_LLM_MODEL
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_TIMEOUT
OPENAI_MAX_RETRIES

Future Extensions
-----------------
As additional providers are introduced (Anthropic, Gemini, Ollama,
Azure OpenAI, DeepSeek, etc.), this module should remain the single
source of configuration for all LLM-related infrastructure.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    """
    Runtime configuration for Large Language Models.

    Attributes
    ----------
    provider
        Default language model provider.

    model
        Default model used for inference.

    api_key
        API key for the configured provider.

    base_url
        Optional custom endpoint.

    timeout
        Request timeout in seconds, shared by every LLM provider.
        Read from the ``TIMEOUT`` environment variable. Only applied
        to providers when explicitly set -- see
        :attr:`provider_timeout`.

    max_retries
        Maximum number of retry attempts for failed requests.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    provider: str = Field(
        default="openai",
        alias="DEFAULT_LLM_PROVIDER",
    )

    model: str = Field(
        default="gpt-4.1",
        alias="DEFAULT_LLM_MODEL",
    )

    api_key: str = Field(
        default="",
        alias="API_KEY",
        repr=False,
    )

    base_url: str | None = Field(
        default=None,
        alias="BASE_URL",
    )

    timeout: int = Field(
        default=60,
        alias="TIMEOUT",
    )

    @property
    def provider_timeout(self) -> float | None:
        """
        The timeout to hand to LLM providers, or ``None`` for
        "use each provider's own default".

        The shared ``TIMEOUT`` setting only overrides a provider's
        own default when the operator has *explicitly* set it. That
        distinction matters: the providers in the catalog have
        deliberately different defaults (60 seconds for the hosted
        HTTP APIs, 120 for the local Ollama provider), and silently
        flattening them to one number would change behaviour for
        anyone who never touched ``TIMEOUT``.

        When the operator *has* set ``TIMEOUT``, it applies to every
        provider. A provider-specific environment variable
        (``MINIMAX_TIMEOUT``, ``OLLAMA_TIMEOUT``) still wins inside
        the provider, because it is the more specific configuration.

        Note
        ----
        The environment variable is ``TIMEOUT``, not
        ``OPENAI_TIMEOUT`` -- ``LLMSettings`` sets no
        ``env_prefix``, so the field alias is the literal variable
        name. ``OPENAI_TIMEOUT`` was documented in ``.env.example``
        but never read by anything.
        """
        if "timeout" not in self.model_fields_set:
            return None
        return float(self.timeout)

    max_retries: int = Field(
        default=3,
        alias="MAX_RETRIES",
    )


llm_settings = LLMSettings()