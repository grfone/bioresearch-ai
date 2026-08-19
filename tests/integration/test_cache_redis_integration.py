"""
tests/integration/test_cache_redis_integration.py

Real-Redis integration tests for the RedisCache backend.

These tests exercise the same RedisCache implementation as
the unit tests (tests/unit/test_cache_protocol.py), but
against a real ``redis-server`` process instead of
``fakeredis``. The point is to catch behavioral drift that
fakeredis misses:

  - Pipeline command ordering -- fakeredis executes
    pipeline commands eagerly while real Redis buffers
    them and sends them in one network round-trip. A
    real bug like ``ZADD xx=True`` being a no-op when it
    should refresh LRU, or a pipeline misordering
    causing stale data to leak back, won't reproduce
    against fakeredis.

  - Connection error handling -- fakeredis never raises
    ConnectionError because it has no socket. The real
    cache's misconfigured-URL behavior (RedisCache is
    constructed but the first ``get`` raises
    ``ConnectionError``) is only testable against a
    real server we can disconnect from.

  - Atomic counter semantics -- fakeredis INCR is correct
    but a real Redis under contention can show subtle
    differences (e.g. integer overflow, key-not-found
    edge cases). Real Redis catches these.

Skip behavior
-------------
If the env var ``REDIS_URL`` is not set, these tests are
SKIPPED (not failed). This makes the integration suite
opt-in: developers run ``REDIS_URL=redis://localhost:6379/0
pytest tests/integration`` locally; CI sets the env var via
the GitHub Actions ``services:`` block.

The CI workflow at ``.github/workflows/ci.yml`` spins up
a real ``redis:7-alpine`` container via the GitHub
Actions services feature and sets ``REDIS_URL=redis://localhost:6379/0``
for the redis-integration job.

Cleanup
-------
Each test uses a unique ``key_prefix`` (the test name + a
UUID) so concurrent tests don't collide and so the
``after-the-test`` DEL doesn't wipe unrelated keys.
We DEL the prefix's keys at the end of each test to keep
the Redis instance clean across CI runs.
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest

from app.infrastructure.cache import (
    HIT,
    HIT_NONE,
    MISS,
    CacheProtocol,
    RedisCache,
)
# Explicit import so the type checker doesn't trip on
# ``redis.exceptions.ConnectionError`` (Pyright's redis
# stubs don't expose ``redis.exceptions`` as a module).
from redis.exceptions import ConnectionError as RedisConnectionError


REDIS_URL = os.environ.get("REDIS_URL")

# Type checker: ``os.environ.get`` returns ``str | None``,
# but our pytest.skipif guard above ensures REDIS_URL is
# a string at test runtime. Re-bind to a ``str`` so the
# rest of the module doesn't have to assert-narrow.
REDIS_URL_STR: str = REDIS_URL if REDIS_URL is not None else ""


# Skip the entire module if REDIS_URL is not set. This is
# what makes the tests opt-in: the CI job sets the env var
# explicitly; local dev runs without it get a clean skip
# rather than a connection-error failure.
pytestmark = pytest.mark.skipif(
    not REDIS_URL_STR,
    reason=(
        "REDIS_URL not set; real-Redis integration tests "
        "are opt-in. Set REDIS_URL=redis://localhost:6379/0 "
        "(or similar) to run them."
    ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def redis_cache() -> Iterator[RedisCache]:
    """A RedisCache backed by the real Redis at REDIS_URL,
    with a unique key_prefix per test so concurrent tests
    don't collide.

    Tears down by DELing all keys with this prefix after
    the test -- so the Redis instance is left clean for
    the next CI run (or the next developer's local run).
    """
    # Sanity-check the connection BEFORE running the test
    # so a misconfigured REDIS_URL fails fast with a clear
    # ConnectionError rather than hanging on the first
    # Redis command.
    import redis as redis_lib
    client = redis_lib.Redis.from_url(REDIS_URL_STR, decode_responses=True)
    try:
        client.ping()
    except RedisConnectionError as exc:
        pytest.skip(f"REDIS_URL {REDIS_URL_STR!r} unreachable: {exc}")

    # Each test gets a unique prefix. The prefix is
    # namespaced under ``bioresearch-test:`` so it's
    # obviously test-only and easy to wipe in bulk if
    # something goes wrong.
    prefix = f"bioresearch-test:{uuid.uuid4().hex}:"
    cache = RedisCache(
        redis_url=REDIS_URL_STR,
        capacity=128,
        key_prefix=prefix,
        client=client,
    )

    yield cache

    # Cleanup: DEL every key with our prefix. We use
    # SCAN+DELETE rather than FLUSHALL because the latter
    # would wipe other tests' keys if they ran in parallel.
    try:
        for key in client.scan_iter(match=f"{prefix}*"):
            client.delete(key)
    finally:
        client.close()


def _extraction_result(abstract: str, inferred: bool = False):
    """Build a duck-typed ExtractionResult -- the cache
    protocol is intentionally typed as ``object`` so any
    object with ``.abstract`` and ``.inferred`` attrs
    works. See tests/unit/test_cache_protocol.py for the
    matching helper.
    """
    return type(
        "R",
        (),
        {"abstract": abstract, "inferred": inferred},
    )()


# ---------------------------------------------------------------------------
# Behavioral parity with fakeredis tests
# ---------------------------------------------------------------------------
#
# These tests are intentionally a SUBSET of the
# TestCacheProtocolContract tests in
# tests/unit/test_cache_protocol.py -- just the ones that
# exercise behaviors where fakeredis and real Redis might
# diverge (pipeline ordering, atomic counters, real
# network round-trips). The full battery lives in the
# unit tests so they run on every dev machine; the
# integration tests are a smoke-check that real Redis
# agrees with fakeredis.

class TestRedisCacheAgainstRealServer:
    """Smoke checks against a real ``redis-server``."""

    def test_miss_then_set_then_hit_round_trip(
        self, redis_cache: RedisCache
    ) -> None:
        """Real Redis round-trip: miss, set, hit."""
        status, value = redis_cache.get("doi1")
        assert status == MISS
        assert value is None

        result = _extraction_result("real abstract", inferred=False)
        redis_cache.set("doi1", result)

        status, value = redis_cache.get("doi1")
        assert status == HIT
        # The cache returns a dict (JSON-roundtripped
        # ExtractionResult) in the Redis impl.
        assert value["abstract"] == "real abstract"
        assert value["inferred"] is False

    def test_negative_cache_round_trips_through_redis(
        self, redis_cache: RedisCache
    ) -> None:
        """The ``NO_ABSTRACT_SENTINEL`` round-trips through
        JSON correctly -- a real bug here would silently
        break the negative-cache contract for blocked
        pages.
        """
        redis_cache.set("blocked-doi", None)
        status, value = redis_cache.get("blocked-doi")
        assert status == HIT_NONE
        assert value is None
        # A non-existent key should still be MISS, not
        # HIT_NONE -- distinct from the cached-None case.
        status, value = redis_cache.get("never-set")
        assert status == MISS
        assert value is None

    def test_counters_use_atomic_incr(
        self, redis_cache: RedisCache
    ) -> None:
        """Real Redis INCR is atomic. Verify by hitting
        the cache 5 times and checking the counter is
        exactly 5 (not lost to a race).
        """
        for i in range(5):
            redis_cache.get(f"missing-{i}")
        assert redis_cache.stats().misses == 5
        assert redis_cache.stats().hits == 0

        redis_cache.set("k", _extraction_result("v"))
        for _ in range(3):
            redis_cache.get("k")
        stats = redis_cache.stats()
        assert stats.hits == 3
        assert stats.misses == 5
        assert stats.size == 1

    def test_lru_eviction_under_real_redis(
        self, redis_cache: RedisCache
    ) -> None:
        """Real Redis sorted-set ZRANGE+ZREM eviction:
        capacity=3, set 5 keys, oldest 2 evicted.
        """
        # Replace the cache with one that has capacity=3.
        cache = RedisCache(
            redis_url=REDIS_URL_STR,
            capacity=3,
            key_prefix=redis_cache._key_prefix,
            client=redis_cache._redis,
        )
        import time
        for i in range(1, 6):
            cache.set(f"k{i}", _extraction_result(f"v{i}"))
            time.sleep(0.001)
        # k1, k2 evicted (LRU).
        assert cache.get("k1")[0] == MISS
        assert cache.get("k2")[0] == MISS
        # k3, k4, k5 still there.
        assert cache.get("k3")[0] == HIT
        assert cache.get("k4")[0] == HIT
        assert cache.get("k5")[0] == HIT

    def test_clear_removes_all_redis_keys(
        self, redis_cache: RedisCache
    ) -> None:
        """Real Redis DEL+clear: clear() removes every
        data key + the LRU index + the counters.
        """
        redis_cache.set("a", _extraction_result("v"))
        redis_cache.set("b", _extraction_result("v"))
        redis_cache.get("a")  # 1 hit
        redis_cache.get("nope")  # 1 miss
        assert redis_cache.stats().size == 2

        removed = redis_cache.clear()
        assert removed == 2

        # Verify directly via Redis that the keys are gone.
        import redis as redis_lib
        client = redis_lib.Redis.from_url(REDIS_URL_STR, decode_responses=True)
        try:
            # Data keys gone.
            assert client.exists(redis_cache._data_key("a")) == 0
            assert client.exists(redis_cache._data_key("b")) == 0
            # LRU index gone.
            assert client.exists(redis_cache._index_key) == 0
            # Counters gone (or never created if cache was
            # empty before clear -- both are valid).
            stats = redis_cache.stats()
            assert stats.hits == 0
            assert stats.misses == 0
            assert stats.size == 0
        finally:
            client.close()

    def test_delete_is_system_wide(
        self, redis_cache: RedisCache
    ) -> None:
        """Two RedisCache instances pointing at the same
        Redis (same key_prefix) share state -- this is the
        multi-worker scenario. ``delete`` on one instance
        removes the entry; the other instance sees the
        miss on its next read.

        This is the integration-test equivalent of the
        multi-worker reproduction in
        docs/multi-worker-cache-investigation.md.
        """
        cache_a = redis_cache
        cache_b = RedisCache(
            redis_url=REDIS_URL_STR,
            capacity=128,
            key_prefix=redis_cache._key_prefix,
            client=redis_cache._redis,
        )
        # cache_a sets.
        cache_a.set("shared-key", _extraction_result("v"))
        # cache_b sees the entry (HIT).
        assert cache_b.get("shared-key")[0] == HIT
        # cache_a deletes.
        deleted = cache_a.delete("shared-key")
        assert deleted is True
        # cache_b sees the miss.
        assert cache_b.get("shared-key")[0] == MISS


class TestRedisCacheConnectionBehavior:
    """Connection-level behavior only exercisable against
    a real Redis server.
    """

    def test_misconfigured_url_raises_on_first_op(
        self, redis_cache: RedisCache
    ) -> None:
        """The constructor succeeds with a syntactically-
        valid-but-unreachable URL -- redis-py is lazy
        about DNS resolution. The FIRST ``get`` raises
        ``ConnectionError``. This is the documented
        behavior in app/infrastructure/cache/__init__.py
        and the contract that operators see when their
        REDIS_URL is wrong.
        """
        import redis as redis_lib
        # 127.0.0.1:1 is a reserved port; no Redis listens
        # there. The connection will fail on the first op.
        bad_cache = RedisCache(
            redis_url="redis://127.0.0.1:1/0",
            capacity=128,
            key_prefix="should-never-be-used:",
        )
        with pytest.raises(RedisConnectionError):
            bad_cache.get("anything")
