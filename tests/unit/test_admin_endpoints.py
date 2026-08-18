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

        # Set up deterministic counts: 2 CREATED, 1
        # PAPERS_RETRIEVED, 0 everywhere else.
        counts = {state.value: 0 for state in WorkspaceState}
        counts["CREATED"] = 2
        counts["PAPERS_RETRIEVED"] = 1
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
        assert body["CREATED"] == 2
        assert body["PAPERS_RETRIEVED"] == 1
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

        # Sparse input: only REPORTED has a count.
        fake = self._fake_orchestrator_with_counts(
            {"REPORTED": 4}
        )

        monkeypatch.setattr(
            container, "get_workspace_orchestrator",
            lambda: fake,
        )

        response = client.get("/admin/orchestrator-stats")
        body = response.json()

        # Sparse input was 1 key; the endpoint should have
        # zero-filled all the OTHER states to 0. REPORTED
        # itself stays at 4.
        assert body["REPORTED"] == 4
        for state in WorkspaceState:
            if state.value == "REPORTED":
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

        # Create 3 CREATED workspaces
        for _ in range(3):
            session = ResearchSession(
                question=ResearchQuestion(question="x"),
                state=WorkspaceState.CREATED,
            )
            repo.create(session)

        # Create 1 PAPERS_RETRIEVED workspace
        session = ResearchSession(
            question=ResearchQuestion(question="y"),
            state=WorkspaceState.PAPERS_RETRIEVED,
        )
        repo.create(session)

        counts = repo.workspace_state_counts()
        assert counts["CREATED"] == 3
        assert counts["PAPERS_RETRIEVED"] == 1
        # All other states are zero.
        for state in WorkspaceState:
            if state.value not in ("CREATED", "PAPERS_RETRIEVED"):
                assert counts[state.value] == 0
