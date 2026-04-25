"""Tests for P005 false-positive suppression on context-managed acquires.

P005 fires on resource-leak shapes (acquire/cursor/connect/lock without a
matching release). When the call sits inside an `async with` (or plain
`with`) header, the context manager handles release on __aexit__, so the
finding is by construction a false positive. Caught 2026-04-24 when the
model flagged `async with db.acquire() as conn:` lines (KG entry
2026-04-24T02:01:05).
"""

from __future__ import annotations

import pytest

from agents.watcher.agent import _verify_finding_against_source
from agents.watcher.findings import Finding


def _make(line: int, pattern: str = "P005") -> Finding:
    return Finding(
        pattern=pattern,
        file="src/example.py",
        line=line,
        hint="resource leak",
        severity="medium",
        detected_at="2026-04-25T00:00:00Z",
        model_used="test",
    )


class TestP005ContextManagedSuppression:
    """`async with X.acquire()` and friends must drop — context manager releases."""

    def test_async_with_db_acquire_dropped(self):
        snippet = {1: "async with db.acquire() as conn:"}
        assert _verify_finding_against_source(_make(1), "", snippet) is False

    def test_async_with_pool_acquire_dropped(self):
        snippet = {5: "    async with pool.acquire() as conn:"}
        assert _verify_finding_against_source(_make(5), "", snippet) is False

    def test_async_with_redis_lock_dropped(self):
        snippet = {3: "async with redis.lock(name) as lock:"}
        assert _verify_finding_against_source(_make(3), "", snippet) is False

    def test_async_with_conn_cursor_dropped(self):
        snippet = {7: "async with conn.cursor() as cur:"}
        assert _verify_finding_against_source(_make(7), "", snippet) is False

    def test_plain_with_connect_dropped(self):
        snippet = {2: "with sqlite3.connect(path) as conn:"}
        assert _verify_finding_against_source(_make(2), "", snippet) is False


class TestP005RealLeaksKept:
    """Bare acquires without a context manager must NOT be dropped here."""

    def test_bare_acquire_assignment_kept(self):
        # No context manager — must not be dropped by the new rule.
        # (Survives the required-token gate; goes through to remaining checks.)
        snippet = {4: "    conn = await db.acquire()"}
        assert _verify_finding_against_source(_make(4), "", snippet) is True

    def test_bare_cursor_assignment_kept(self):
        snippet = {6: "    cur = conn.cursor()"}
        assert _verify_finding_against_source(_make(6), "", snippet) is True

    def test_acquire_in_comment_dropped_by_existing_rule(self):
        # Comment lines are dropped by _looks_like_comment, not by us.
        snippet = {8: "    # remember to .acquire() the lock"}
        assert _verify_finding_against_source(_make(8), "", snippet) is False


class TestP005DropDoesNotLeakToOtherPatterns:
    """The new drop must only apply to P005."""

    def test_p001_with_acquire_on_line_not_affected(self):
        # P001 has its own required-token gate (`create_task(`), so an
        # `async with db.acquire()` line fails P001's required-token check
        # before reaching our new P005 branch.
        snippet = {1: "async with db.acquire() as conn:"}
        assert _verify_finding_against_source(_make(1, pattern="P001"), "", snippet) is False
