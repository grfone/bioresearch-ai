"""
test_admin_endpoints.py

Tests for the operator-facing diagnostics endpoints
mounted under /admin.

We use TestClient with the real FastAPI app and override
``get_identifier_resolver`` to inject a controllable
fake resolver. The fake carries a real AbstractEnricher
(or ``None``) so the endpoint exercises both branches:

  - status="disabled" when the enricher is None
  - the stats dict when the enricher is wired
"""

from __future__ import annotations

from typing import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Spin up the FastAPI app once per test. Uses the
    default ``.env`` from the repo (which the test
    container sets via the bootstrap).

    The endpoint under test doesn't touch the database or
    the network, so we don't need to override
    ``get_research_assistant`` or ``get_workspace_orchestrator``.
    """
    from app.config import container

    import main as main_module

    # Snapshot existing overrides so we can restore them
    # after the test (some test suites leak overrides).
    snapshot = dict(main_module.app.dependency_overrides)

    try:
        yield TestClient(main_module.app)
    finally:
        main_module.app.dependency_overrides.clear()
        main_module.app.dependency_overrides.update(snapshot)


def _make_resolver_with_enricher(enabled: bool | None):
    """Build a fake resolver whose ``_abstract_enricher``
    attribute is either None (disabled) or a real
    AbstractEnricher with controllable cache state.

    The endpoint reads ``resolver._abstract_enricher``
    directly -- not via the public API -- so the fake
    has to expose that attribute with the right shape.
    """
    from dataclasses import dataclass

    class FakeEnricher:
        def __init__(self, hits: int, misses: int, size: int):
            self._hits = hits
            self._misses = misses
            self._size = size

        def cache_stats(self) -> dict[str, int]:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": self._size,
                "capacity": 256,
            }

    @dataclass
    class FakeResolver:
        _abstract_enricher: object

    enricher = (
        FakeEnricher(hits=42, misses=7, size=15)
        if enabled
        else None
    )
    return FakeResolver(_abstract_enricher=enricher)


class TestEnricherStatsEndpoint:
    """GET /admin/enricher-stats."""

    def test_returns_stats_dict_when_enricher_wired(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """When the enricher is constructed, the endpoint
        returns its cache_stats() dict verbatim. This is the
        happy path operators will see in production when
        ABSTRACT_ENRICHER_ENABLED=true.
        """
        from app.config import container
        import app.api.routes.admin as admin_mod

        fake_resolver = _make_resolver_with_enricher(enabled=True)
        # Override the dependency that the route pulls in.
        monkeypatch.setattr(
            container, "get_identifier_resolver",
            lambda: fake_resolver,
        )
        # Also patch the symbol the route already imported.
        monkeypatch.setattr(
            admin_mod, "get_identifier_resolver",
            lambda: fake_resolver,
        )

        response = client.get("/admin/enricher-stats")
        assert response.status_code == 200
        assert response.json() == {
            "hits": 42,
            "misses": 7,
            "size": 15,
            "capacity": 256,
        }

    def test_returns_disabled_status_when_enricher_is_none(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """When ABSTRACT_ENRICHER_ENABLED=false (or otherwise
        not wired), the endpoint returns a clean "disabled"
        payload instead of raising. Operators get a clear
        signal and a hint on how to enable the enricher.
        """
        from app.config import container
        import app.api.routes.admin as admin_mod

        fake_resolver = _make_resolver_with_enricher(enabled=None)
        monkeypatch.setattr(
            container, "get_identifier_resolver",
            lambda: fake_resolver,
        )
        monkeypatch.setattr(
            admin_mod, "get_identifier_resolver",
            lambda: fake_resolver,
        )

        response = client.get("/admin/enricher-stats")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "disabled"
        assert "ABSTRACT_ENRICHER_ENABLED" in body["message"]

    def test_endpoint_is_under_admin_prefix(
        self, client: TestClient,
    ):
        """Confirm the route is registered under the
        ``/admin`` prefix -- catches accidental route
        registration changes that would break operators
        who have dashboards pointing at the canonical URL.
        """
        response = client.get("/admin/enricher-stats")
        # 200 if the enricher is wired (most test setups),
        # 500 if the singleton can't be constructed (no
        # .env in unit tests), but never 404 -- the route
        # is registered.
        assert response.status_code != 404
