"""
tests/unit/test_research_assistant_dependency.py

Tests that the API routes depend on the canonical
``get_research_assistant()`` provider from
``app.config.container``, not on local copies.

Background
----------
Prior to this refactor, ``app/api/routes/search.py``
and ``app/api/routes/workspace.py`` each defined their
own ``get_research_assistant()`` function that called
``Container.build()`` on every request -- building a
fresh ``ResearchAssistant`` instance, including a new
orchestrator, search use case, summarizer, and report
generator. Each call also re-constructed the workspace
orchestrator and the search use case.

The canonical ``get_research_assistant()`` in
``app/config/container`` solves both problems: it
caches the ``ResearchAssistant`` instance at module
scope so the second hit reuses the previous instance,
and it points every dependency injection at the same
singleton.

This test pins:
  - Both routes import ``get_research_assistant`` from
    ``app.config.container``.
  - Neither route defines its own local
    ``get_research_assistant`` (which would shadow the
    import).
  - Neither route imports ``Container`` (the class
    whose classmethod is wrapped by the canonical
    provider).
  - The FastAPI dependency graph routes both routes
    through the canonical provider, so HTTP requests
    get a cached singleton.
"""
from __future__ import annotations

import inspect
import sys

from app.api.routes import search as search_route
from app.api.routes import workspace as workspace_route
from app.config.container import get_research_assistant


def _route_module_uses_canonical_dependency(route_module) -> None:
    """Pin the dedupe contract for a single route module.

    Verifies that:

      1. The module imports ``get_research_assistant``
         from ``app.config.container`` (rather than
         defining its own local copy).
      2. The module does NOT import the ``Container``
         class -- ``Container`` is what the local copy
         would call; importing it would mean the route
         could re-introduce a local function by accident.
    """
    # 1) ``get_research_assistant`` is importable from the
    # route module's namespace (because Python re-exports
    # imports).
    assert hasattr(route_module, "get_research_assistant"), (
        f"{route_module.__name__} must expose "
        f"get_research_assistant (imported from container)"
    )
    # The function must be the canonical container one,
    # not a local copy. Use object identity (``is``) and
    # ``__code__.co_filename`` -- ``__qualname__`` would
    # only show ``get_research_assistant`` regardless of
    # where the function was defined, so it's not a
    # reliable signal here.
    canonical_func = get_research_assistant
    assert route_module.get_research_assistant is canonical_func, (
        f"{route_module.__name__}.get_research_assistant "
        f"must be the canonical container provider "
        f"(identity check), not a local copy"
    )
    assert (
        route_module.get_research_assistant.__code__.co_filename
        == canonical_func.__code__.co_filename
    ), (
        f"{route_module.__name__}.get_research_assistant "
        f"must be defined in container.py "
        f"(co_filename mismatch)"
    )

    # 2) The module must not import ``Container`` -- that
    # would mean the route is still wired to the
    # non-cached ``Container.build()`` classmethod.
    route_source = inspect.getsource(route_module)
    assert "from app.config.container import Container" not in (
        route_source
    ), (
        f"{route_module.__name__} must not import "
        f"``Container`` directly -- the canonical "
        f"``get_research_assistant`` provider in "
        f"``app.config.container`` should be used "
        f"instead so the cached singleton pattern is "
        f"preserved."
    )


def test_search_route_uses_canonical_dependency():
    """The /search route must use the canonical dependency."""
    _route_module_uses_canonical_dependency(search_route)


def test_workspace_route_uses_canonical_dependency():
    """The /workspaces routes must use the canonical dependency."""
    _route_module_uses_canonical_dependency(workspace_route)


def test_canonical_dependency_is_a_module_level_singleton():
    """The canonical ``get_research_assistant`` must be
    module-level so it survives across requests. A
    class-level or instance-level implementation would
    defeat the purpose of the dedupe (the singleton is
    the entire reason for centralising the provider).
    """
    # The canonical provider lives in
    # ``app.config.container``. Verify it uses the
    # module-level ``_assistant`` cache.
    source = inspect.getsource(sys.modules["app.config.container"])
    assert "_assistant: ResearchAssistant | None = None" in source, (
        "the canonical get_research_assistant must use a "
        "module-level cache (currently named ``_assistant``) "
        "to survive across requests"
    )
    assert "global _assistant" in source, (
        "the canonical get_research_assistant must "
        "declare ``global _assistant`` to write to the "
        "module-level cache"
    )


def test_no_local_get_research_assistant_in_route_modules():
    """Belt-and-braces: the route modules' ``__dict__`` must
    NOT contain a local ``get_research_assistant``
    function. This guards against a future refactor that
    accidentally re-introduces the duplicate.

    Python's module ``__dict__`` contains both imported
    names AND locally defined names. By checking the
    function's ``__module__`` attribute (which records
    where the function was originally defined), we can
    tell which names were imported vs which were
    defined locally.
    """
    for route_module in (search_route, workspace_route):
        func = route_module.get_research_assistant
        assert func.__module__ == "app.config.container", (
            f"{route_module.__name__}.get_research_assistant "
            f"must be imported from app.config.container "
            f"(got __module__={func.__module__!r}, meaning the "
            f"function is locally defined)"
        )
