"""
probe_credentials.py

Standalone helper used by the bootstrap GUI to verify that the
supplied credentials actually work before saving them to `.env`.

The script is intentionally self-contained — it does not import the
BioResearch AI application. It only needs the standard library
plus ``openai`` (which is shipped on the host or the conda env) and
``urllib`` for PubMed.

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
import sys
import time
import urllib.parse
import urllib.request
from typing import Any


# ---------------------------------------------------------------------------
# LLM probe
# ---------------------------------------------------------------------------


def probe_openai(api_key: str, base_url: str, model: str, timeout: int = 30) -> dict[str, Any]:
    """
    Verify an OpenAI-compatible API key by issuing a 1-token call.

    Parameters
    ----------
    api_key : str
        The API key under test (or "ollama" for local).
    base_url : str
        Base URL of the OpenAI-compatible endpoint.
    model : str
        Model name to call.
    timeout : int
        Maximum time (seconds) to wait.

    Returns
    -------
    dict[str, Any]
        Probe result with ``ok`` and ``message``.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        return {
            "ok": False,
            "message": (
                "The 'openai' Python package is not installed. "
                "Re-run bootstrap.py with the conda environment active."
            ),
        }

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    started = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            temperature=0.0,
        )
        _ = response.choices[0].message.content
        return {
            "ok": True,
            "message": (
                f"OK — {model} responded in "
                f"{time.monotonic() - started:.1f}s"
            ),
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": _explain_openai_error(exc),
        }


def _explain_openai_error(exc: Exception) -> str:
    """Return a hint tailored to the most common OpenAI-style errors."""
    text = str(exc)
    lowered = text.lower()
    if "401" in text or "invalid_api_key" in lowered or "incorrect api key" in lowered:
        return (
            "Authentication failed: the API key was rejected. "
            "Double-check the value (no leading/trailing whitespace) and "
            "that it has the right permissions on your provider's dashboard."
        )
    if "404" in text or "model_not_found" in lowered:
        return (
            "The selected model is not available on this account. "
            "Try a different model (e.g. 'gpt-4.1-mini', 'claude-3-5-sonnet')."
        )
    if "429" in text or "rate_limit" in lowered:
        return (
            "Rate-limited. Wait a few seconds and try again, or "
            "upgrade the plan on your provider's dashboard."
        )
    if "connection" in lowered or "timeout" in lowered:
        return (
            "Could not reach the API endpoint. Check the base URL "
            "and your network connection."
        )
    return f"Unexpected error: {text}"


# ---------------------------------------------------------------------------
# PubMed probe
# ---------------------------------------------------------------------------


def probe_pubmed(email: str, api_key: str, timeout: int = 15) -> dict[str, Any]:
    """
    Verify that the PubMed (NCBI E-utilities) credentials work.

    NCBI requires an email for every request and accepts an
    optional API key which raises the rate limit from 3 to 10
    requests per second. The probe hits the ``einfo`` endpoint
    which returns the public list of databases — it is a cheap
    round-trip that fails fast if the credentials are invalid.

    Parameters
    ----------
    email : str
        Email registered with NCBI.
    api_key : str
        NCBI API key (may be empty).
    timeout : int
        Request timeout (seconds).

    Returns
    -------
    dict[str, Any]
        Probe result with ``ok`` and ``message``.
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
    parser = argparse.ArgumentParser(description="Probe LLM and PubMed credentials")
    parser.add_argument("--llm", choices=["openai", "local"], required=True)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--pubmed-email", default="")
    parser.add_argument("--pubmed-api-key", default="")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    exit_code = 0

    if args.llm == "local":
        # For local mode we don't probe the API key — we just check
        # that the Ollama daemon is reachable on the configured host.
        # The bootstrap script sets OLLAMA_BASE_URL to the in-network
        # address (http://ollama:11434) when docker compose is used.
        import os
        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            with urllib.request.urlopen(f"{base}/api/version", timeout=10) as r:
                body = r.read().decode("utf-8", errors="replace")
            checks.append({
                "name": "llm",
                "ok": True,
                "message": f"OK — Ollama daemon reachable at {base} ({body.strip()[:80]})",
            })
        except Exception as exc:
            checks.append({
                "name": "llm",
                "ok": False,
                "message": (
                    f"Could not reach Ollama at {base}: {exc}. "
                    "Make sure `docker compose up` finished and the "
                    "ollama service is running."
                ),
            })
            exit_code = 2
    else:
        result = probe_openai(
            args.api_key, args.base_url, args.model, timeout=args.timeout
        )
        checks.append({"name": "llm", **result})
        if not result["ok"]:
            exit_code = 2

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
