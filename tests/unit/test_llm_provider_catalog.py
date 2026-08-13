"""
Unit tests for the LLM provider catalog and the factory.

These tests lock in:

- The catalog has exactly the providers we expect.
- Every catalog entry has a working class registered in the
  factory.
- The factory's ``available_providers`` returns slugs in the
  canonical catalog order.
- The ``LOCAL`` slug is wired to the same class as ``OLLAMA``.
- ``LLMFactory.create`` raises a helpful error for an unknown
  provider.

The tests do not exercise the actual API calls — only the
catalog wiring and the factory dispatch. API-key probing is
covered by ``scripts/probe_credentials.py`` and is tested in
the integration suite.
"""

from __future__ import annotations

import pytest

from app.application.services.llm_provider_catalog import (
    CATALOG,
    ProviderMeta,
    all_slugs,
    get_provider_meta,
    grouped_by_region,
)
from app.core.enums.llm_provider import LLMProviderEnum
from app.infrastructure.llm.llm_factory import LLMFactory


# ---------------------------------------------------------------------------
# Catalog structure
# ---------------------------------------------------------------------------


def test_catalog_has_at_least_twenty_providers() -> None:
    """The user explicitly asked for many options."""
    assert len(CATALOG) >= 20, (
        f"Expected at least 20 providers, got {len(CATALOG)}. "
        "The user asked for many LLM options."
    )


def test_catalog_has_all_major_chinese_providers() -> None:
    """Every major Chinese provider must be present."""
    required = {
        LLMProviderEnum.DEEPSEEK,
        LLMProviderEnum.MINIMAX,
        LLMProviderEnum.MOONSHOT,
        LLMProviderEnum.ZHIPU,
        LLMProviderEnum.ALIBABA,
        LLMProviderEnum.BAIDU,
        LLMProviderEnum.TENCENT,
        LLMProviderEnum.BYTEDANCE,
        LLMProviderEnum.BAICHUAN,
        LLMProviderEnum.YI,
        LLMProviderEnum.SENSETIME,
        LLMProviderEnum.IFLYTEK,
        LLMProviderEnum.STEP_FUN,
        LLMProviderEnum.HUAWEI,
    }
    catalog_slugs = {entry.slug for entry in CATALOG}
    missing = required - catalog_slugs
    assert not missing, f"Missing Chinese providers: {missing}"


def test_catalog_has_all_major_us_providers() -> None:
    """OpenAI, Anthropic, Gemini, Azure, xAI, Perplexity."""
    required = {
        LLMProviderEnum.OPENAI,
        LLMProviderEnum.ANTHROPIC,
        LLMProviderEnum.GEMINI,
        LLMProviderEnum.AZURE_OPENAI,
        LLMProviderEnum.XAI,
        LLMProviderEnum.PERPLEXITY,
    }
    catalog_slugs = {entry.slug for entry in CATALOG}
    missing = required - catalog_slugs
    assert not missing, f"Missing US providers: {missing}"


def test_catalog_has_eu_and_ca_providers() -> None:
    """Mistral and Cohere round out the regional catalog."""
    required = {LLMProviderEnum.MISTRAL, LLMProviderEnum.COHERE}
    catalog_slugs = {entry.slug for entry in CATALOG}
    assert required <= catalog_slugs


def test_catalog_has_local_option() -> None:
    """The Local entry is always present for self-hosted users."""
    assert LLMProviderEnum.LOCAL in {entry.slug for entry in CATALOG}


# ---------------------------------------------------------------------------
# Catalog metadata quality
# ---------------------------------------------------------------------------


def test_every_entry_has_required_fields() -> None:
    for entry in CATALOG:
        assert entry.display_name, f"{entry.slug} is missing a display_name"
        assert entry.region, f"{entry.slug} is missing a region"
        assert entry.default_model, f"{entry.slug} is missing default_model"
        if entry.slug is not LLMProviderEnum.LOCAL:
            assert entry.api_key_env, (
                f"{entry.slug} is missing api_key_env"
            )


def test_api_key_env_is_uppercase() -> None:
    """Convention: env var names are UPPER_SNAKE_CASE."""
    for entry in CATALOG:
        if not entry.api_key_env:
            continue
        assert entry.api_key_env == entry.api_key_env.upper(), (
            f"{entry.slug}: api_key_env must be uppercase, got {entry.api_key_env}"
        )
        assert " " not in entry.api_key_env, (
            f"{entry.slug}: api_key_env must not contain spaces"
        )


def test_base_url_is_https_or_localhost() -> None:
    """All providers must use HTTPS or localhost."""
    for entry in CATALOG:
        if entry.base_url is None:
            continue  # bespoke providers (Anthropic, Azure)
        assert entry.base_url.startswith("https://") or entry.base_url.startswith(
            "http://localhost"
        ) or entry.base_url.startswith("http://host.docker"), (
            f"{entry.slug}: base_url must use https or localhost, got {entry.base_url}"
        )


# ---------------------------------------------------------------------------
# Region grouping
# ---------------------------------------------------------------------------


def test_grouped_by_region_contains_all_entries() -> None:
    """Every catalog entry shows up in exactly one region bucket."""
    flat = [e for entries in grouped_by_region().values() for e in entries]
    assert sorted(e.slug.value for e in flat) == sorted(
        e.slug.value for e in CATALOG
    )


def test_chinese_providers_are_in_cn_bucket() -> None:
    by_region = grouped_by_region()
    assert "CN" in by_region
    cn_slugs = {entry.slug for entry in by_region["CN"]}
    assert LLMProviderEnum.DEEPSEEK in cn_slugs
    assert LLMProviderEnum.MINIMAX in cn_slugs
    assert LLMProviderEnum.ALIBABA in cn_slugs


def test_us_providers_are_in_us_bucket() -> None:
    by_region = grouped_by_region()
    assert "US" in by_region
    us_slugs = {entry.slug for entry in by_region["US"]}
    assert LLMProviderEnum.OPENAI in us_slugs
    assert LLMProviderEnum.ANTHROPIC in us_slugs
    assert LLMProviderEnum.XAI in us_slugs


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def test_get_provider_meta_returns_metadata() -> None:
    meta = get_provider_meta(LLMProviderEnum.DEEPSEEK)
    assert isinstance(meta, ProviderMeta)
    assert meta.slug == LLMProviderEnum.DEEPSEEK
    assert meta.base_url == "https://api.deepseek.com/v1"
    assert meta.default_model == "deepseek-chat"


def test_get_provider_meta_raises_for_unknown() -> None:
    """Bogus enum value must raise KeyError."""
    with pytest.raises(KeyError):
        get_provider_meta("not-a-real-provider")  # type: ignore[arg-type]


def test_all_slugs_returns_catalog_order() -> None:
    """The order in all_slugs() matches the catalog declaration order."""
    expected = [entry.slug for entry in CATALOG]
    assert all_slugs() == expected


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


def test_factory_registers_every_catalog_entry() -> None:
    """Every catalog entry must have a factory class."""
    for entry in CATALOG:
        cls = LLMFactory.PROVIDERS.get(entry.slug)
        assert cls is not None, (
            f"{entry.slug.value} is in the catalog but not registered "
            f"in LLMFactory.PROVIDERS"
        )


def test_local_alias_points_to_ollama() -> None:
    """LLMProviderEnum.LOCAL and OLLAMA share the same provider class."""
    assert LLMFactory.PROVIDERS[LLMProviderEnum.LOCAL] is (
        LLMFactory.PROVIDERS[LLMProviderEnum.OLLAMA]
    )


def test_factory_available_providers_returns_catalog_order() -> None:
    """available_providers() returns slugs in catalog order."""
    available = LLMFactory.available_providers()
    expected = [entry.slug for entry in CATALOG]
    assert available == expected


def test_factory_create_returns_instance() -> None:
    """create() returns an instance of the registered class."""
    provider = LLMFactory.create(LLMProviderEnum.OPENAI)
    assert provider.__class__.__name__ == "OpenAIProvider"


def test_factory_create_raises_for_unknown() -> None:
    """create() raises ValueError with a helpful message."""
    with pytest.raises(ValueError) as exc:
        # ``register`` is the only way to add a new enum value at
        # runtime, so we can't add a fake provider here. Instead we
        # spy on the registry by removing one and trying to create it.
        original = LLMFactory.PROVIDERS.pop(LLMProviderEnum.OPENAI)
        try:
            LLMFactory.create(LLMProviderEnum.OPENAI)
        finally:
            LLMFactory.PROVIDERS[LLMProviderEnum.OPENAI] = original
    assert "openai" in str(exc.value)
    assert "Implemented providers" in str(exc.value)


# ---------------------------------------------------------------------------
# Provider class behaviour (cheap instantiation, no API calls)
# ---------------------------------------------------------------------------


def test_openai_compatible_provider_has_expected_attributes() -> None:
    """Every non-bespoke provider exposes the base URL via the class."""
    from app.infrastructure.llm.deepseek_provider import DeepSeekProvider
    from app.infrastructure.llm.xai_provider import XaiProvider

    # Both inherit from OpenAICompatibleProvider and set base_url.
    dp = DeepSeekProvider(api_key="dummy")
    assert dp._base_url == "https://api.deepseek.com/v1"
    assert dp._model == "deepseek-chat"

    xp = XaiProvider(api_key="dummy")
    assert xp._base_url == "https://api.x.ai/v1"
    assert xp._model == "grok-3-mini"


def test_minimax_provider_preserved() -> None:
    """The user's existing bespoke provider still works."""
    from app.infrastructure.llm.minimax_provider import MinimaxProvider
    provider = MinimaxProvider(api_key="dummy")
    assert provider.ENDPOINT == "https://api.minimax.io/anthropic/v1/messages"
    assert provider.DEFAULT_MODEL == "MiniMax-M3"
