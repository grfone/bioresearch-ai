"""
llm_provider_catalog.py

Single source of truth for the LLM providers supported by
BioResearch AI.

Purpose
-------
This module is the authoritative catalog of every LLM provider the
bootstrap GUI lets the user pick. It is consumed by:

- :class:`app.application.services.llm_provider_catalog.LLMProviderCatalog`
  itself, which exposes the data in a typed form.
- The bootstrap GUI (``bootstrap.py``) which renders the regional
  picker.
- The credential probe (``scripts/probe_credentials.py``) which
  receives the catalog metadata to know the right endpoint.
- The LLM factory which instantiates the right provider class.

Every provider here has a working implementation. The user said
"make the LLM options great" — so we cover the major Chinese
providers (DeepSeek, Alibaba Qwen, Baidu Qianfan, Tencent
Hunyuan, ByteDance Doubao, Zhipu GLM, Moonshot Kimi, Baichuan,
MiniMax, 01.AI Yi, SenseTime, iFlytek Spark, StepFun, Huawei
Pangu) and the major US providers (OpenAI, Anthropic, Google
Gemini, Azure OpenAI, xAI Grok, Perplexity) plus Cohere (CA)
and Mistral (EU).

Architectural choice
---------------------
The vast majority of these providers expose an OpenAI-compatible
``/chat/completions`` endpoint. We do **not** write 22 bespoke HTTP
adapters. Instead, every provider except

- ``minimax`` (Anthropic /v1/messages format), and
- ``anthropic`` itself,

is a one-line subclass of :class:`OpenAICompatibleProvider` from
``app.infrastructure.llm._openai_compatible``. The catalog is the
single place where the URL, model, and key environment variable
are configured for each provider.

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional

from app.core.enums.llm_provider import LLMProviderEnum


# ---------------------------------------------------------------------------
# Metadata model
# ---------------------------------------------------------------------------


class ProviderProtocol(StrEnum):
    """The wire protocol a provider exposes.

    Most modern LLM providers expose an OpenAI-compatible
    ``/chat/completions`` endpoint (OpenAI itself, DeepSeek,
    Moonshot, Alibaba Qwen, ByteDance Doubao, Mistral, Cohere,
    Gemini, xAI Grok, Perplexity, etc.).

    A handful of providers expose the Anthropic-native
    ``/v1/messages`` endpoint instead. The most prominent is
    Anthropic itself, but the Anthropic-shaped API is also
    exposed by several Chinese providers (e.g. MiniMax
    recommends it for M-series reasoning models). When a
    provider uses the Anthropic protocol we must talk to
    ``/v1/messages`` with the Anthropic request schema
    (system, messages, max_tokens) rather than the OpenAI
    schema.
    """

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass(frozen=True)
class ProviderMeta:
    """
    Static metadata describing a single LLM provider.

    Attributes
    ----------
    slug : LLMProviderEnum
        The enum value used in ``.env`` and the database.

    display_name : str
        Human-readable name shown in the bootstrap GUI.

    region : str
        Two-letter country / region code ("US", "CN", "EU", "CA").
        Used to group picks in the GUI.

    base_url : str | None
        Default OpenAI-compatible base URL. ``None`` means the
        provider is bespoke (Anthropic, AzureOpenAI) and the
        provider class handles the URL itself.

    default_model : str
        Reasonable default model identifier pre-filled in the GUI.

    api_key_env : str
        Environment variable name that holds the API key (e.g.
        ``OPENAI_API_KEY``). The bootstrap GUI checks for this
        name in the user's environment and offers it as the
        default.

    model_hint : str
        A short hint shown next to the model field in the GUI
        (e.g. "gpt-4.1, gpt-4.1-mini, gpt-5"). Helps the user
        pick a sensible model.

    requires_extra_headers : bool
        ``True`` for the few providers that need a custom header
        (e.g. Baidu's Qianfan) instead of the standard
        ``Authorization: Bearer <key>``.

    notes : str
        Free-form note shown in the GUI. Used for things like
        "Azure requires a deployment name" or "use BOT_TOKEN for
        @Minimax users".
    """

    slug: LLMProviderEnum
    display_name: str
    region: str
    base_url: Optional[str]
    default_model: str
    api_key_env: str
    model_hint: str = ""
    requires_extra_headers: bool = False
    notes: str = ""
    protocol: ProviderProtocol = ProviderProtocol.OPENAI


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------
#
# Order is significant: the GUI displays providers in this order, grouped
# by region. We list first the providers the user is most likely to use,
# then the long tail.
# ---------------------------------------------------------------------------

CATALOG: tuple[ProviderMeta, ...] = (
    # ------------------------------------------------------------------
    # Local — self-hosted (no API key)
    # ------------------------------------------------------------------
    ProviderMeta(
        slug=LLMProviderEnum.LOCAL,
        display_name="Local (self-hosted Ollama)",
        region="Local",
        base_url="http://localhost:11434/v1",
        default_model="deepseek-coder-v2-lite-instruct",
        api_key_env="",
        model_hint="deepseek-r1-distill-llama-8b-q4_k_m, qwen2.5, llama3.1",
        notes=(
            "Runs entirely on your machine. The bootstrap script "
            "selects a quantized model that fits your hardware."
        ),
    protocol=ProviderProtocol.OPENAI,
    ),
    # ------------------------------------------------------------------
    # US — major providers
    # ------------------------------------------------------------------
    ProviderMeta(
        slug=LLMProviderEnum.OPENAI,
        display_name="OpenAI",
        region="US",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4.1-mini",
        api_key_env="OPENAI_API_KEY",
        model_hint="gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-4o, gpt-4o-mini, o3, o4-mini",
        protocol=ProviderProtocol.OPENAI,
),
    ProviderMeta(
        slug=LLMProviderEnum.ANTHROPIC,
        display_name="Anthropic",
        region="US",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-3-5-sonnet-latest",
        api_key_env="ANTHROPIC_API_KEY",
        model_hint="claude-3-5-sonnet, claude-3-5-haiku, claude-opus-4",
        notes=(
            "Uses Anthropic's OpenAI-compatible endpoint at /v1. "
            "Configure via ANTHROPIC_API_KEY."
),
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.GEMINI,
        display_name="Google Gemini",
        region="US",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-2.0-flash",
        api_key_env="GEMINI_API_KEY",
        model_hint="gemini-2.0-flash, gemini-2.0-pro, gemini-1.5-pro",
        protocol=ProviderProtocol.OPENAI,
),
    ProviderMeta(
        slug=LLMProviderEnum.AZURE_OPENAI,
        display_name="Azure OpenAI",
        region="US",
        base_url=None,
        default_model="gpt-4.1",
        api_key_env="AZURE_OPENAI_API_KEY",
        model_hint="Use your deployment name",
        notes=(
            "Azure requires AZURE_OPENAI_ENDPOINT and the deployment "
            "name as the model field."
),
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.XAI,
        display_name="xAI (Grok)",
        region="US",
        base_url="https://api.x.ai/v1",
        default_model="grok-3-mini",
        api_key_env="XAI_API_KEY",
        model_hint="grok-3, grok-3-fast, grok-3-mini, grok-2",
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.PERPLEXITY,
        display_name="Perplexity",
        region="US",
        base_url="https://api.perplexity.ai/v1",
        default_model="llama-3.1-sonar-large-128k-online",
        api_key_env="PERPLEXITY_API_KEY",
        model_hint="llama-3.1-sonar-large-128k-online, sonar",
        protocol=ProviderProtocol.OPENAI,
),
    # ------------------------------------------------------------------
    # EU / CA
    # ------------------------------------------------------------------
    ProviderMeta(
        slug=LLMProviderEnum.MISTRAL,
        display_name="Mistral AI",
        region="EU",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-large-latest",
        api_key_env="MISTRAL_API_KEY",
        model_hint="mistral-large-latest, mistral-medium-latest, mistral-small-latest",
        protocol=ProviderProtocol.OPENAI,
),
    ProviderMeta(
        slug=LLMProviderEnum.COHERE,
        display_name="Cohere",
        region="CA",
        base_url="https://api.cohere.ai/compatibility/v1",
        default_model="command-r-plus",
        api_key_env="COHERE_API_KEY",
        model_hint="command-r-plus, command-r, command-light",
        protocol=ProviderProtocol.OPENAI,
),
    # ------------------------------------------------------------------
    # China — major providers
    # ------------------------------------------------------------------
    ProviderMeta(
        slug=LLMProviderEnum.DEEPSEEK,
        display_name="DeepSeek",
        region="CN",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        model_hint="deepseek-chat, deepseek-reasoner, deepseek-coder",
        protocol=ProviderProtocol.OPENAI,
),
    ProviderMeta(
        slug=LLMProviderEnum.MINIMAX,
        display_name="MiniMax",
        region="CN",
        base_url="https://api.minimax.io/anthropic",
        default_model="MiniMax-M3",
        api_key_env="MINIMAX_API_KEY",
        model_hint="abab6.5s-chat, MiniMax-M3, MiniMax-Text-01",
        notes=(
            "Uses Anthropic-compatible /v1/messages. The retain "
            "API key starts with ``eyJ...``."
),
    protocol=ProviderProtocol.ANTHROPIC,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.MOONSHOT,
        display_name="Moonshot (Kimi)",
        region="CN",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-32k",
        api_key_env="MOONSHOT_API_KEY",
        model_hint="moonshot-v1-32k, moonshot-v1-128k, moonshot-v1-8k",
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.ZHIPU,
        display_name="Zhipu (GLM)",
        region="CN",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-plus",
        api_key_env="ZHIPU_API_KEY",
        model_hint="glm-4-plus, glm-4-air, glm-4-airx, glm-4-long",
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.ALIBABA,
        display_name="Alibaba (Qwen)",
        region="CN",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        api_key_env="DASHSCOPE_API_KEY",
        model_hint="qwen-plus, qwen-max, qwen-turbo, qwen-coder-plus",
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.BAIDU,
        display_name="Baidu (Qianfan / ERNIE)",
        region="CN",
        base_url="https://qianfan.baidubce.com/v2",
        default_model="ernie-4.0-8k",
        api_key_env="QIANFAN_API_KEY",
        model_hint="ernie-4.0-8k, ernie-3.5-8k, ernie-speed-8k",
        requires_extra_headers=True,
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.TENCENT,
        display_name="Tencent (Hunyuan)",
        region="CN",
        base_url="https://api.hunyuan.cloud.tencent.com/v1",
        default_model="hunyuan-pro",
        api_key_env="HUNYUAN_API_KEY",
        model_hint="hunyuan-pro, hunyuan-standard, hunyuan-lite",
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.BYTEDANCE,
        display_name="ByteDance (Doubao)",
        region="CN",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-pro-32k",
        api_key_env="BYTE_DANCE_API_KEY",
        model_hint="doubao-pro-32k, doubao-lite-32k, doubao-pro-128k",
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.BAICHUAN,
        display_name="Baichuan",
        region="CN",
        base_url="https://api.baichuan-ai.com/v1",
        default_model="baichuan4-turbo",
        api_key_env="BAICHUAN_API_KEY",
        model_hint="baichuan4-turbo, baichuan4-air, baichuan3-turbo",
        protocol=ProviderProtocol.OPENAI,
),
    ProviderMeta(
        slug=LLMProviderEnum.YI,
        display_name="01.AI (Yi)",
        region="CN",
        base_url="https://api.01.ai/v1",
        default_model="yi-large",
        api_key_env="YI_API_KEY",
        model_hint="yi-large, yi-medium, yi-vision, yi-spark",
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.SENSETIME,
        display_name="SenseTime (SenseChat)",
        region="CN",
        base_url="https://api.sensenova.cn/compatible-mode/v1",
        default_model="SenseChat-5",
        api_key_env="SENSENOVA_API_KEY",
        model_hint="SenseChat-5, SenseChat-5-120B, SenseChat-4",
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.IFLYTEK,
        display_name="iFlytek (Spark)",
        region="CN",
        base_url="https://spark-api-open.xf-yun.com/v1",
        default_model="generalv3.5",
        api_key_env="IFLYTEK_API_KEY",
        model_hint="generalv3.5, generalv3, generalv2.5",
    protocol=ProviderProtocol.OPENAI,
    ),
    ProviderMeta(
        slug=LLMProviderEnum.STEP_FUN,
        display_name="StepFun",
        region="CN",
        base_url="https://api.stepfun.com/v1",
        default_model="step-1v-32k",
        api_key_env="STEPFUN_API_KEY",
        model_hint="step-1v-32k, step-1-32k, step-1-128k",
        protocol=ProviderProtocol.OPENAI,
),
    ProviderMeta(
        slug=LLMProviderEnum.HUAWEI,
        display_name="Huawei (Pangu)",
        region="CN",
        base_url="https://pangu.ap-southeast-1.myhuaweicloud.com/v1",
        default_model="pangu-4",
        api_key_env="HUAWEI_PANGU_API_KEY",
        model_hint="pangu-4, pangu-3",
    protocol=ProviderProtocol.OPENAI,
    ),
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _by_slug() -> dict[LLMProviderEnum, ProviderMeta]:
    return {entry.slug: entry for entry in CATALOG}


def get_provider_meta(slug: LLMProviderEnum) -> ProviderMeta:
    """
    Return the metadata for the given provider.

    Raises
    ------
    KeyError
        If the slug is not in the catalog.
    """
    return _by_slug()[slug]


def grouped_by_region() -> dict[str, list[ProviderMeta]]:
    """Return the catalog grouped by region, preserving catalog order."""
    out: dict[str, list[ProviderMeta]] = {}
    for entry in CATALOG:
        out.setdefault(entry.region, []).append(entry)
    return out


def all_slugs() -> list[LLMProviderEnum]:
    """Return the catalog slugs in declared order."""
    return [entry.slug for entry in CATALOG]
