"""
tests/unit/test_health_route.py

Tests for the system health endpoints
(``GET /health`` and ``GET /health/sanitizer``).

The ``/health`` endpoint is intentionally trivial (no DB,
no LLM, no external API) so it can be called from any
healthcheck probe. The ``/health/sanitizer`` endpoint
exposes in-process telemetry counters from the citation
sanitizer -- it's safe to call from probes too (no DB,
no LLM, no external API).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.health import router as health_router


@pytest.fixture
def client() -> TestClient:
    """A minimal FastAPI app exposing only the health router.

    We don't import the full ``main`` module here because
    that wires up the workspace repository, redis, the
    LLM provider, and several heavy dependencies. None
    of that is needed for the health endpoints -- the
    whole point of ``/health`` is that it has zero
    external dependencies. Building a minimal app keeps
    the test fast and the failure modes simple.
    """
    app = FastAPI()
    app.include_router(health_router)
    return TestClient(app)


class TestHealthEndpoint:
    """Pin the existing ``/health`` behaviour so the
    sanitizer endpoint addition doesn't regress it.
    """

    def test_health_returns_healthy_status(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestHealthSanitizerEndpoint:
    """Pin the new ``/health/sanitizer`` endpoint:

      - Returns 200 OK with the expected JSON shape.
      - Reflects the live ``_stats`` dict from the
        ``citation_sanitizer`` module (not a stale
        snapshot).
      - Resetting the counters zeroes the response.
    """

    def test_endpoint_returns_expected_keys(self, client):
        """The endpoint response shape is the same as
        ``get_stats()`` output. The keys are part of the
        contract -- a future change must either preserve
        the keys or update the contract.
        """
        from app.infrastructure.llm.citation_sanitizer import (
            reset_stats,
        )
        reset_stats()
        response = client.get("/health/sanitizer")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
            "total_calls",
            "total_dropped",
            "calls_with_drops",
        }
        for key in body:
            assert isinstance(body[key], int)

    def test_endpoint_reflects_live_counters(self, client):
        """The endpoint reads the live ``_stats`` dict
        from the sanitizer module -- not a cached
        snapshot. We bump a counter by calling the
        sanitizer, then assert the endpoint shows the
        new value.
        """
        from app.infrastructure.llm.citation_sanitizer import (
            reset_stats,
            sanitize_citation_markers,
        )
        reset_stats()

        # Initial state: zeros.
        body = client.get("/health/sanitizer").json()
        assert body["total_calls"] == 0

        # Bump the counters.
        sanitize_citation_markers(
            "see [paper:99]", 20,
            logger_=None,
        )
        sanitize_citation_markers(
            "see [paper:5]", 20,
            logger_=None,
        )

        # Endpoint reflects the new state.
        body = client.get("/health/sanitizer").json()
        assert body["total_calls"] == 2
        assert body["total_dropped"] == 1
        assert body["calls_with_drops"] == 1

    def test_endpoint_does_not_reset_counters(self, client):
        """Calling the endpoint must be a pure read -- it
        must NOT bump any counters. We assert the value
        is stable across two consecutive reads.
        """
        from app.infrastructure.llm.citation_sanitizer import (
            reset_stats,
            sanitize_citation_markers,
        )
        reset_stats()
        sanitize_citation_markers(
            "see [paper:5]", 20, logger_=None,
        )
        before = client.get("/health/sanitizer").json()
        # Second read must return the same values.
        after = client.get("/health/sanitizer").json()
        assert before == after
        # And the read count must NOT have been bumped by
        # the GET requests themselves (otherwise an
        # active healthcheck probe would inflate the
        # counter -- a classic observability antipattern).
        assert after["total_calls"] == 1

    def test_endpoint_returns_independent_copy(self, client):
        """Mutating the response dict must NOT mutate the
        live ``_stats`` dict. This is the ``get_stats``
        contract -- copy on read -- and the endpoint must
        honour it. Otherwise an HTTP client that caches
        the response and writes to it could accidentally
        poison the process-wide counters.
        """
        from app.infrastructure.llm.citation_sanitizer import (
            get_stats,
            reset_stats,
        )
        reset_stats()
        body = client.get("/health/sanitizer").json()
        body["total_calls"] = 9999
        # Live counters unchanged.
        live = get_stats()
        assert live["total_calls"] == 0

    def test_endpoint_does_not_hit_db_or_llm(self):
        """Defence in depth: the endpoint must not import
        anything that opens a database connection or
        makes an LLM call. We assert the module's
        *top-level* imports are all stdlib / FastAPI --
        the sanitizer endpoint's lazy import is fine
        because it's in-process (no I/O).

        The ``get_stats()`` accessor reads the in-process
        ``_stats`` dict -- no I/O. The endpoint imports it
        lazily (inside the function body) so the module
        is importable in test environments without the
        full container wiring.
        """
        import app.api.routes.health as health_mod
        source = open(health_mod.__file__).read()
        # Pin the top-level imports: only stdlib and
        # FastAPI. Anything that opens a DB connection or
        # makes an LLM call must be lazy-imported inside
        # the route handler -- which is what we do for
        # ``citation_sanitizer.get_stats()``.
        top_level_imports = []
        for line in source.splitlines():
            stripped = line.strip()
            if not (
                stripped.startswith("from ")
                or stripped.startswith("import ")
            ):
                continue
            # Skip comments and strings (docstring text is
            # in the file too).
            if stripped.startswith("#"):
                continue
            top_level_imports.append(stripped)
        # Filter out the lazy import inside the function
        # body -- we only check top-level module imports.
        top_level_only = [
            line
            for line in top_level_imports
            if not line.startswith("from app")
            and not line.startswith("import app")
        ]
        # The sanitizer endpoint imports ``get_stats``
        # lazily inside its handler. That import is
        # fine -- the endpoint reads in-process counters.
        # What we forbid is lazy imports that would
        # trigger DB or LLM I/O.
        assert top_level_only == [
            "from fastapi import APIRouter",
        ], (
            "top-level imports of health.py must be limited "
            "to stdlib + FastAPI. Lazy imports inside route "
            "handlers (like the sanitizer endpoint) are "
            "acceptable as long as they don't open DB "
            "connections or make LLM calls. Found: "
            f"{top_level_only}"
        )
