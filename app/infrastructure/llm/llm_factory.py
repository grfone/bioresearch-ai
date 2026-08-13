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

Supported Providers
-------------------
Current
    - OpenAI

Planned
    - Anthropic
    - Gemini
    - Ollama
    - Azure OpenAI
    - DeepSeek
    - Additional providers listed in ``LLMProviderEnum``.

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
from app.infrastructure.llm.deepseek_provider import DeepSeekProvider
from app.infrastructure.llm.gemini_provider import GeminiProvider
from app.infrastructure.llm.huawei_provider import HuaweiProvider
from app.infrastructure.llm.iflytek_provider import IflytekProvider
from app.infrastructure.llm.minimax_provider import MinimaxProvider
from app.infrastructure.llm.moonshot_provider import MoonshotProvider
from app.infrastructure.llm.ollama_provider import OllamaProvider
from app.infrastructure.llm.openai_provider import OpenAIProvider
from app.infrastructure.llm.sensetime_provider import SensetimeProvider
from app.infrastructure.llm.step_fun_provider import StepFunProvider
from app.infrastructure.llm.tencent_provider import TencentProvider
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
    New providers can be added simply by:

    1. Creating a new implementation of ``LLMProvider``.
    2. Registering it in the ``PROVIDERS`` dictionary.

    No changes should be required elsewhere in the application.
    """

    #: Registry of supported provider implementations.
    PROVIDERS: dict[LLMProviderEnum, type[LLMProvider]] = {
        LLMProviderEnum.OPENAI: OpenAIProvider,
        # ``LOCAL`` is the user-facing alias for self-hosted Ollama.
        # Both ``LLMProviderEnum.LOCAL`` and ``LLMProviderEnum.OLLAMA``
        # map to the same provider so existing code that picks OLLAMA
        # keeps working.
        LLMProviderEnum.LOCAL: OllamaProvider,
        LLMProviderEnum.ANTHROPIC: AnthropicProvider,
        LLMProviderEnum.GEMINI: GeminiProvider,
        LLMProviderEnum.OLLAMA: OllamaProvider,
        LLMProviderEnum.AZURE_OPENAI: AzureOpenAIProvider,
        LLMProviderEnum.DEEPSEEK: DeepSeekProvider,
        LLMProviderEnum.ALIBABA: AlibabaProvider,
        LLMProviderEnum.BAICHUAN: BaichuanProvider,
        LLMProviderEnum.BAIDU: BaiduProvider,
        LLMProviderEnum.BYTEDANCE: BytedanceProvider,
        LLMProviderEnum.HUAWEI: HuaweiProvider,
        LLMProviderEnum.IFLYTEK: IflytekProvider,
        LLMProviderEnum.MINIMAX: MinimaxProvider,
        LLMProviderEnum.MOONSHOT: MoonshotProvider,
        LLMProviderEnum.SENSETIME: SensetimeProvider,
        LLMProviderEnum.STEP_FUN: StepFunProvider,
        LLMProviderEnum.TENCENT: TencentProvider,
        LLMProviderEnum.YI: YiProvider,
        LLMProviderEnum.ZHIPU: ZhipuProvider,
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
            Alphabetically sorted provider enumeration values.
        """

        return sorted(
            cls.PROVIDERS.keys(),
            key=lambda provider: provider.value,
        )

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