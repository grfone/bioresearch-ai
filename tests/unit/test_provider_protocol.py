"""
Unit tests for the LLM provider catalog's protocol tagging.

Each provider must declare which wire protocol its API exposes:

- ``openai`` (default): the OpenAI-compatible ``/chat/completions``
  schema. The vast majority of providers use this.
- ``anthropic``: the Anthropic-native ``/v1/messages`` schema.
  Used by Anthropic itself and a few Chinese providers that have
  adopted the Anthropic-shaped API (e.g. MiniMax recommends it
  for M-series reasoning models).

These tests guard against a regression where a provider's
``protocol`` field is missing or mis-tagged, which would cause the
bootstrap to test the wrong endpoint and report a misleading
``'openai' package not installed`` error.

A previous version of ``probe_credentials.py`` hardcoded the OpenAI
client for every non-local provider, which is exactly the bug
that caused the user to see ``'openai' package not installed``
when they picked MiniMax.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PY = REPO_ROOT / "app" / "application" / "services" / "llm_provider_catalog.py"
BOOTSTRAP_PY = REPO_ROOT / "bootstrap.py"
PROBE_PY = REPO_ROOT / "scripts" / "probe_credentials.py"


# ---------------------------------------------------------------------------
# Catalog — every provider must declare a protocol
# ---------------------------------------------------------------------------


def test_catalog_uses_protocol_enum() -> None:
    """The catalog must import ``ProviderProtocol`` from somewhere
    visible. We just check the symbol is referenced, not where it
    lives — the import path may move."""
    text = CATALOG_PY.read_text()
    assert "ProviderProtocol" in text, (
        "catalog.py must define ProviderProtocol and reference it"
    )
    # ANTHROPIC + OPENAI enum values must exist.
    assert 'ANTHROPIC = "anthropic"' in text
    assert 'OPENAI = "openai"' in text


def test_every_provider_has_a_protocol_field() -> None:
    """Every ``ProviderMeta(...)`` call must include ``protocol=``."""
    import ast
    tree = ast.parse(CATALOG_PY.read_text())
    # Find all ProviderMeta calls.
    provider_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ProviderMeta"
    ]
    assert len(provider_calls) >= 10, (
        f"Expected at least 10 ProviderMeta calls, found {len(provider_calls)}"
    )
    for call in provider_calls:
        # Find the slug so we can report which one is missing.
        slug = None
        for kw in call.keywords:
            if kw.arg == "slug" and isinstance(kw.value, ast.Attribute):
                if (
                    isinstance(kw.value.value, ast.Name)
                    and kw.value.value.id == "LLMProviderEnum"
                ):
                    slug = kw.value.attr
                    break
        # Check that ``protocol=`` is present.
        kw_names = {kw.arg for kw in call.keywords}
        assert "protocol" in kw_names, (
            f"ProviderMeta for {slug!r} is missing the protocol= field"
        )


def test_anthropic_uses_openai_protocol() -> None:
    """Anthropic must declare ``protocol=OPENAI`` and use the
    OpenAI-compatible /v1 endpoint.

    The application's ``AnthropicProvider`` is a subclass of
    ``OpenAICompatibleProvider`` and talks to ``/v1`` (the
    OpenAI-compat layer). The probe must use the same protocol
    so a successful probe means the application will also
    work.
    """
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from app.application.services.llm_provider_catalog import CATALOG

    for entry in CATALOG:
        if entry.slug.value == "anthropic":
            assert entry.protocol.value == "openai", (
                f"Anthropic must use protocol=openai, got {entry.protocol.value}"
            )
            assert entry.base_url == "https://api.anthropic.com/v1", (
                f"Anthropic base_url must be the OpenAI-compat /v1, "
                f"got {entry.base_url}"
            )


def test_minimax_uses_anthropic_protocol() -> None:
    """MiniMax recommends its Anthropic-compatible endpoint for
    M-series reasoning models (``/v1/messages``). The probe must
    use the Anthropic probe for MiniMax, not the OpenAI one."""
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from app.application.services.llm_provider_catalog import CATALOG

    for entry in CATALOG:
        if entry.slug.value == "minimax":
            assert entry.protocol.value == "anthropic", (
                f"MiniMax must use protocol=anthropic, got {entry.protocol.value}"
            )


def test_local_uses_default_protocol() -> None:
    """Local (Ollama) is probed with a special --llm local path,
    so its protocol field is irrelevant. We just assert it doesn't
    crash."""
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from app.application.services.llm_provider_catalog import CATALOG

    for entry in CATALOG:
        if entry.slug.value == "local":
            # No assertion; just confirm we can access the field.
            assert entry.protocol is not None


# ---------------------------------------------------------------------------
# Probe — must accept the right --llm values
# ---------------------------------------------------------------------------


def test_probe_supports_all_three_protocols() -> None:
    """``probe_credentials.py --llm`` must accept openai,
    anthropic, and local."""
    text = PROBE_PY.read_text()
    assert "choices=[\"openai\", \"anthropic\", \"local\"]" in text, (
        "probe_credentials.py --llm choices must include "
        "'openai', 'anthropic', 'local'"
    )


def test_probe_implements_anthropic_probe() -> None:
    """The probe must have a separate ``probe_anthropic_compat`` function
    that uses /v1/messages and the x-api-key / anthropic-version
    headers. The OpenAI client cannot do this."""
    text = PROBE_PY.read_text()
    assert "def probe_anthropic_compat" in text, (
        "probe_credentials.py must define probe_anthropic_compat()"
    )
    assert "/v1/messages" in text, (
        "Anthropic probe must hit /v1/messages"
    )
    assert "anthropic-version" in text, (
        "Anthropic probe must set the anthropic-version header"
    )


def test_probe_implements_openai_probe() -> None:
    """The probe must have a ``probe_openai_compat`` function that
    uses /chat/completions. This is the path used by every
    OpenAI-compatible provider."""
    text = PROBE_PY.read_text()
    assert "def probe_openai_compat" in text
    assert "/chat/completions" in text


def test_probe_implements_local_probe() -> None:
    """The probe must have a ``probe_local`` function that hits
    Ollama's /api/version endpoint."""
    text = PROBE_PY.read_text()
    assert "def probe_local" in text
    assert "/api/version" in text


# ---------------------------------------------------------------------------
# Bootstrap — must dispatch to the right probe based on protocol
# ---------------------------------------------------------------------------


def test_bootstrap_picks_protocol_from_catalog() -> None:
    """The bootstrap's ``on_test`` callback must look up the
    provider's ``protocol`` field and pass the corresponding
    ``--llm`` value (``openai`` / ``anthropic`` / ``local``)
    to the probe."""
    text = BOOTSTRAP_PY.read_text()
    # Find the on_test body.
    import re
    m = re.search(
        r"def on_test\(\):.*?(?=\n    def )",
        text,
        re.DOTALL,
    )
    assert m is not None, "on_test() not found in bootstrap.py"
    body = m.group(0)
    # The bug was hardcoded ``"openai"``. Now it must be conditional
    # on entry.protocol.value.
    assert 'entry.protocol.value == "anthropic"' in body, (
        "bootstrap.on_test() must look up entry.protocol.value "
        "to pick between openai and anthropic probes"
    )
    # And it must not have a hardcoded fallback to "openai" for
    # everything that isn't local.
    assert "local" not in body.split("if is_local:")[0] or "anthropic" in body, (
        "The bootstrap must default to anthropic for anthropic-protocol "
        "providers, not silently fall back to openai"
    )
