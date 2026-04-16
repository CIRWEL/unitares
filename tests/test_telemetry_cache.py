"""
Tests for src/telemetry_cache.py - TTL-based telemetry cache.

Pure in-memory operations, no I/O needed.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.telemetry_cache import TelemetryCache, get_telemetry_cache


# ============================================================================
# TelemetryCache - init
# ============================================================================

class TestTelemetryCacheInit:

    def test_default_ttl(self):
        cache = TelemetryCache()
        assert cache.default_ttl == 60

    def test_custom_ttl(self):
        cache = TelemetryCache(default_ttl_seconds=30)
        assert cache.default_ttl == 30

    def test_empty_cache(self):
        cache = TelemetryCache()
        assert len(cache.cache) == 0


# ============================================================================
# TelemetryCache - _make_key
# ============================================================================

class TestMakeKey:

    def test_basic_key(self):
        cache = TelemetryCache()
        key = cache._make_key("skip_rate")
        assert isinstance(key, str)
        assert len(key) == 32  # MD5 hex

    def test_same_params_same_key(self):
        cache = TelemetryCache()
        k1 = cache._make_key("skip_rate", agent_id="a1", window_hours=24)
        k2 = cache._make_key("skip_rate", agent_id="a1", window_hours=24)
        assert k1 == k2

    def test_different_type_different_key(self):
        cache = TelemetryCache()
        k1 = cache._make_key("skip_rate")
        k2 = cache._make_key("confidence_dist")
        assert k1 != k2

    def test_different_agent_different_key(self):
        cache = TelemetryCache()
        k1 = cache._make_key("skip_rate", agent_id="a1")
        k2 = cache._make_key("skip_rate", agent_id="a2")
        assert k1 != k2

    def test_different_window_different_key(self):
        cache = TelemetryCache()
        k1 = cache._make_key("skip_rate", window_hours=12)
        k2 = cache._make_key("skip_rate", window_hours=24)
        assert k1 != k2

    def test_no_agent_id(self):
        cache = TelemetryCache()
        k1 = cache._make_key("skip_rate")
        k2 = cache._make_key("skip_rate", agent_id=None)
        assert k1 == k2


# ============================================================================
# TelemetryCache - get/set
# ============================================================================

class TestGetSet:

    def test_set_and_get(self):
        cache = TelemetryCache()
        data = {"count": 5, "rate": 0.3}
        cache.set("skip_rate", data)
        result = cache.get("skip_rate")
        assert result == data

    def test_get_nonexistent(self):
        cache = TelemetryCache()
        result = cache.get("skip_rate")
        assert result is None

    def test_get_expired(self):
        cache = TelemetryCache()
        data = {"count": 5}
        cache.set("skip_rate", data, ttl_seconds=0)
        # Force expiration deterministically without wall-clock sleep.
        key = cache._make_key("skip_rate")
        cache.cache[key]["expires_at"] = datetime.now() - timedelta(seconds=1)
        result = cache.get("skip_rate")
        assert result is None

    def test_expired_entry_removed(self):
        cache = TelemetryCache()
        cache.set("skip_rate", {"data": 1}, ttl_seconds=0)
        key = cache._make_key("skip_rate")
        cache.cache[key]["expires_at"] = datetime.now() - timedelta(seconds=1)
        cache.get("skip_rate")  # Triggers cleanup
        assert len(cache.cache) == 0

    def test_custom_ttl_override(self):
        cache = TelemetryCache(default_ttl_seconds=60)
        cache.set("skip_rate", {"data": 1}, ttl_seconds=3600)
        result = cache.get("skip_rate")
        assert result is not None

    def test_set_with_agent_id(self):
        cache = TelemetryCache()
        cache.set("skip_rate", {"data": 1}, agent_id="a1")
        assert cache.get("skip_rate", agent_id="a1") == {"data": 1}
        assert cache.get("skip_rate", agent_id="a2") is None

    def test_set_with_window(self):
        cache = TelemetryCache()
        cache.set("skip_rate", {"data": 1}, window_hours=12)
        assert cache.get("skip_rate", window_hours=12) == {"data": 1}
        assert cache.get("skip_rate", window_hours=24) is None

    def test_overwrite(self):
        cache = TelemetryCache()
        cache.set("skip_rate", {"v": 1})
        cache.set("skip_rate", {"v": 2})
        assert cache.get("skip_rate") == {"v": 2}


# ============================================================================
# TelemetryCache - invalidate
# ============================================================================

class TestInvalidate:

    def test_invalidate_all(self):
        cache = TelemetryCache()
        cache.set("a", {"data": 1})
        cache.set("b", {"data": 2})
        count = cache.invalidate()
        assert count == 2
        assert len(cache.cache) == 0

    def test_invalidate_by_query_type(self):
        cache = TelemetryCache()
        cache.set("skip_rate", {"data": 1})
        cache.set("confidence_dist", {"data": 2})
        count = cache.invalidate(query_type="skip_rate")
        assert count == 1
        assert cache.get("confidence_dist") == {"data": 2}

    def test_invalidate_empty_cache(self):
        cache = TelemetryCache()
        count = cache.invalidate()
        assert count == 0


# ============================================================================
# TelemetryCache - clear
# ============================================================================

class TestClear:

    def test_clear(self):
        cache = TelemetryCache()
        cache.set("a", {"data": 1})
        cache.set("b", {"data": 2})
        cache.clear()
        assert len(cache.cache) == 0

    def test_clear_empty(self):
        cache = TelemetryCache()
        cache.clear()  # Should not crash


# ============================================================================
# TelemetryCache - stats
# ============================================================================

class TestStats:

    def test_empty_stats(self):
        cache = TelemetryCache()
        s = cache.stats()
        assert s["total_entries"] == 0
        assert s["active_entries"] == 0
        assert s["expired_entries"] == 0

    def test_stats_with_entries(self):
        cache = TelemetryCache()
        cache.set("a", {"data": 1}, ttl_seconds=3600)
        cache.set("b", {"data": 2}, ttl_seconds=3600)
        s = cache.stats()
        assert s["total_entries"] == 2
        assert s["active_entries"] == 2

    def test_stats_with_expired(self):
        cache = TelemetryCache()
        cache.set("a", {"data": 1}, ttl_seconds=0)
        key = cache._make_key("a")
        cache.cache[key]["expires_at"] = datetime.now() - timedelta(seconds=1)
        s = cache.stats()
        assert s["expired_entries"] == 1

    def test_stats_default_ttl(self):
        cache = TelemetryCache(default_ttl_seconds=42)
        s = cache.stats()
        assert s["default_ttl_seconds"] == 42


# ============================================================================
# get_telemetry_cache (global instance)
# ============================================================================

class TestGetTelemetryCache:

    def test_returns_cache(self):
        cache = get_telemetry_cache()
        assert isinstance(cache, TelemetryCache)

    def test_returns_same_instance(self):
        c1 = get_telemetry_cache()
        c2 = get_telemetry_cache()
        assert c1 is c2


# ============================================================================
# TelemetryCache - sweep
# ============================================================================

class TestSweep:

    def test_sweep_removes_expired(self):
        cache = TelemetryCache()
        cache.set("a", {"data": 1}, ttl_seconds=0)
        cache.set("b", {"data": 2}, ttl_seconds=3600)
        expired_key = cache._make_key("a")
        cache.cache[expired_key]["expires_at"] = datetime.now() - timedelta(seconds=1)
        removed = cache.sweep()
        assert removed >= 1
        assert len(cache.cache) == 1
        assert cache.get("b") == {"data": 2}

    def test_sweep_empty_cache(self):
        cache = TelemetryCache()
        assert cache.sweep() == 0

    def test_sweep_nothing_expired(self):
        cache = TelemetryCache()
        cache.set("a", {"data": 1}, ttl_seconds=3600)
        assert cache.sweep() == 0
        assert len(cache.cache) == 1

    def test_max_entries_eviction(self):
        cache = TelemetryCache()
        original_max = TelemetryCache.MAX_ENTRIES
        TelemetryCache.MAX_ENTRIES = 5
        try:
            # Insert directly to bypass auto-sweep
            for i in range(10):
                key = cache._make_key(f"type_{i}")
                cache.cache[key] = {
                    'data': {"i": i},
                    'expires_at': datetime.now() + timedelta(hours=1),
                    'cached_at': datetime.now().isoformat(),
                    'query_type': f"type_{i}",
                }
            assert len(cache.cache) == 10
            cache.sweep()
            assert len(cache.cache) == 5
        finally:
            TelemetryCache.MAX_ENTRIES = original_max

    def test_auto_sweep_on_write(self):
        cache = TelemetryCache()
        # Add expired entries
        for i in range(5):
            cache.set(f"old_{i}", {"i": i}, ttl_seconds=0)
        cache._sweep_counter = 0
        # Mark all old entries expired deterministically.
        for i in range(5):
            old_key = cache._make_key(f"old_{i}")
            cache.cache[old_key]["expires_at"] = datetime.now() - timedelta(seconds=1)
        # Set counter to 49 so next write triggers sweep
        cache._sweep_counter = 49
        cache.set("trigger", {"data": "new"}, ttl_seconds=3600)
        # Expired entries should have been swept
        assert len(cache.cache) == 1
        assert cache.get("trigger") == {"data": "new"}
