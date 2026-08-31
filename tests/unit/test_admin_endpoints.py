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

from dataclasses import dataclass

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


class TestOrchestratorStatsEndpoint:
    """GET /admin/orchestrator-stats.

    The endpoint delegates to WorkspaceOrchestrator.state_counts(),
    which calls workspace_state_counts() on the repository.
    We mock the orchestrator to return deterministic counts
    so the test is hermetic.
    """

    def _fake_orchestrator_with_counts(self, counts: dict[str, int]):
        """Build a fake orchestrator whose state_counts()
        returns the given counts dict. Mirrors the public
        method so the route can call it directly.
        """
        from app.config import container

        class FakeOrchestrator:
            def __init__(self, counts):
                self._counts = counts

            def state_counts(self) -> dict[str, int]:
                return dict(self._counts)

        fake = FakeOrchestrator(counts)
        return fake

    def test_returns_counts_for_each_state(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """When the orchestrator is wired, the endpoint
        returns the per-state counts. Verifies the contract:
        every WorkspaceState member is represented, plus
        the convenience ``total`` field.
        """
        from app.config import container
        import app.api.routes.admin as admin_mod
        from app.core.enums.workspace_state import WorkspaceState

        # Set up deterministic counts: 2 INITIAL, 1
        # INTERMEDIATE, 0 everywhere else.
        counts = {state.value: 0 for state in WorkspaceState}
        counts["INITIAL"] = 2
        counts["INTERMEDIATE"] = 1
        fake = self._fake_orchestrator_with_counts(counts)

        # The endpoint imports get_workspace_orchestrator
        # inside the function (defensive import), so we
        # only need to patch the container module's symbol.
        monkeypatch.setattr(
            container, "get_workspace_orchestrator",
            lambda: fake,
        )

        response = client.get("/admin/orchestrator-stats")
        assert response.status_code == 200
        body = response.json()

        # Every WorkspaceState member is present.
        for state in WorkspaceState:
            assert state.value in body, (
                f"state {state.value} missing from response"
            )

        # Counts are passed through verbatim.
        assert body["INITIAL"] == 2
        assert body["INTERMEDIATE"] == 1
        # Total equals sum of state counts (3 here).
        assert body["total"] == 3

    def test_zero_fills_unused_states(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """Even when the orchestrator returns a sparse dict
        (some states missing), the endpoint zero-fills
        every WorkspaceState. Operators get a complete FSM
        picture, not a sparse dict that hides unused states.
        """
        from app.config import container
        import app.api.routes.admin as admin_mod
        from app.core.enums.workspace_state import WorkspaceState

        # Sparse input: only FINAL has a count.
        fake = self._fake_orchestrator_with_counts(
            {"FINAL": 4}
        )

        monkeypatch.setattr(
            container, "get_workspace_orchestrator",
            lambda: fake,
        )

        response = client.get("/admin/orchestrator-stats")
        body = response.json()

        # Sparse input was 1 key; the endpoint should have
        # zero-filled all the OTHER states to 0. FINAL
        # itself stays at 4.
        assert body["FINAL"] == 4
        for state in WorkspaceState:
            if state.value == "FINAL":
                continue
            assert body[state.value] == 0, (
                f"state {state.value} expected 0 (zero-filled), "
                f"got {body[state.value]}"
            )
        assert body["total"] == 4

    def test_endpoint_under_admin_prefix(
        self, client: TestClient,
    ):
        """Catches accidental route-registration changes
        that would break operator dashboards pointed at
        the canonical URL.
        """
        response = client.get("/admin/orchestrator-stats")
        assert response.status_code != 404


class TestWorkspaceStateCountsRepository:
    """Verify the repository's workspace_state_counts()
    method directly (without going through the admin route).
    """

    def test_in_memory_zero_fills_every_state(self):
        """The in-memory repo returns every WorkspaceState
        member in the dict, even when no workspaces exist."""
        from app.core.enums.workspace_state import WorkspaceState
        from app.infrastructure.storage.in_memory_workspace_repository import (
            InMemoryWorkspaceRepository,
        )

        repo = InMemoryWorkspaceRepository()
        counts = repo.workspace_state_counts()
        # Every WorkspaceState is represented.
        for state in WorkspaceState:
            assert state.value in counts
            assert counts[state.value] == 0

    def test_in_memory_counts_existing_sessions(self):
        """Add a few sessions in different states and verify
        the counts match.
        """
        from app.core.enums.workspace_state import WorkspaceState
        from app.domain.entities.research_question import ResearchQuestion
        from app.domain.entities.research_session import (
            ResearchSession,
        )
        from app.infrastructure.storage.in_memory_workspace_repository import (
            InMemoryWorkspaceRepository,
        )

        repo = InMemoryWorkspaceRepository()

        # Create 3 INITIAL workspaces
        for _ in range(3):
            session = ResearchSession(
                question=ResearchQuestion(question="x"),
                state=WorkspaceState.INITIAL,
            )
            repo.create(session)

        # Create 1 INTERMEDIATE workspace
        session = ResearchSession(
            question=ResearchQuestion(question="y"),
            state=WorkspaceState.INTERMEDIATE,
        )
        repo.create(session)

        counts = repo.workspace_state_counts()
        assert counts["INITIAL"] == 3
        assert counts["INTERMEDIATE"] == 1
        # All other states are zero.
        for state in WorkspaceState:
            if state.value not in ("INITIAL", "INTERMEDIATE"):
                assert counts[state.value] == 0


class TestForceRefreshEndpoint:
    """POST /admin/papers/{doi}/force-refresh.

    The endpoint invalidates a single LRU cache entry
    and re-fetches the abstract. Two branches:

    - Hit: there was a cache entry for the DOI; we
      removed it before re-fetching.
    - Miss: the DOI was never cached; we just fetch.

    And two contract branches:

    - Enricher wired: invalidate + fetch happen.
    - Enricher disabled (None): returns the disabled
      payload.
    """

    def _fake_resolver_with_enricher(self, fetch_results: dict[str, object]):
        """Build a fake resolver whose enricher has
        deterministic behavior: any DOI in
        ``fetch_results`` returns that value, any other
        DOI returns None.

        Uses a fake ExtractionResult for the dict values
        (since the real fetch returns ExtractionResult,
        not a bare string, after the LLMExtractor
        threading).
        """
        from dataclasses import dataclass

        @dataclass
        class StubResult:
            abstract: str

        @dataclass
        class FakeEnricher:
            cache: dict
            seed_map: dict
            cache_hits: int = 0
            cache_misses: int = 0

            def invalidate(self, doi: str) -> bool:
                from app.infrastructure.pubmed.abstract_enricher import (
                    AbstractEnricher,
                )
                key = AbstractEnricher._normalize_doi(doi)
                if key in self.cache:
                    del self.cache[key]
                    return True
                return False

            def fetch(self, doi: str):
                from app.infrastructure.pubmed.abstract_enricher import (
                    AbstractEnricher,
                )
                key = AbstractEnricher._normalize_doi(doi)
                # Look up in the wrapped fixture map (which
                # may be a StubResult, None, or missing).
                # If missing, default to None (the contract
                # for "DOI has no abstract").
                if doi in self.seed_map:
                    value = self.seed_map[doi]
                elif key in self.seed_map:
                    value = self.seed_map[key]
                else:
                    value = None
                self.cache[key] = value
                return value

            def cache_stats(self):
                return {
                    "hits": self.cache_hits,
                    "misses": self.cache_misses,
                    "size": len(self.cache),
                    "capacity": 256,
                }

        @dataclass
        class FakeResolver:
            _abstract_enricher: object

        # The cache starts empty; tests that need a "was
        # cached" pre-condition can populate the cache
        # directly. ``seed_map`` is what ``fetch()`` returns
        # for each DOI (the test's "what the publisher would
        # respond with" fixture). The cache is separate
        # from the seed map so tests that assert "cache is
        # empty" can do so without also having to assert
        # "fetch returns None".
        seed_map = {}
        for k, v in fetch_results.items():
            if v is None:
                seed_map[k] = None
            elif isinstance(v, StubResult):
                seed_map[k] = v
            else:
                seed_map[k] = StubResult(abstract=str(v))
        enricher = FakeEnricher(cache={}, seed_map=seed_map)
        return FakeResolver(_abstract_enricher=enricher)

    def test_force_refresh_invalidates_and_refetches(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """Hit case: DOI was cached, we invalidate it,
        then fetch returns the new abstract.
        """
        from app.config import container
        import app.api.routes.admin as admin_mod

        fake = self._fake_resolver_with_enricher(
            {"10.1038/nature14539": "The new abstract from a re-fetch."}
        )
        # Seed the cache from the seed_map so the test
        # starts with a "was cached" entry. The cache
        # itself starts empty in the helper.
        fake._abstract_enricher.cache["10.1038/nature14539"] = (
            fake._abstract_enricher.seed_map["10.1038/nature14539"]
        )

        monkeypatch.setattr(
            container, "get_identifier_resolver",
            lambda: fake,
        )

        response = client.post(
            "/admin/papers/refresh/10.1038/nature14539",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["doi"] == "10.1038/nature14539"
        # The cache had an entry for this DOI, so
        # invalidate_returned must be True.
        assert body["invalidate_returned"] is True
        # The re-fetch populated the cache with the
        # new value.
        assert body["abstract_length"] == len(
            "The new abstract from a re-fetch."
        )

    def test_force_refresh_unknown_doi_does_not_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """Even when the DOI was never cached, the
        endpoint should re-fetch (and return the new
        value). We don't want a 404 on miss -- the
        point of force-refresh is to bypass the cache
        and retry the publisher.
        """
        from app.config import container
        import app.api.routes.admin as admin_mod

        fake = self._fake_resolver_with_enricher(
            {"10.1038/nature14539": "fetched abstract"}
        )
        # Cache is empty for this DOI.
        monkeypatch.setattr(
            container, "get_identifier_resolver",
            lambda: fake,
        )

        response = client.post(
            "/admin/papers/refresh/10.1038/nature14539",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["invalidate_returned"] is False
        assert body["abstract_length"] > 0

    def test_force_refresh_handles_url_encoded_doi(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """DOIs may contain ``/`` (after the ``10.`` prefix).
        When a client passes a percent-encoded DOI like
        ``10.1038%2Fnature14539`` to a path parameter, the
        endpoint should unquote it before invalidating.
        """
        from app.config import container

        fake = self._fake_resolver_with_enricher(
            {"10.1038/nature14539": "abstract text"}
        )
        monkeypatch.setattr(
            container, "get_identifier_resolver",
            lambda: fake,
        )

        response = client.post(
            "/admin/papers/refresh/10.1038%2Fnature14539",
        )
        assert response.status_code == 200
        body = response.json()
        # The endpoint unquotes the path parameter before
        # returning it in the response.
        assert body["doi"] == "10.1038/nature14539"

    def test_force_refresh_returns_disabled_when_enricher_none(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """If the enricher isn't wired, returns the
        same disabled payload as the enricher-stats
        endpoint.
        """
        from app.config import container

        @dataclass
        class FakeResolver:
            _abstract_enricher: object = None

        fake = FakeResolver(_abstract_enricher=None)
        monkeypatch.setattr(
            container, "get_identifier_resolver",
            lambda: fake,
        )

        response = client.post(
            "/admin/papers/refresh/10.1038/nature14539",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "disabled"


class TestClearCacheEndpoint:
    """DELETE /admin/enricher-cache."""

    def test_clear_cache_drops_all_entries(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """Cached entries are dropped; stats_after
        shows size=0 + hits=0 + misses=0.
        """
        from dataclasses import dataclass
        from app.config import container

        @dataclass
        class FakeEnricher:
            cache: dict
            cache_hits: int = 5
            cache_misses: int = 2

            def clear_cache(self) -> None:
                self.cache.clear()
                self.cache_hits = 0
                self.cache_misses = 0

            def cache_stats(self) -> dict:
                return {
                    "hits": self.cache_hits,
                    "misses": self.cache_misses,
                    "size": len(self.cache),
                    "capacity": 256,
                }

        @dataclass
        class FakeResolver:
            _abstract_enricher: object

        enricher = FakeEnricher(
            cache={"a": "x", "b": "y", "c": "z"},
            cache_hits=5,
            cache_misses=2,
        )
        fake = FakeResolver(_abstract_enricher=enricher)
        monkeypatch.setattr(
            container, "get_identifier_resolver",
            lambda: fake,
        )

        response = client.delete("/admin/enricher-cache")
        assert response.status_code == 200
        body = response.json()
        assert body["cleared"] is True
        assert body["stats_after"]["hits"] == 0
        assert body["stats_after"]["misses"] == 0
        assert body["stats_after"]["size"] == 0
        # Capacity is not reset.
        assert body["stats_after"]["capacity"] == 256

    def test_clear_cache_returns_disabled_when_enricher_none(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """Same disabled-payload contract as the other
        /admin/* endpoints.
        """
        from dataclasses import dataclass
        from app.config import container

        @dataclass
        class FakeResolver:
            _abstract_enricher: object = None

        fake = FakeResolver()
        monkeypatch.setattr(
            container, "get_identifier_resolver",
            lambda: fake,
        )

        response = client.delete("/admin/enricher-cache")
        assert response.status_code == 200
        assert response.json()["status"] == "disabled"
