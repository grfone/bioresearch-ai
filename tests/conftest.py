"""
tests/conftest.py

Pytest configuration for the BioResearch AI suite.

The project instantiates ``PubMedSettings`` from
``app.config.pubmed`` at module-import time. ``PubMedSettings``
requires ``PUBMED_EMAIL`` to be present (NCBI publishes a usage
policy requiring an email address in E-Utils requests) and the
test environment did not previously set a default, which made
test invocations on a clean machine fail with a Pydantic
ValidationError before any test code ran.

We set a synthetic test email here so the test suite can run
without any operator setup. PubMed E-Utils calls in tests that
hit the real API are isolated and use ``monkeypatch`` on the
HTTP client; the rest of the suite never talks to NCBI.
"""

from __future__ import annotations

import os

# Set defaults BEFORE any ``app.*`` import so Pydantic reads
# the env on module load.
os.environ.setdefault(
    "PUBMED_EMAIL", "bioresearch-ai-tests@example.com"
)
os.environ.setdefault(
    "OPENAI_API_KEY", "sk-test-fake-key-for-suite"
)
os.environ.setdefault(
    "DEFAULT_LLM_PROVIDER", "openai"
)
os.environ.setdefault(
    "DEFAULT_LLM_MODEL", "gpt-4.1-mini"
)
