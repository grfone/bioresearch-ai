"""
llm_factory.py

Factory responsible for creating Large Language Model (LLM) providers.

Purpose
-------
This module centralizes the creation of concrete implementations of the
``LLMProvider`` interface.

The rest of the application should never instantiate provider-specific
classes directly (e.g. ``OpenAIProvider``). Instead, it requests an
implementation from this factory.

Using a factory provides several advantages:

- Decouples business logic from infrastructure.
- Centralizes provider registration.
- Simplifies dependency injection.
- Makes it easy to introduce new providers.
- Improves maintainability and extensibility.

The factory relies on the ``LLMProviderEnum`` enumeration instead of raw
strings, improving type safety and preventing typographical errors.

Architectural choice
--------------------
The vast majority of providers in the catalog are thin subclasses of
:class:`~app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`.
This module imports them all and registers them in the
``PROVIDERS`` dictionary. The two bespoke providers (``minimax``,
which uses Anthropic's /v1/messages format, and ``AzureOpenAI``,
which has a deployment-specific URL) keep their custom classes.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from app.core.enums.llm_provider import LLMProviderEnum
from app.domain.interfaces.llm_provider import LLMProvider

from app.infrastructure.llm.alibaba_provider import AlibabaProvider
from app.infrastructure.llm.anthropic_provider import AnthropicProvider
from app.infrastructure.llm.azure_openai_provider import AzureOpenAIProvider
from app.infrastructure.llm.baichuan_provider import BaichuanProvider
from app.infrastructure.llm.baidu_provider import BaiduProvider
from app.infrastructure.llm.bytedance_provider import BytedanceProvider
from app.infrastructure.llm.cohere_provider import CohereProvider
from app.infrastructure.llm.deepseek_provider import DeepSeekProvider
from app.infrastructure.llm.gemini_provider import GeminiProvider
from app.infrastructure.llm.huawei_provider import HuaweiProvider
from app.infrastructure.llm.iflytek_provider import IflytekProvider
from app.infrastructure.llm.minimax_provider import MinimaxProvider
from app.infrastructure.llm.mistral_provider import MistralProvider
from app.infrastructure.llm.moonshot_provider import MoonshotProvider
from app.infrastructure.llm.ollama_provider import OllamaProvider
from app.infrastructure.llm.openai_provider import OpenAIProvider
from app.infrastructure.llm.perplexity_provider import PerplexityProvider
from app.infrastructure.llm.sensetime_provider import SensetimeProvider
from app.infrastructure.llm.step_fun_provider import StepFunProvider
from app.infrastructure.llm.tencent_provider import TencentProvider
from app.infrastructure.llm.xai_provider import XaiProvider
from app.infrastructure.llm.yi_provider import YiProvider
from app.infrastructure.llm.zhipu_provider import ZhipuProvider


class LLMFactory:
    """
    Factory responsible for creating LLM provider instances.

    This class hides the concrete implementations of language model
    providers from the rest of the application.

    The application layer should only depend on the abstract
    ``LLMProvider`` interface and should never instantiate provider
    implementations directly.

    Notes
    -----
    Adding a new provider requires:

    1. Adding a new entry to
       :class:`app.application.services.llm_provider_catalog.CATALOG`.
    2. Creating a thin subclass of
       :class:`app.infrastructure.llm._openai_compatible.OpenAICompatibleProvider`
       (or a bespoke class for non-OpenAI-compatible providers).
    3. Registering the class here, in the ``PROVIDERS`` dictionary.

    No changes should be required elsewhere in the application.
    """

    #: Registry of supported provider implementations.
    PROVIDERS: dict[LLMProviderEnum, type[LLMProvider]] = {
        # Local (self-hosted Ollama). LOCAL is the user-facing alias
        # for OLLAMA.
        LLMProviderEnum.LOCAL: OllamaProvider,
        LLMProviderEnum.OLLAMA: OllamaProvider,
        # US tier.
        LLMProviderEnum.OPENAI: OpenAIProvider,
        LLMProviderEnum.ANTHROPIC: AnthropicProvider,
        LLMProviderEnum.GEMINI: GeminiProvider,
        LLMProviderEnum.AZURE_OPENAI: AzureOpenAIProvider,
        LLMProviderEnum.XAI: XaiProvider,
        LLMProviderEnum.PERPLEXITY: PerplexityProvider,
        # EU / CA.
        LLMProviderEnum.MISTRAL: MistralProvider,
        LLMProviderEnum.COHERE: CohereProvider,
        # CN tier.
        LLMProviderEnum.DEEPSEEK: DeepSeekProvider,
        LLMProviderEnum.MINIMAX: MinimaxProvider,
        LLMProviderEnum.MOONSHOT: MoonshotProvider,
        LLMProviderEnum.ZHIPU: ZhipuProvider,
        LLMProviderEnum.ALIBABA: AlibabaProvider,
        LLMProviderEnum.BAIDU: BaiduProvider,
        LLMProviderEnum.TENCENT: TencentProvider,
        LLMProviderEnum.BYTEDANCE: BytedanceProvider,
        LLMProviderEnum.BAICHUAN: BaichuanProvider,
        LLMProviderEnum.YI: YiProvider,
        LLMProviderEnum.SENSETIME: SensetimeProvider,
        LLMProviderEnum.IFLYTEK: IflytekProvider,
        LLMProviderEnum.STEP_FUN: StepFunProvider,
        LLMProviderEnum.HUAWEI: HuaweiProvider,
    }

    @classmethod
    def create(
        cls,
        provider: LLMProviderEnum,
    ) -> LLMProvider:
        """
        Create an LLM provider instance.

        Parameters
        ----------
        provider
            The provider to instantiate.

        Returns
        -------
        LLMProvider
            Concrete implementation of the requested provider.

        Raises
        ------
        ValueError
            If the provider has not yet been implemented.
        """

        provider_class = cls.PROVIDERS.get(provider)

        if provider_class is None:
            supported = ", ".join(
                p.value for p in cls.available_providers()
            )

            raise ValueError(
                f"Provider '{provider.value}' is not currently "
                f"implemented.\n"
                f"Implemented providers: {supported}."
            )

        return provider_class()

    @classmethod
    def available_providers(cls) -> list[LLMProviderEnum]:
        """
        Return the list of implemented providers.

        Returns
        -------
        list[LLMProviderEnum]
            Providers in the canonical catalog order.
        """
        from app.application.services.llm_provider_catalog import all_slugs

        # Filter to providers that are actually registered.
        registered = set(cls.PROVIDERS.keys())
        return [s for s in all_slugs() if s in registered]

    @classmethod
    def register(
        cls,
        provider: LLMProviderEnum,
        implementation: type[LLMProvider],
    ) -> None:
        """
        Register a new LLM provider.

        This method allows new provider implementations to be added
        without modifying the factory interface.

        Parameters
        ----------
        provider
            Enumeration value identifying the provider.

        implementation
            Class implementing the ``LLMProvider`` interface.

        Notes
        -----
        If a provider is already registered, it will be replaced by the
        supplied implementation.
        """

        cls.PROVIDERS[provider] = implementation
