"""
Tests for src/rate_limiter.py - Token bucket rate limiting.

Pure class with no dependencies.
"""

import pytest
import time
import sys
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.rate_limiter import RateLimiter, get_rate_limiter


class TestRateLimiterInit:

    def test_default_limits(self):
        rl = RateLimiter()
        assert rl.max_per_minute == 60
        assert rl.max_per_hour == 1000

    def test_custom_limits(self):
        rl = RateLimiter(max_requests_per_minute=10, max_requests_per_hour=100)
        assert rl.max_per_minute == 10
        assert rl.max_per_hour == 100


class TestCheckRateLimit:

    def test_first_request_allowed(self):
        rl = RateLimiter()
        allowed, msg = rl.check_rate_limit("agent-1")
        assert allowed is True
        assert msg is None

    def test_within_limit_allowed(self):
        rl = RateLimiter(max_requests_per_minute=5)
        for _ in range(4):
            allowed, _ = rl.check_rate_limit("agent-1")
            assert allowed is True

    def test_exceeds_per_minute_limit(self):
        rl = RateLimiter(max_requests_per_minute=3)
        for _ in range(3):
            rl.check_rate_limit("agent-1")
        allowed, msg = rl.check_rate_limit("agent-1")
        assert allowed is False
        assert "per minute" in msg

    def test_exceeds_per_hour_limit(self):
        rl = RateLimiter(max_requests_per_minute=1000, max_requests_per_hour=5)
        for _ in range(5):
            rl.check_rate_limit("agent-1")
        allowed, msg = rl.check_rate_limit("agent-1")
        assert allowed is False
        assert "per hour" in msg

    def test_per_agent_isolation(self):
        rl = RateLimiter(max_requests_per_minute=2)
        rl.check_rate_limit("agent-1")
        rl.check_rate_limit("agent-1")
        # agent-1 is at limit
        allowed1, _ = rl.check_rate_limit("agent-1")
        assert allowed1 is False
        # agent-2 should still be fine
        allowed2, _ = rl.check_rate_limit("agent-2")
        assert allowed2 is True

    def test_old_requests_cleaned_up(self):
        """Requests older than window should be cleaned up."""
        rl = RateLimiter(max_requests_per_minute=2)
        # Manually inject old timestamps
        rl.request_history["agent-1"].append(time.time() - 120)  # 2 min ago
        rl.request_history["agent-1"].append(time.time() - 120)
        # These old requests should not count
        allowed, _ = rl.check_rate_limit("agent-1")
        assert allowed is True


class TestGetStats:

    def test_empty_stats(self):
        rl = RateLimiter(max_requests_per_minute=10, max_requests_per_hour=100)
        stats = rl.get_stats("agent-1")
        assert stats["requests_last_minute"] == 0
        assert stats["requests_last_hour"] == 0
        assert stats["limit_per_minute"] == 10
        assert stats["limit_per_hour"] == 100
        assert stats["remaining_minute"] == 10
        assert stats["remaining_hour"] == 100

    def test_stats_after_requests(self):
        rl = RateLimiter(max_requests_per_minute=10)
        for _ in range(3):
            rl.check_rate_limit("agent-1")
        stats = rl.get_stats("agent-1")
        assert stats["requests_last_minute"] == 3
        assert stats["remaining_minute"] == 7


class TestReset:

    def test_reset_specific_agent(self):
        rl = RateLimiter(max_requests_per_minute=5)
        rl.check_rate_limit("agent-1")
        rl.check_rate_limit("agent-2")
        rl.reset("agent-1")
        stats1 = rl.get_stats("agent-1")
        stats2 = rl.get_stats("agent-2")
        assert stats1["requests_last_minute"] == 0
        assert stats2["requests_last_minute"] == 1

    def test_reset_all(self):
        rl = RateLimiter(max_requests_per_minute=5)
        rl.check_rate_limit("agent-1")
        rl.check_rate_limit("agent-2")
        rl.reset()
        assert len(rl.request_history) == 0


class TestGetRateLimiter:

    def test_returns_instance(self):
        rl = get_rate_limiter()
        assert isinstance(rl, RateLimiter)

    def test_singleton(self):
        rl1 = get_rate_limiter()
        rl2 = get_rate_limiter()
        assert rl1 is rl2
