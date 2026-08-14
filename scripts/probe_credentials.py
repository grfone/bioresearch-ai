"""
probe_credentials.py

Standalone helper used by the bootstrap GUI to verify that the
supplied credentials actually work before saving them to ``.env``.

The script is intentionally self-contained — it does not import the
BioResearch AI application. It uses the standard library plus
``httpx`` (already shipped on the host via the conda env or the
slim image's minimal requirements) for HTTP. We deliberately avoid
the OpenAI and Anthropic SDKs so the probe works for providers that
expose either ``/chat/completions`` (OpenAI-compatible) or
``/v1/messages`` (Anthropic-compatible).

Exit code semantics:
    0   success
    1   invalid CLI args
    2   LLM probe failed
    3   PubMed probe failed

Output:
    A single JSON object on stdout with the following shape:

    {
        "ok": true | false,
        "checks": [
            {"name": "llm",    "ok": true,  "message": "..."},
            {"name": "pubmed", "ok": true,  "message": "..."}
        ]
    }

Author
------
Guillermo Ramajo Fernández
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

import httpx


# ---------------------------------------------------------------------------
# LLM probes — one per protocol
# ---------------------------------------------------------------------------


# The smallest valid request for each protocol. The goal is to
# reach the model endpoint and confirm the API key works without
# spending tokens or generating a meaningful reply.

_OPENAI_PROBE: dict[str, Any] = {
    "model": "placeholder-replaced-by-arg",
    "messages": [{"role": "user", "content": "ping"}],
    "max_tokens": 1,
    "temperature": 0.0,
    "stream": False,
}

_ANTHROPIC_PROBE: dict[str, Any] = {
    "model": "placeholder-replaced-by-arg",
    "messages": [{"role": "user", "content": "ping"}],
    "max_tokens": 1,
}


def probe_openai_compat(
    api_key: str,
    base_url: str,
    model: str,
    timeout: int = 30,
) -> dict[str, Any]:
    """Probe an OpenAI-compatible ``/chat/completions`` endpoint.

    Used for the vast majority of providers (OpenAI itself, DeepSeek,
    Moonshot, Alibaba Qwen, ByteDance Doubao, Mistral, Cohere, Gemini
    via its openai-compat layer, xAI Grok, Perplexity, etc.).
    """
    if not base_url:
        return {
            "ok": False,
            "message": "No base URL configured for this provider.",
        }
    payload = dict(_OPENAI_PROBE)
    payload["model"] = model
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "message": (
                f"Could not reach the API endpoint: {exc!s}. "
                "Check the base URL and your network connection."
            ),
        }
    elapsed = time.monotonic() - started
    if response.status_code == 200:
        return {
            "ok": True,
            "message": (
                f"OK — {model} responded via OpenAI-compatible "
                f"endpoint in {elapsed:.1f}s"
            ),
        }
    return {
        "ok": False,
        "message": _explain_http_error(response.status_code, response.text),
    }


def probe_anthropic_compat(
    api_key: str,
    base_url: str,
    model: str,
    timeout: int = 30,
) -> dict[str, Any]:
    """Probe an Anthropic-compatible ``/v1/messages`` endpoint.

    Used for Anthropic itself and providers that expose the
    Anthropic Messages schema (e.g. MiniMax recommends
    ``/v1/messages`` for M-series reasoning models).
    """
    if not base_url:
        return {
            "ok": False,
            "message": (
                "This provider uses the Anthropic protocol but "
                "no base URL is configured."
            ),
        }
    payload = dict(_ANTHROPIC_PROBE)
    payload["model"] = model
    # The Anthropic API requires ``max_tokens``. We already set it
    # to 1 above. Anthropic also accepts a ``system`` field; we
    # omit it to keep the probe minimal.
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "message": (
                f"Could not reach the API endpoint: {exc!s}. "
                "Check the base URL and your network connection."
            ),
        }
    elapsed = time.monotonic() - started
    if response.status_code == 200:
        return {
            "ok": True,
            "message": (
                f"OK — {model} responded via Anthropic-compatible "
                f"endpoint in {elapsed:.1f}s"
            ),
        }
    return {
        "ok": False,
        "message": _explain_http_error(response.status_code, response.text),
    }


def probe_local(base: str | None = None, timeout: int = 10) -> dict[str, Any]:
    """Probe a local Ollama daemon.

    Hits ``/api/version`` (cheap, no GPU required) to confirm the
    daemon is reachable on the configured host. The bootstrap
    script sets ``OLLAMA_BASE_URL`` to the in-network address
    (http://ollama:11434) when docker compose is used.
    """
    if base is None:
        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    url = f"{base.rstrip('/')}/api/version"
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
        response.raise_for_status()
        body = response.text
        elapsed = time.monotonic() - started
        return {
            "ok": True,
            "message": (
                f"OK — Ollama daemon reachable at {base} "
                f"({body.strip()[:80]}) in {elapsed:.1f}s"
            ),
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "message": (
                f"Could not reach Ollama at {base}: {exc!s}. "
                "Make sure ``docker compose up`` finished and the "
                "ollama service is running."
            ),
        }


def _explain_http_error(status_code: int, body: str) -> str:
    """Return a hint tailored to the most common LLM API errors."""
    snippet = body[:200] if body else ""
    lowered = snippet.lower()
    if status_code == 401 or "invalid_api_key" in lowered or "incorrect api key" in lowered:
        return (
            "Authentication failed: the API key was rejected. "
            "Double-check the value (no leading/trailing whitespace) "
            "and that it has the right permissions on your provider's "
            "dashboard."
        )
    if status_code == 403:
        return (
            "Permission denied. The API key may not have access to "
            "this model or this endpoint."
        )
    if status_code == 404 or "model_not_found" in lowered:
        return (
            "The selected model is not available on this account. "
            "Try a different model (e.g. 'gpt-4.1-mini', "
            "'claude-3-5-sonnet-latest', 'MiniMax-M3')."
        )
    if status_code == 429 or "rate_limit" in lowered:
        return (
            "Rate-limited. Wait a few seconds and try again, or "
            "upgrade the plan on your provider's dashboard."
        )
    if status_code in (502, 503, 504) or "connection" in lowered or "timeout" in lowered:
        return (
            "The provider's API endpoint is unreachable or "
            "timing out. Try again in a moment, or check the base "
            "URL is correct."
        )
    return (
        f"Unexpected error: HTTP {status_code}. "
        f"Response: {snippet}"
    )


# ---------------------------------------------------------------------------
# PubMed probe (unchanged — uses stdlib urllib)
# ---------------------------------------------------------------------------


def probe_pubmed(email: str, api_key: str, timeout: int = 15) -> dict[str, Any]:
    """Verify that the PubMed (NCBI E-utilities) credentials work.

    NCBI requires an email for every request and accepts an
    optional API key which raises the rate limit from 3 to 10
    requests per second. The probe hits the ``einfo`` endpoint
    which returns the public list of databases — it is a cheap
    round-trip that fails fast if the credentials are invalid.
    """
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi"
    params = {"email": email, "tool": "BioResearchAI-bootstrap"}
    if api_key:
        params["api_key"] = api_key
    url = f"{base}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BioResearchAI/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if "<DbList>" in body or "pubmed" in body.lower():
                return {
                    "ok": True,
                    "message": (
                        f"OK — NCBI E-utilities reachable"
                        f"{' with API key' if api_key else ' (no API key, lower rate limit)'}"
                    ),
                }
            return {
                "ok": False,
                "message": "Unexpected PubMed response — please try again.",
            }
    except urllib.error.HTTPError as exc:
        if exc.code == 400:
            return {
                "ok": False,
                "message": (
                    "PubMed rejected the email. NCBI requires a valid "
                    "email address. Sign up or re-check the value at "
                    "https://www.ncbi.nlm.nih.gov/account/"
                ),
            }
        if exc.code == 429:
            return {
                "ok": False,
                "message": (
                    "PubMed rate limit exceeded. Wait a few seconds "
                    "and try again, or set an API key."
                ),
            }
        return {
            "ok": False,
            "message": f"PubMed HTTP {exc.code}: {exc.reason}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": (
                f"Could not reach PubMed: {exc}. "
                "Check your network connection."
            ),
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe LLM and PubMed credentials. The LLM probe "
            "dispatches to one of three backends based on --llm: "
            "'local' pings Ollama's /api/version; 'openai' talks "
            "to /chat/completions; 'anthropic' talks to /v1/messages."
        )
    )
    parser.add_argument(
        "--llm",
        choices=["openai", "anthropic", "local"],
        required=True,
        help=(
            "LLM probe protocol. 'openai' = OpenAI-compatible "
            "/chat/completions (covers most providers). "
            "'anthropic' = Anthropic Messages API. "
            "'local' = Ollama daemon."
        ),
    )
    parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--pubmed-email", default="")
    parser.add_argument("--pubmed-api-key", default="")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--ollama-base-url",
        default=None,
        help=(
            "Override the Ollama daemon URL for the 'local' probe. "
            "Defaults to the OLLAMA_BASE_URL env var or "
            "http://localhost:11434."
        ),
    )
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    exit_code = 0

    # ---- LLM probe ----
    if args.llm == "local":
        result = probe_local(
            base=args.ollama_base_url, timeout=min(args.timeout, 15)
        )
    elif args.llm == "openai":
        result = probe_openai_compat(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            timeout=args.timeout,
        )
    elif args.llm == "anthropic":
        result = probe_anthropic_compat(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            timeout=args.timeout,
        )
    else:
        # argparse ``choices`` should make this unreachable.
        result = {"ok": False, "message": f"Unknown --llm value {args.llm!r}"}

    checks.append({"name": "llm", **result})
    if not result["ok"]:
        exit_code = 2

    # ---- PubMed probe ----
    if args.pubmed_email:
        result = probe_pubmed(args.pubmed_email, args.pubmed_api_key)
        checks.append({"name": "pubmed", **result})
        if not result["ok"]:
            exit_code = 3 if exit_code == 0 else exit_code

    overall_ok = all(c["ok"] for c in checks)
    output = {"ok": overall_ok, "checks": checks}
    print(json.dumps(output, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
