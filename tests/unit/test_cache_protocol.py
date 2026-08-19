"""
test_cache_protocol.py

Unit tests for the abstract-enricher cache backend
abstraction (``app.infrastructure.cache``).

Coverage
--------

- ``InMemoryLRUCache``: the default in-process LRU. Tests
  cover the basic LRU invariants (LRU eviction, miss vs.
  hit_none distinction, capacity=0 disables the cache) and
  the contract that ``cache_stats()`` returns hits/misses/
  size/capacity.

- ``RedisCache``: the multi-worker fix. Tests use
  ``fakeredis`` to simulate a Redis server in-process. The
  tests cover LRU eviction, negative-cache handling (the
  ``__bioresearch_no_abstract__`` sentinel), atomic counter
  increments, and the system-wide clear.

- ``make_cache`` factory: tests the string-to-impl mapping
  (memory vs. redis) and the validation that
  ``CACHE_BACKEND=redis`` requires ``REDIS_URL``.

- ``TestCacheProtocolContract``: a parameterized test that
  runs the same battery of operations against every cache
  implementation. This guarantees that the InMemory and
  Redis backends are behaviorally equivalent (the contract
  they implement) even though their internals are very
  different. If you add a third backend (e.g. memcached),
  this test catches you if the new backend doesn't match
  the contract.

The tests use ``fakeredis>=2.20`` (added as a dev dep).
The fakeredis library is a Python in-memory Redis
implementation that's API-compatible with the redis-py
client. It supports ZADD with NX/XX, INCR, GET, SET,
DEL, ZCARD, ZRANGE, ZREM, pipelining -- everything we use.

These tests do NOT require a running Redis server. A
separate integration test (not in this file, since it
needs a live Redis) would verify the implementation against
a real redis-server process. The investigation doc explains
how to run that.
"""

from __future__ import annotations

import fakeredis
import pytest

from app.infrastructure.cache import (
    HIT,
    HIT_NONE,
    MISS,
    CacheProtocol,
    CacheStats,
    InMemoryLRUCache,
    RedisCache,
    make_cache,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_redis_client() -> fakeredis.FakeRedis:
    """A fresh fakeredis instance per test. We use
    ``decode_responses=True`` so the RedisCache's ZADD/etc.
    calls match the fakeredis behavior (no bytes vs str
    confusion).
    """
    return fakeredis.FakeRedis(decode_responses=True)


def _abstract_of(value):
    """Read ``.abstract`` from a cache value, whether it's
    an ExtractionResult (in-memory impl) or a dict (Redis
    impl after JSON round-trip).
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("abstract")
    return getattr(value, "abstract", None)


def _inferred_of(value):
    """Read ``.inferred`` from a cache value (dict or object)."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("inferred")
    return getattr(value, "inferred", None)


def _make_extraction_result(abstract: str, inferred: bool = False):
    """Build a duck-typed ExtractionResult. We don't import
    the real ExtractionResult class here because the
    CacheProtocol is intentionally typed as ``object`` to
    keep the protocol decoupled from any specific value
    type. A simple namespace with the two attributes the
    protocol requires (``abstract`` and ``inferred``) is
    enough to drive the tests.
    """
    return type(
        "R",
        (),
        {"abstract": abstract, "inferred": inferred},
    )()


# ---------------------------------------------------------------------------
# TestCacheProtocolContract -- parameterized across every impl
# ---------------------------------------------------------------------------

# Add new cache implementations here as they're added. The
# parametrized test below will then automatically cover them.
ALL_IMPLEMENTATIONS = pytest.mark.parametrize(
    "cache_factory",
    [
        pytest.param(
            lambda: InMemoryLRUCache(capacity=3),
            id="in-memory",
        ),
        pytest.param(
            lambda: _make_fake_redis_cache(),
            id="redis",
        ),
    ],
)


def _make_fake_redis_cache() -> RedisCache:
    """Helper: build a RedisCache backed by a fresh fakeredis
    instance. Defined at module level so pytest.mark.parametrize
    can pickle it (lambdas in module scope sometimes hit
    pickling issues in older pytest versions).
    """
    client = fakeredis.FakeRedis(decode_responses=True)
    return RedisCache(
        redis_url="redis://fake/",
        capacity=3,
        client=client,
    )


# We parametrize the contract test over a callable that
# returns a fresh cache instance. The callable is invoked
# once per test (per parametrize expansion), so each test
# gets an isolated cache. This pattern is more portable
# than ``pytest.lazy_fixture`` (which requires pytest >= 8.0
# in some configurations).
def _in_memory_cache():
    return InMemoryLRUCache(capacity=3)


def _fake_redis_cache_callable():
    return _make_fake_redis_cache()


ALL_IMPLEMENTATIONS = pytest.mark.parametrize(
    "cache_factory",
    [_in_memory_cache, _fake_redis_cache_callable],
    ids=["in-memory", "redis"],
)


@ALL_IMPLEMENTATIONS
class TestCacheProtocolContract:
    """Every cache implementation must satisfy the same
    contract. This test class runs the same battery of
    assertions against every impl -- if RedisCache ever
    diverges from InMemoryLRUCache behaviorally, this test
    catches it.

    Coverage:

      - miss on empty cache
      - miss after explicit delete
      - hit + hit_none distinction
      - LRU eviction when over capacity
      - clear resets state
      - capacity=0 disables the cache (no hits/misses counted)
    """

    # ``cache_factory`` is injected by the parametrize
    # decorator above. We call it at the start of each
    # test to get a fresh cache instance -- this matters
    # because the tests are stateful (they ``set`` values,
    # which leaks between tests if shared).
    @pytest.fixture(autouse=True)
    def _cache(self, cache_factory) -> CacheProtocol:
        self._cache_instance: CacheProtocol = cache_factory()
        return self._cache_instance

    @property
    def cache(self) -> CacheProtocol:
        return self._cache_instance

    def test_miss_on_empty_cache(self) -> None:
        status, value = self.cache.get("nonexistent-key")
        assert status == MISS
        assert value is None

    def test_set_then_get_round_trips_value(self) -> None:
        result = _make_extraction_result("abstract text", inferred=False)
        self.cache.set("key1", result)
        status, value = self.cache.get("key1")
        assert status == HIT
        # ``value`` is typed as ``object | None`` in the
        # protocol, but the in-memory impl returns the
        # ExtractionResult unchanged and the Redis impl
        # returns a dict (which we access via
        # ``.get("abstract")`` for back-compat). To assert
        # against both, we use a small helper.
        assert _abstract_of(value) == "abstract text"
        assert _inferred_of(value) is False

    def test_set_none_round_trips_as_hit_none(self) -> None:
        # The "negative cache" case -- a DOI whose publisher
        # returned a blocked page. We cache the None so the
        # next fetch doesn't re-do the HTTP request.
        self.cache.set("key-with-no-abstract", None)
        status, value = self.cache.get("key-with-no-abstract")
        assert status == HIT_NONE
        assert value is None

    def test_distinguishes_none_from_absent(self) -> None:
        # A set-None entry is distinct from "not cached".
        self.cache.set("present", None)
        present_status, _ = self.cache.get("present")
        absent_status, _ = self.cache.get("absent")
        assert present_status == HIT_NONE
        assert absent_status == MISS

    def test_delete_removes_entry(self) -> None:
        self.cache.set("k", _make_extraction_result("v"))
        assert self.cache.delete("k") is True
        # Second delete returns False (idempotent).
        assert self.cache.delete("k") is False
        status, _ = self.cache.get("k")
        assert status == MISS

    def test_delete_unknown_returns_false(
        self, cache: CacheProtocol
    ) -> None:
        assert self.cache.delete("never-existed") is False

    def test_lru_evicts_oldest_when_over_capacity(self) -> None:
        # capacity=3 in both impls. Add 5 keys; the 2
        # oldest should be evicted.
        for i in range(1, 6):
            self.cache.set(f"k{i}", _make_extraction_result(f"v{i}"))
            # Microsecond sleep to ensure monotonic
            # timestamps differ (matters for the Redis impl
            # which uses time.monotonic() for the LRU score).
            import time
            time.sleep(0.001)

        # k1, k2 should be evicted.
        assert self.cache.get("k1")[0] == MISS
        assert self.cache.get("k2")[0] == MISS
        # k3, k4, k5 should still be in the cache.
        assert self.cache.get("k3")[0] == HIT
        assert self.cache.get("k4")[0] == HIT
        assert self.cache.get("k5")[0] == HIT

    def test_lru_refresh_on_get(self) -> None:
        # With capacity=3, the LRU is whichever key was
        # least-recently-get or -set. After touching k1
        # again, it should be promoted to MRU; k2 (which
        # was previously newer than k1) should become the
        # new LRU and be evicted by the 4th insert.
        import time
        for i in range(1, 4):
            self.cache.set(f"k{i}", _make_extraction_result(f"v{i}"))
            time.sleep(0.001)
        # Touch k1 to refresh its LRU position.
        self.cache.get("k1")
        time.sleep(0.001)
        # Insert k4. With capacity=3, the LRU (k2) should
        # be evicted; k1, k3, k4 should remain.
        self.cache.set("k4", _make_extraction_result("v4"))
        assert self.cache.get("k1")[0] == HIT
        assert self.cache.get("k2")[0] == MISS
        assert self.cache.get("k3")[0] == HIT
        assert self.cache.get("k4")[0] == HIT

    def test_clear_resets_state(self) -> None:
        self.cache.set("k1", _make_extraction_result("v1"))
        self.cache.set("k2", _make_extraction_result("v2"))
        # Force at least one miss + one hit so the counters
        # are non-zero.
        self.cache.get("nonexistent")
        self.cache.get("k1")
        # Sanity: stats are non-zero before clear.
        stats_before = self.cache.stats()
        assert stats_before.size > 0
        assert stats_before.hits > 0

        removed = self.cache.clear()
        assert removed == 2
        # Counters are reset. The ``clear`` method is
        # responsible for zeroing out the hit/miss counters
        # -- not for the entries disappearing (which the
        # next ``get`` would tell us, but that would also
        # increment the miss counter and muddle the
        # assertion). So we check stats BEFORE doing any
        # post-clear lookups.
        stats_after = self.cache.stats()
        assert stats_after.hits == 0  # cleared
        assert stats_after.misses == 0  # cleared
        assert stats_after.size == 0
        # Sanity: a fresh ``get`` after the clear returns
        # MISS (the entry is genuinely gone, not just
        # masked).
        assert self.cache.get("k1")[0] == MISS
        assert self.cache.get("k2")[0] == MISS

    def test_stats_after_miss_and_hit(self) -> None:
        # Empty cache -- both counters zero, size zero.
        assert self.cache.stats() == CacheStats(
            hits=0, misses=0, size=0, capacity=3
        )
        # Miss -- misses=1.
        self.cache.get("nope")
        assert self.cache.stats() == CacheStats(
            hits=0, misses=1, size=0, capacity=3
        )
        # Set + hit -- hits=1, size=1.
        self.cache.set("k", _make_extraction_result("v"))
        self.cache.get("k")
        assert self.cache.stats() == CacheStats(
            hits=1, misses=1, size=1, capacity=3
        )


# ---------------------------------------------------------------------------
# TestInMemoryLRUCache -- impl-specific behavior
# ---------------------------------------------------------------------------

class TestInMemoryLRUCache:
    """In-memory implementation -- the historical default."""

    def test_capacity_zero_disables_cache(self) -> None:
        """``cache_size=0`` means the cache is off. Every
        ``get`` returns MISS but no counters increment
        (matching the historical contract preserved by
        ``AbstractEnricher.test_cache_size_zero_disables_caching``).
        """
        cache = InMemoryLRUCache(capacity=0)
        cache.get("anything")
        cache.get("anything")
        # Even after 2 lookups, hits=0, misses=0 -- the
        # cache is off, not "broken". This is the operator
        # UX guarantee: a cache that is intentionally
        # disabled shows a clean zero, not a misleading
        # "100% miss rate".
        stats = cache.stats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.size == 0
        assert stats.capacity == 0

    def test_capacity_property_reflects_construction_arg(self) -> None:
        assert InMemoryLRUCache(capacity=128).capacity == 128
        assert InMemoryLRUCache(capacity=512).capacity == 512

    def test_negative_capacity_raises(self) -> None:
        """``capacity=-1`` (or any negative) is a programming
        error -- raise loudly at construction, not at the
        first cache op.
        """
        with pytest.raises(ValueError, match="capacity must be >= 0"):
            InMemoryLRUCache(capacity=-1)

    def test_capacity_is_preserved_through_set_overflow(
        self,
    ) -> None:
        """Setting more than capacity entries evicts LRU,
        doesn't grow unbounded.
        """
        cache = InMemoryLRUCache(capacity=2)
        for i in range(10):
            cache.set(f"k{i}", _make_extraction_result(f"v{i}"))
        assert cache.stats().size == 2
        assert cache.stats().capacity == 2


# ---------------------------------------------------------------------------
# TestRedisCache -- impl-specific behavior (with fakeredis)
# ---------------------------------------------------------------------------

class TestRedisCache:
    """Redis implementation -- the multi-worker fix.

    Uses ``fakeredis`` so tests don't need a running Redis
    server. fakeredis is API-compatible with redis-py; the
    tests below would pass against a real ``redis-server``
    process started via ``docker run --rm redis:7-alpine``.
    """

    def test_capacity_zero_disables_cache(
        self, fake_redis_client: fakeredis.FakeRedis
    ) -> None:
        """Same contract as InMemoryLRUCache: capacity=0
        means off; no counter increments.
        """
        cache = RedisCache(
            redis_url="redis://fake/",
            capacity=0,
            client=fake_redis_client,
        )
        cache.get("anything")
        cache.get("anything")
        stats = cache.stats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.size == 0
        assert stats.capacity == 0

    def test_redis_url_required(self) -> None:
        """``CACHE_BACKEND=redis`` requires a real redis_url.
        Without one, the constructor raises rather than
        silently defaulting to localhost (which would be
        a footgun: a developer might point at the wrong
        Redis instance).
        """
        with pytest.raises(ValueError, match="non-empty redis_url"):
            RedisCache(redis_url="", capacity=128)

    def test_negative_capacity_raises(self) -> None:
        with pytest.raises(ValueError, match="capacity must be >= 0"):
            RedisCache(redis_url="redis://fake/", capacity=-1)

    def test_value_uses_key_prefix(
        self, fake_redis_client: fakeredis.FakeRedis
    ) -> None:
        """The ``key_prefix`` argument namespaces the Redis
        keys so the cache doesn't collide with other apps
        sharing the same Redis instance.

        Note: counter keys (``__hits__``, ``__misses__``) only
        exist in Redis after the FIRST ``get`` call --
        Redis INCR creates the key lazily. We exercise
        ``get`` here so the test is meaningful; without
        that, the test would only verify that ``set``
        writes the data key + LRU index, not the
        counters.
        """
        cache = RedisCache(
            redis_url="redis://fake/",
            capacity=128,
            key_prefix="myapp:cache:",
            client=fake_redis_client,
        )
        cache.set("k", _make_extraction_result("v"))
        # Trigger counter creation via a get -- we do
        # BOTH a miss (non-existent key) and a hit (the
        # key we just set) so the ``__misses__`` counter
        # and the ``__hits__`` counter both get created
        # (Redis INCR creates keys lazily).
        cache.get("never-existed")
        cache.get("k")
        # The data key has the prefix.
        assert fake_redis_client.get("myapp:cache:k") is not None
        # The LRU index has the prefix.
        assert fake_redis_client.exists("myapp:cache:__lru__")
        # Counters have the prefix (created lazily by INCR).
        assert fake_redis_client.exists("myapp:cache:__hits__")
        assert fake_redis_client.exists("myapp:cache:__misses__")

    def test_default_key_prefix(
        self, fake_redis_client: fakeredis.FakeRedis
    ) -> None:
        """The default prefix is ``bioresearch:abstract:``.
        This test pins the default so a refactor that changes
        it triggers a test failure (callers may depend on
        the key shape -- e.g. ops scripts that FLUSH the
        cache namespace).
        """
        cache = RedisCache(
            redis_url="redis://fake/",
            capacity=128,
            client=fake_redis_client,
        )
        cache.set("k", _make_extraction_result("v"))
        assert fake_redis_client.get("bioresearch:abstract:k") is not None
        assert fake_redis_client.exists("bioresearch:abstract:__lru__")

    def test_counters_are_atomic_across_increments(
        self, fake_redis_client: fakeredis.FakeRedis
    ) -> None:
        """``hits`` and ``misses`` are independent atomic
        INCRs on Redis. Test the relationship between
        ``get`` (increments one) and ``set`` (doesn't
        increment either).
        """
        cache = RedisCache(
            redis_url="redis://fake/",
            capacity=128,
            client=fake_redis_client,
        )
        # 5 misses (no set).
        for i in range(5):
            cache.get(f"k{i}")
        assert cache.stats() == CacheStats(
            hits=0, misses=5, size=0, capacity=128
        )
        # 3 sets, then 3 hits. misses stays at 5.
        for i in range(3):
            cache.set(f"k{i}", _make_extraction_result(f"v{i}"))
        for i in range(3):
            cache.get(f"k{i}")
        assert cache.stats() == CacheStats(
            hits=3, misses=5, size=3, capacity=128
        )

    def test_lru_index_is_zset(
        self, fake_redis_client: fakeredis.FakeRedis
    ) -> None:
        """The LRU index is a sorted set. This is the data
        structure that makes LRU possible in O(log N) per
        op. If a future refactor changes the type (e.g. to
        a regular set with separate timestamps), this test
        will fail and the change can be reviewed.
        """
        cache = RedisCache(
            redis_url="redis://fake/",
            capacity=128,
            client=fake_redis_client,
        )
        cache.set("k1", _make_extraction_result("v1"))
        # ZCARD returns the cardinality of a sorted set.
        # If the LRU index weren't a zset, ZCARD would
        # raise. This test pins the implementation choice.
        assert fake_redis_client.zcard("bioresearch:abstract:__lru__") == 1


# ---------------------------------------------------------------------------
# TestMakeCache -- the factory
# ---------------------------------------------------------------------------

class TestMakeCache:
    """``make_cache(backend, ...)`` translates the env-var
    string into a cache instance. Pin the contract here so
    a typo in a deployment's env file produces a clear error
    at startup, not a runtime AttributeError on the first
    cache op.
    """

    def test_memory_backend_default(self) -> None:
        cache = make_cache("memory", capacity=128)
        assert isinstance(cache, InMemoryLRUCache)
        assert cache.capacity == 128

    def test_memory_backend_case_insensitive(self) -> None:
        """``CACHE_BACKEND`` env values may be set by hand
        and may have unexpected casing. Be tolerant.
        """
        for variant in ("memory", "Memory", "MEMORY", "in_memory"):
            cache = make_cache(variant, capacity=128)
            assert isinstance(cache, InMemoryLRUCache)

    def test_redis_backend_with_url(self) -> None:
        client = fakeredis.FakeRedis(decode_responses=True)
        # We can't easily intercept the URL-built client, so
        # we use the ``client`` override path via the RedisCache
        # directly -- the factory just constructs one with
        # the URL. We test the URL-validation path separately.
        cache = make_cache(
            "redis",
            capacity=128,
            redis_url="redis://test:6379/0",
        )
        assert isinstance(cache, RedisCache)
        assert cache.capacity == 128
        # We don't assert on the underlying client because
        # RedisCache.from_url() may resolve the URL lazily.
        # The functional test is the URL-required validation
        # below.

    def test_redis_backend_requires_url(self) -> None:
        """``CACHE_BACKEND=redis`` with no REDIS_URL is a
        deployment error -- fail loudly at startup.
        """
        with pytest.raises(ValueError, match="requires REDIS_URL"):
            make_cache("redis", capacity=128, redis_url="")

    def test_unknown_backend_raises(self) -> None:
        """Typos in CACHE_BACKEND produce a clear error,
        not a silent default.
        """
        with pytest.raises(ValueError, match="Unknown CACHE_BACKEND"):
            make_cache("momory", capacity=128)  # typo
        with pytest.raises(ValueError, match="Unknown CACHE_BACKEND"):
            make_cache("Memcached", capacity=128)  # not yet supported

    def test_redis_backend_with_custom_prefix(self) -> None:
        """The custom ``redis_key_prefix`` argument is
        passed through to ``RedisCache``. We test via the
        factory rather than calling ``RedisCache`` directly
        so the factory's prefix-passing is also exercised.
        """
        # We can't actually verify the key shape without a
        # real Redis (the URL-built client goes to a
        # non-existent server). The functional test is in
        # ``TestRedisCache.test_value_uses_key_prefix``.
        cache = make_cache(
            "redis",
            capacity=128,
            redis_url="redis://fake/",
            redis_key_prefix="custom:prefix:",
        )
        assert isinstance(cache, RedisCache)
        assert cache._key_prefix == "custom:prefix:"
