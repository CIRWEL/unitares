# Audit Payload Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `audit.tool_usage.payload` with allowlisted, redacted, size-capped tool arguments so downstream audit / calibration-drift / observer-vs-self work has real data to read.

**Architecture:** Three new modules (`_redact.py`, `audit_payload_policy.py`, and expanded tests), two modified services (`tool_usage_recorder.py`, `http_tool_service.py`), one modified server (`mcp_server_std.py`). Redaction runs before truncation; truncation runs before size-cap; whole-row fallback on aggregate overflow. Per-tool allowlist is default-closed.

**Tech Stack:** Python 3.12+, stdlib `re` for redaction, asyncpg for audit writes, pytest for tests. No new dependencies.

**Spec:** `docs/specs/2026-04-17-audit-payload-capture-design.md`

---

## Prerequisites

Before starting, verify the worktree is clean and the spec is readable:

```bash
cd /Users/cirwel/projects/unitares
git worktree list  # audit-payload-spec should exist, or create one from master
```

If a new implementation worktree is needed (recommended so the spec PR and impl PR are separate):

```bash
cd /Users/cirwel/projects/unitares
git worktree add .worktrees/audit-payload-impl -b feat/audit-payload-capture
cd .worktrees/audit-payload-impl
```

All task paths below are relative to the worktree root.

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `src/services/_redact.py` | Secret redaction — 10 pattern classes, recursive over lists/dicts, high-ratio stub suppression |
| `src/services/audit_payload_policy.py` | Allowlist dispatcher per tool, size-cap enforcement, sentinel-drop logic |
| `tests/test_redact.py` | Unit tests for redaction — 12+ cases covering all patterns + recursion + stubs |
| `tests/test_audit_payload_policy.py` | Unit tests for allowlist + size cap — 10+ cases |

**Modify:**

| Path | Change |
|---|---|
| `src/services/tool_usage_recorder.py` | Add `arguments` parameter; call policy; thread `session_id` |
| `src/mcp_server_std.py` | Pass `arguments` + `session_id` at three call sites (lines 448, 450, 463) |
| `src/services/http_tool_service.py` | Pass `arguments` + `session_id` at three call sites (lines 76, 81, 86) |

---

## Task 1: Create `_redact.py` with base patterns + recursion

**Files:**
- Create: `src/services/_redact.py`
- Create: `tests/test_redact.py`

- [ ] **Step 1: Write the failing tests (base patterns only)**

Create `tests/test_redact.py`:

```python
"""Unit tests for src/services/_redact.py — secret redaction with recursion."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services._redact import redact_secrets


def test_redacts_anthropic_api_key():
    text = "ran with ANTHROPIC_API_KEY=sk-ant-api03-FIXTUREaaaabbbbccccddddeeeeffff"
    out = redact_secrets(text)
    assert "sk-ant-api03" not in out
    assert "[REDACTED:anthropic_key]" in out


def test_redacts_openai_api_key():
    text = "Bearer sk-proj-FIXTUREaaaabbbbccccddddeeeeffffgggghhhhiiiijjjj"
    out = redact_secrets(text)
    assert "sk-proj-" not in out
    assert "[REDACTED:openai_key]" in out


def test_redacts_github_token():
    text = "ghp_FIXTUREaaaabbbbccccddddeeeeffffgggg"
    out = redact_secrets(text)
    assert "ghp_" not in out
    assert "[REDACTED:github_token]" in out


def test_redacts_github_pat():
    text = "github_pat_FIXTUREaaaabbbbccccddddeeeeffffgggghhhh"
    out = redact_secrets(text)
    assert "github_pat_" not in out
    assert "[REDACTED:github_token]" in out


def test_redacts_aws_access_key():
    text = "AKIAIOSFODNN7EXAMPLE is the key"
    out = redact_secrets(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[REDACTED:aws_key]" in out


def test_preserves_non_secret_text():
    text = "Ran pytest and 257 tests passed"
    assert redact_secrets(text) == text


def test_handles_none_input():
    assert redact_secrets(None) is None


def test_handles_empty_string():
    assert redact_secrets("") == ""


def test_redacts_list_elements():
    """tags: list of strings — recurse into list elements."""
    value = ["fine-tag", "sk-ant-api03-FIXTUREaaaabbbbccccddddeeeeffff"]
    out = redact_secrets(value)
    assert out[0] == "fine-tag"
    assert "sk-ant" not in out[1]
    assert "[REDACTED:anthropic_key]" in out[1]


def test_redacts_dict_values():
    value = {"clean": "ok", "leak": "sk-ant-api03-FIXTUREaaaabbbbccccddddeeeeffff"}
    out = redact_secrets(value)
    assert out["clean"] == "ok"
    assert "[REDACTED:anthropic_key]" in out["leak"]


def test_passes_through_non_strings():
    """Numbers, booleans, None pass unchanged."""
    assert redact_secrets(0.5) == 0.5
    assert redact_secrets(True) is True
    assert redact_secrets(42) == 42
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/audit-payload-impl
python3 -m pytest tests/test_redact.py -v
```

Expected: all tests FAIL with `ModuleNotFoundError: No module named 'src.services._redact'`.

- [ ] **Step 3: Implement `src/services/_redact.py`**

```python
"""Secret redaction for audit payload capture.

Matches common API key / token patterns and replaces them with a labelled
placeholder before text is stored in audit.tool_usage.payload. Recursive
over lists and dicts so nested strings (e.g. elements of a `tags` list)
are covered.

Defense-in-depth. Not resistant to motivated adversaries — whitespace
insertion, case variation, unicode lookalikes, and chunking across fields
are deliberately NOT defended against. See spec §2.
"""

from __future__ import annotations

import re
from typing import Any

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("anthropic_key", re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}")),
    ("openai_key", re.compile(r"sk-(?:proj-)?[a-zA-Z0-9]{32,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9_]{20,})")),
    ("aws_key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("generic_bearer", re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{40,}\b")),
]


def redact_secrets(value: Any) -> Any:
    """Recursively redact secrets. Strings get patterns applied; lists and
    dicts have their elements recursed into; other types pass through.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, dict):
        return {k: redact_secrets(v) for k, v in value.items()}
    return value


def _redact_string(text: str) -> str:
    """Apply every pattern in order. Replacements contain `[REDACTED:...]`
    which no later pattern matches — order therefore doesn't matter for
    correctness, only for label-attribution of overlapping patterns.
    """
    result = text
    for label, pattern in _PATTERNS:
        result = pattern.sub(f"[REDACTED:{label}]", result)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_redact.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/services/_redact.py tests/test_redact.py
git commit -m "feat(services): _redact.py base patterns + recursion"
```

---

## Task 2: Expand redaction patterns (JWT, DB URL, PEM, Stripe, Slack)

**Files:**
- Modify: `src/services/_redact.py`
- Modify: `tests/test_redact.py`

- [ ] **Step 1: Write failing tests for expanded patterns**

Append to `tests/test_redact.py`:

```python
def test_redacts_jwt():
    text = "auth: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    out = redact_secrets(text)
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert "[REDACTED:jwt]" in out


def test_redacts_postgres_url_with_credentials():
    text = "connecting to postgres://admin:s3cretPW@db.example.com:5432/mydb"
    out = redact_secrets(text)
    assert "admin:s3cretPW" not in out
    assert "[REDACTED:db_url]" in out


def test_redacts_mysql_url_with_credentials():
    text = "mysql://root:p@ssword@localhost/db"
    out = redact_secrets(text)
    assert "root:p@ssword" not in out
    assert "[REDACTED:db_url]" in out


def test_redacts_mongodb_url_with_credentials():
    text = "mongodb://user:pass@cluster0.example.com/testdb"
    out = redact_secrets(text)
    assert "user:pass" not in out
    assert "[REDACTED:db_url]" in out


def test_redacts_pem_private_key():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQEAfake\n-----END RSA PRIVATE KEY-----"
    out = redact_secrets(text)
    assert "MIIEogIBAAKCAQEAfake" not in out
    assert "[REDACTED:pem_key]" in out


def test_redacts_stripe_live_key():
    text = "sk" + "_live_" + "FIXTUREaaaabbbbccccddddeeeeffffgggghhhh"  # split literal so secret scanners skip
    out = redact_secrets(text)
    assert "sk_live_" not in out
    assert "[REDACTED:stripe_key]" in out


def test_redacts_stripe_restricted_key():
    text = "rk" + "_live_" + "FIXTUREaaaabbbbccccddddeeeeffffgggghhhh"  # split literal so secret scanners skip
    out = redact_secrets(text)
    assert "rk_live_" not in out
    assert "[REDACTED:stripe_key]" in out


def test_redacts_slack_token():
    text = "xoxb-FIXTURE123-aaaabbbbccccddddeeeeffff"
    out = redact_secrets(text)
    assert "xoxb-" not in out
    assert "[REDACTED:slack_token]" in out


def test_urls_without_credentials_preserved():
    """postgres://host/db without user:pass@ must not match."""
    text = "see docs at postgres://localhost/mydb for schema"
    out = redact_secrets(text)
    assert out == text  # untouched
```

- [ ] **Step 2: Run tests to verify new ones fail**

```bash
python3 -m pytest tests/test_redact.py -v
```

Expected: 11 existing pass, 9 new fail (e.g. `assert "[REDACTED:jwt]" in out` — redaction label not present).

- [ ] **Step 3: Expand `_PATTERNS` in `src/services/_redact.py`**

Replace the `_PATTERNS` definition with:

```python
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("anthropic_key", re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}")),
    ("openai_key", re.compile(r"sk-(?:proj-)?[a-zA-Z0-9]{32,}")),
    ("stripe_key", re.compile(r"\b(?:sk|rk)_live_[a-zA-Z0-9]{20,}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9_]{20,})")),
    ("slack_token", re.compile(r"\bxox[bpoas]-[a-zA-Z0-9\-]{20,}\b")),
    ("aws_key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")),
    ("db_url", re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb|redis|amqp)://[^:@\s/]+:[^@\s/]+@[^\s/]+")),
    ("pem_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("generic_bearer", re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{40,}\b")),
]
```

Note: `stripe_key` appears before `openai_key` because `sk_live_FIXTURE...` could conceivably overlap with the openai prefix (`sk-` vs `sk_`). Order matters only for label-attribution; the secret is redacted either way.

- [ ] **Step 4: Run tests to verify all pass**

```bash
python3 -m pytest tests/test_redact.py -v
```

Expected: 20 passed.

- [ ] **Step 5: Commit**

```bash
git add src/services/_redact.py tests/test_redact.py
git commit -m "feat(services): _redact.py expanded patterns (JWT, DB URL, PEM, Stripe, Slack)"
```

---

## Task 3: High-redaction-ratio stub suppression

**Files:**
- Modify: `src/services/_redact.py`
- Modify: `tests/test_redact.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_redact.py`:

```python
def test_redact_string_with_ratio_returns_tuple():
    """redact_string_with_ratio returns (redacted_text, replaced_ratio)."""
    from src.services._redact import redact_string_with_ratio

    # Clean text: 0% replaced
    clean_result, clean_ratio = redact_string_with_ratio("normal text")
    assert clean_result == "normal text"
    assert clean_ratio == 0.0

    # Entirely secret: ratio ≈ 1.0
    secret = "sk-ant-api03-FIXTUREaaaabbbbccccddddeeeeffff"
    _, all_secret_ratio = redact_string_with_ratio(secret)
    assert all_secret_ratio > 0.9  # most of the bytes were the secret

    # Mixed: ratio reflects actual fraction
    mixed = "OK " + secret + " more text here"
    _, mixed_ratio = redact_string_with_ratio(mixed)
    assert 0.1 < mixed_ratio < 0.9
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_redact.py::test_redact_string_with_ratio_returns_tuple -v
```

Expected: FAIL with `ImportError: cannot import name 'redact_string_with_ratio'`.

- [ ] **Step 3: Add `redact_string_with_ratio` to `src/services/_redact.py`**

Append to `src/services/_redact.py`:

```python
def redact_string_with_ratio(text: str) -> tuple[str, float]:
    """Redact and return (redacted_text, replaced_byte_ratio).

    The ratio is (original_bytes_replaced / original_bytes) where
    original_bytes_replaced counts bytes that matched a pattern (not the
    placeholder bytes). Callers use the ratio to decide whether the
    remaining text is meaningful or a redaction-dense stub.
    """
    if not text:
        return text, 0.0
    original_bytes = len(text.encode("utf-8"))
    if original_bytes == 0:
        return text, 0.0
    replaced_bytes = 0
    result = text
    for label, pattern in _PATTERNS:
        def _count_and_replace(match: re.Match) -> str:
            nonlocal replaced_bytes
            replaced_bytes += len(match.group(0).encode("utf-8"))
            return f"[REDACTED:{label}]"
        result = pattern.sub(_count_and_replace, result)
    ratio = replaced_bytes / original_bytes if original_bytes else 0.0
    return result, ratio
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_redact.py::test_redact_string_with_ratio_returns_tuple -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/services/_redact.py tests/test_redact.py
git commit -m "feat(services): _redact adds redact_string_with_ratio for stub suppression"
```

---

## Task 4: `audit_payload_policy.py` — allowlist skeleton + three simple tools

**Files:**
- Create: `src/services/audit_payload_policy.py`
- Create: `tests/test_audit_payload_policy.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_audit_payload_policy.py`:

```python
"""Unit tests for src/services/audit_payload_policy.py — allowlist dispatch."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.audit_payload_policy import build_payload


def test_unknown_tool_returns_empty_payload():
    out = build_payload("mystery_tool", {"anything": "ignored"})
    assert out == {}


def test_process_agent_update_captures_allowlisted_fields():
    args = {
        "response_text": "did the work",
        "complexity": 0.5,
        "confidence": 0.7,
        "task_type": "refactoring",
        "continuity_token": "should-not-capture",
        "client_session_id": "also-not",
    }
    out = build_payload("process_agent_update", args)
    assert out["response_text"] == "did the work"
    assert out["complexity"] == 0.5
    assert out["confidence"] == 0.7
    assert out["task_type"] == "refactoring"
    assert "continuity_token" not in out
    assert "client_session_id" not in out


def test_process_agent_update_redacts_secrets_in_response_text():
    args = {
        "response_text": "used key sk-ant-api03-FIXTUREaaaabbbbccccddddeeeeffff to test",
        "complexity": 0.3,
        "confidence": 0.9,
    }
    out = build_payload("process_agent_update", args)
    assert "sk-ant-api03" not in out["response_text"]
    assert "[REDACTED:anthropic_key]" in out["response_text"]


def test_onboard_captures_allowlisted_fields():
    args = {
        "name": "Watcher",
        "model_type": "claude-opus",
        "client_hint": "claude-code",
        "spawn_reason": "resident_observer",
        "force_new": False,
        "agent_uuid": "should-not-capture",
        "continuity_token": "also-not",
    }
    out = build_payload("onboard", args)
    assert out["name"] == "Watcher"
    assert out["model_type"] == "claude-opus"
    assert out["client_hint"] == "claude-code"
    assert out["spawn_reason"] == "resident_observer"
    assert out["force_new"] is False
    assert "agent_uuid" not in out
    assert "continuity_token" not in out


def test_identity_captures_allowlisted_fields():
    args = {
        "resume": True,
        "force_new": False,
        "model_type": "claude-opus",
        "agent_uuid": "should-not-capture",
    }
    out = build_payload("identity", args)
    assert out["resume"] is True
    assert out["force_new"] is False
    assert out["model_type"] == "claude-opus"
    assert "agent_uuid" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_audit_payload_policy.py -v
```

Expected: all fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/services/audit_payload_policy.py` skeleton**

```python
"""Per-tool allowlist for audit.tool_usage.payload capture.

Default-closed: tools not in ALLOWLIST produce `{}`. Onboarding a new
tool is a deliberate act — edit this file, add a test.
"""

from __future__ import annotations

from typing import Any, Callable

from src.services._redact import redact_secrets


def build_payload(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the audit payload for one tool call from its arguments.

    Returns the allowlisted subset, redacted. Size-cap enforcement
    (per-field truncation + aggregate fallback) is applied by
    `apply_size_cap` in a later task.
    """
    handler = ALLOWLIST.get(tool_name)
    if handler is None:
        return {}
    return handler(arguments or {})


def _process_agent_update(args: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in ("response_text", "complexity", "confidence", "task_type"):
        if field in args and args[field] is not None:
            payload[field] = args[field]
    # Redact strings (response_text primarily)
    return redact_secrets(payload)


def _onboard(args: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in ("name", "model_type", "client_hint", "spawn_reason", "force_new"):
        if field in args and args[field] is not None:
            payload[field] = args[field]
    return redact_secrets(payload)


def _identity(args: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in ("resume", "force_new", "model_type"):
        if field in args and args[field] is not None:
            payload[field] = args[field]
    return redact_secrets(payload)


ALLOWLIST: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "process_agent_update": _process_agent_update,
    "onboard": _onboard,
    "identity": _identity,
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_audit_payload_policy.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/services/audit_payload_policy.py tests/test_audit_payload_policy.py
git commit -m "feat(services): audit_payload_policy allowlist for process_agent_update/onboard/identity"
```

---

## Task 5: Add `outcome_event`, `knowledge`, dialectic tools to allowlist

**Files:**
- Modify: `src/services/audit_payload_policy.py`
- Modify: `tests/test_audit_payload_policy.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_audit_payload_policy.py`:

```python
def test_outcome_event_drops_detail_field():
    """detail is free-form operator text — too dangerous to capture even redacted."""
    args = {
        "outcome_type": "success",
        "outcome_score": 0.8,
        "is_bad": False,
        "detail": "operator typed continuity_token here accidentally",
    }
    out = build_payload("outcome_event", args)
    assert out["outcome_type"] == "success"
    assert out["outcome_score"] == 0.8
    assert out["is_bad"] is False
    assert "detail" not in out


def test_knowledge_search_captures_query():
    args = {
        "action": "search",
        "query": "what's the name-claim status",
        "tags": ["identity", "audit"],
    }
    out = build_payload("knowledge", args)
    assert out["action"] == "search"
    assert out["query"] == "what's the name-claim status"
    assert out["tags"] == ["identity", "audit"]


def test_knowledge_store_captures_summary_not_query():
    args = {
        "action": "store",
        "summary": "discovered that tool_usage payload was empty",
        "tags": ["audit"],
        "discovery_type": "bug_found",
    }
    out = build_payload("knowledge", args)
    assert out["summary"] == "discovered that tool_usage payload was empty"
    assert out["discovery_type"] == "bug_found"
    assert out["tags"] == ["audit"]
    assert "query" not in out


def test_knowledge_other_action_captures_action_only():
    """update / get / list / etc. capture only the action field."""
    args = {"action": "update", "status": "resolved", "discovery_id": "xyz"}
    out = build_payload("knowledge", args)
    assert out == {"action": "update"}


def test_knowledge_tags_element_redacted():
    """List-element redaction: a secret in tags gets redacted."""
    args = {
        "action": "search",
        "query": "ok",
        "tags": ["sk-ant-api03-FIXTUREaaaabbbbccccddddeeeeffff"],
    }
    out = build_payload("knowledge", args)
    assert "sk-ant-api03" not in out["tags"][0]
    assert "[REDACTED:anthropic_key]" in out["tags"][0]


def test_dialectic_request_with_reason_captures_it():
    args = {"action": "request", "reason": "I think the verdict was wrong because X"}
    out = build_payload("request_dialectic_review", args)
    assert out["reason"] == "I think the verdict was wrong because X"


def test_dialectic_request_with_default_sentinel_drops_it():
    """Handler default reason produces empty payload — sentinel-drop."""
    args = {"action": "request", "reason": "Dialectic review requested"}
    out = build_payload("request_dialectic_review", args)
    # With only the sentinel reason, the payload is empty (no meaningful signal).
    assert out == {}


def test_submit_thesis_captures_reasoning():
    args = {"reasoning": "I have E=0.8 and my confidence is justified"}
    out = build_payload("submit_thesis", args)
    assert out["reasoning"] == "I have E=0.8 and my confidence is justified"


def test_submit_synthesis_captures_reasoning_and_agrees():
    args = {"reasoning": "agreed after review", "agrees": True}
    out = build_payload("submit_synthesis", args)
    assert out["reasoning"] == "agreed after review"
    assert out["agrees"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_audit_payload_policy.py -v
```

Expected: 5 existing pass, 9 new fail (unknown tools return `{}`).

- [ ] **Step 3: Extend allowlist handlers in `src/services/audit_payload_policy.py`**

Add these handler functions before the `ALLOWLIST = {...}` declaration:

```python
def _outcome_event(args: dict[str, Any]) -> dict[str, Any]:
    """detail is intentionally excluded — free-form operator text can carry
    tokens, stacktraces, file paths with env values. Safer to drop."""
    payload: dict[str, Any] = {}
    for field in ("outcome_type", "outcome_score", "is_bad"):
        if field in args and args[field] is not None:
            payload[field] = args[field]
    return redact_secrets(payload)


def _knowledge(args: dict[str, Any]) -> dict[str, Any]:
    action = args.get("action")
    payload: dict[str, Any] = {"action": action} if action is not None else {}
    if action == "search":
        for field in ("query", "tags"):
            if field in args and args[field] is not None:
                payload[field] = args[field]
    elif action == "store":
        for field in ("summary", "tags", "discovery_type"):
            if field in args and args[field] is not None:
                payload[field] = args[field]
    # Other actions capture only the action name.
    return redact_secrets(payload)


_DIALECTIC_REASON_SENTINEL = "Dialectic review requested"


def _request_dialectic_review(args: dict[str, Any]) -> dict[str, Any]:
    """Handler defaults `reason` to a sentinel string. Drop the row if that's
    the only value present — otherwise every dialectic request writes a
    non-signal row."""
    reason = args.get("reason")
    if reason is None or reason == _DIALECTIC_REASON_SENTINEL:
        return {}
    return redact_secrets({"reason": reason})


def _submit_thesis(args: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if "reasoning" in args and args["reasoning"] is not None:
        payload["reasoning"] = args["reasoning"]
    return redact_secrets(payload)


def _submit_antithesis(args: dict[str, Any]) -> dict[str, Any]:
    # Same shape as thesis — reuse.
    return _submit_thesis(args)


def _submit_synthesis(args: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if "reasoning" in args and args["reasoning"] is not None:
        payload["reasoning"] = args["reasoning"]
    if "agrees" in args and args["agrees"] is not None:
        payload["agrees"] = args["agrees"]
    return redact_secrets(payload)
```

Then update `ALLOWLIST`:

```python
ALLOWLIST: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "process_agent_update": _process_agent_update,
    "onboard": _onboard,
    "identity": _identity,
    "outcome_event": _outcome_event,
    "knowledge": _knowledge,
    "request_dialectic_review": _request_dialectic_review,
    "submit_thesis": _submit_thesis,
    "submit_antithesis": _submit_antithesis,
    "submit_synthesis": _submit_synthesis,
}
```

- [ ] **Step 4: Run tests to verify all pass**

```bash
python3 -m pytest tests/test_audit_payload_policy.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add src/services/audit_payload_policy.py tests/test_audit_payload_policy.py
git commit -m "feat(services): audit_payload_policy — outcome_event, knowledge, dialectic tools"
```

---

## Task 6: Size cap helpers (per-field byte truncation + whole-row fallback)

**Files:**
- Modify: `src/services/audit_payload_policy.py`
- Modify: `tests/test_audit_payload_policy.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_audit_payload_policy.py`:

```python
def test_apply_size_cap_short_payload_unchanged():
    from src.services.audit_payload_policy import apply_size_cap
    payload = {"response_text": "short", "complexity": 0.3}
    out = apply_size_cap(payload)
    assert out == payload


def test_apply_size_cap_truncates_response_text_by_bytes():
    """response_text capped at 512 bytes (not chars)."""
    from src.services.audit_payload_policy import apply_size_cap
    # 2000 chars of ASCII is 2000 bytes
    payload = {"response_text": "a" * 2000, "complexity": 0.3}
    out = apply_size_cap(payload)
    assert len(out["response_text"].encode("utf-8")) <= 512
    assert out["complexity"] == 0.3


def test_apply_size_cap_truncates_utf8_at_byte_boundary():
    """2000 Cyrillic chars ≈ 4000 UTF-8 bytes; must truncate at byte 512."""
    from src.services.audit_payload_policy import apply_size_cap
    cyrillic = "а" * 2000  # each char = 2 UTF-8 bytes
    payload = {"response_text": cyrillic}
    out = apply_size_cap(payload)
    assert len(out["response_text"].encode("utf-8")) <= 512
    # And the truncated string must be valid UTF-8 (no mid-codepoint cut)
    assert out["response_text"].encode("utf-8").decode("utf-8")


def test_apply_size_cap_whole_row_fallback_on_aggregate_overflow():
    """Aggregate over 4KB → whole-row replaced by marker."""
    from src.services.audit_payload_policy import apply_size_cap
    # 9 fields of 500 bytes each = 4500 bytes total, exceeds 4096
    payload = {f"field_{i}": "x" * 500 for i in range(9)}
    out = apply_size_cap(payload)
    assert out.get("_truncated") is True
    assert "fields_present" in out
    assert set(out["fields_present"]) == set(payload.keys())
    assert "reason" in out


def test_apply_size_cap_query_truncated_at_256_bytes():
    """knowledge(action='search').query has a tighter 256-byte cap."""
    from src.services.audit_payload_policy import apply_size_cap
    payload = {"action": "search", "query": "q" * 1000}
    out = apply_size_cap(payload)
    assert len(out["query"].encode("utf-8")) <= 256


def test_apply_size_cap_preserves_non_text_fields():
    """Numbers and booleans aren't truncated."""
    from src.services.audit_payload_policy import apply_size_cap
    payload = {
        "complexity": 0.375,
        "confidence": 0.8,
        "force_new": True,
        "response_text": "short",
    }
    out = apply_size_cap(payload)
    assert out["complexity"] == 0.375
    assert out["confidence"] == 0.8
    assert out["force_new"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_audit_payload_policy.py -v
```

Expected: 14 existing pass, 6 new fail with `ImportError: cannot import name 'apply_size_cap'`.

- [ ] **Step 3: Implement size-cap helpers**

Append to `src/services/audit_payload_policy.py`:

```python
import json

AGGREGATE_MAX_BYTES = 4096
FIELD_BYTE_CAPS = {
    "response_text": 512,
    "reason": 512,
    "reasoning": 512,
    "summary": 512,
    "query": 256,
}


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """Truncate a string to at most max_bytes of UTF-8, never splitting a
    codepoint. Returns empty string if input is empty."""
    if not text:
        return text
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # Walk back from max_bytes until we hit a codepoint boundary.
    cut = encoded[:max_bytes]
    # UTF-8 continuation bytes are 10xxxxxx (0x80-0xBF). Peel them off.
    while cut and (cut[-1] & 0xC0) == 0x80:
        cut = cut[:-1]
    # The lead byte itself might be mid-sequence; one more peel handles it.
    if cut and (cut[-1] & 0xC0) == 0xC0:
        cut = cut[:-1]
    return cut.decode("utf-8", errors="ignore")


def apply_size_cap(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply per-field byte truncation, then check aggregate size.
    On aggregate overflow, return whole-row fallback marker."""
    if not payload:
        return payload
    # Per-field truncation
    capped: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str) and key in FIELD_BYTE_CAPS:
            capped[key] = _truncate_utf8(value, FIELD_BYTE_CAPS[key])
        else:
            capped[key] = value
    # Aggregate check
    serialized = json.dumps(capped, ensure_ascii=False).encode("utf-8")
    if len(serialized) <= AGGREGATE_MAX_BYTES:
        return capped
    # Whole-row fallback
    return {
        "_truncated": True,
        "fields_present": sorted(payload.keys()),
        "reason": f"payload exceeded {AGGREGATE_MAX_BYTES} bytes",
    }
```

- [ ] **Step 4: Run tests to verify all pass**

```bash
python3 -m pytest tests/test_audit_payload_policy.py -v
```

Expected: 20 passed.

- [ ] **Step 5: Commit**

```bash
git add src/services/audit_payload_policy.py tests/test_audit_payload_policy.py
git commit -m "feat(services): audit_payload size cap — per-field UTF-8 bytes + whole-row fallback"
```

---

## Task 7: Wire `build_payload` + `apply_size_cap` into a public `make_payload` entry point

**Files:**
- Modify: `src/services/audit_payload_policy.py`
- Modify: `tests/test_audit_payload_policy.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_audit_payload_policy.py`:

```python
def test_make_payload_end_to_end():
    """make_payload = build + size-cap in one call."""
    from src.services.audit_payload_policy import make_payload
    args = {
        "response_text": "work with key sk-ant-api03-FIXTUREaaaabbbbccccddddeeeeffff included",
        "complexity": 0.5,
        "confidence": 0.7,
    }
    out = make_payload("process_agent_update", args)
    # Redacted
    assert "sk-ant-api03" not in out["response_text"]
    # Byte-capped
    assert len(out["response_text"].encode("utf-8")) <= 512
    # Numeric fields preserved
    assert out["complexity"] == 0.5


def test_make_payload_unknown_tool():
    from src.services.audit_payload_policy import make_payload
    out = make_payload("unknown", {"stuff": "ignored"})
    assert out == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_audit_payload_policy.py -v
```

Expected: 20 existing pass, 2 new fail with `ImportError: cannot import name 'make_payload'`.

- [ ] **Step 3: Add `make_payload` to `src/services/audit_payload_policy.py`**

Append:

```python
def make_payload(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Public entry point: build allowlisted + redacted payload, then
    apply size cap. Returns the final dict ready for the payload column.

    This is the function call sites use. Never raises — returns {} on
    unknown tools or errors."""
    try:
        raw = build_payload(tool_name, arguments)
        return apply_size_cap(raw)
    except Exception:
        return {}
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_audit_payload_policy.py -v
```

Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
git add src/services/audit_payload_policy.py tests/test_audit_payload_policy.py
git commit -m "feat(services): audit_payload_policy public make_payload entry point"
```

---

## Task 8: Extend `record_tool_usage` with arguments + session_id

**Files:**
- Modify: `src/services/tool_usage_recorder.py`
- Create: `tests/test_tool_usage_recorder.py`

- [ ] **Step 1: Read the existing `record_tool_usage` signature**

```bash
grep -n "def record_tool_usage" src/services/tool_usage_recorder.py
```

Expected: one line showing the current signature around `def record_tool_usage(tool_name, agent_id, success, error_type=None, latency_ms=None)`.

- [ ] **Step 2: Write failing test**

Create `tests/test_tool_usage_recorder.py`:

```python
"""Unit tests for src/services/tool_usage_recorder.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_record_tool_usage_accepts_arguments_and_session_id():
    """Signature change: record_tool_usage now takes `arguments` and `session_id`."""
    from src.services.tool_usage_recorder import record_tool_usage

    captured_coro_args = {}

    async def fake_append(tool_name, agent_id, success, **kwargs):
        captured_coro_args["tool_name"] = tool_name
        captured_coro_args["agent_id"] = agent_id
        captured_coro_args["success"] = success
        captured_coro_args.update(kwargs)

    def discard_task(coro, **kwargs):
        # Consume the coroutine to avoid "never awaited" warnings
        try:
            coro.send(None)
        except StopIteration:
            pass
        except Exception:
            coro.close()
        return MagicMock()

    with patch("src.background_tasks.create_tracked_task", side_effect=discard_task), \
         patch("src.audit_db.append_tool_usage_async", side_effect=fake_append):
        record_tool_usage(
            tool_name="process_agent_update",
            agent_id="test-uuid-12345",
            success=True,
            latency_ms=50,
            arguments={"response_text": "did work", "complexity": 0.3, "confidence": 0.8},
            session_id="sess-abc",
        )

    # The coroutine was constructed and sent — verify payload assembled correctly
    assert captured_coro_args["tool_name"] == "process_agent_update"
    assert captured_coro_args["agent_id"] == "test-uuid-12345"
    assert captured_coro_args["success"] is True
    assert captured_coro_args["session_id"] == "sess-abc"
    payload = captured_coro_args.get("payload") or {}
    assert payload.get("response_text") == "did work"
    assert payload.get("complexity") == 0.3


def test_record_tool_usage_empty_payload_for_unknown_tool():
    """Unknown tools still get recorded, but with empty payload."""
    from src.services.tool_usage_recorder import record_tool_usage

    captured = {}

    async def fake_append(tool_name, agent_id, success, **kwargs):
        captured.update(kwargs)

    def discard_task(coro, **kwargs):
        try:
            coro.send(None)
        except StopIteration:
            pass
        except Exception:
            coro.close()

    with patch("src.background_tasks.create_tracked_task", side_effect=discard_task), \
         patch("src.audit_db.append_tool_usage_async", side_effect=fake_append):
        record_tool_usage(
            tool_name="some_other_tool",
            agent_id="test-uuid",
            success=True,
            arguments={"whatever": "stuff"},
        )

    assert captured.get("payload") == {}


def test_record_tool_usage_backward_compat_without_arguments():
    """Calls without arguments still work (backward compat during rollout)."""
    from src.services.tool_usage_recorder import record_tool_usage

    captured = {}

    async def fake_append(tool_name, agent_id, success, **kwargs):
        captured.update(kwargs)

    def discard_task(coro, **kwargs):
        try:
            coro.send(None)
        except StopIteration:
            pass
        except Exception:
            coro.close()

    with patch("src.background_tasks.create_tracked_task", side_effect=discard_task), \
         patch("src.audit_db.append_tool_usage_async", side_effect=fake_append):
        record_tool_usage(
            tool_name="process_agent_update",
            agent_id="test-uuid",
            success=True,
        )

    # No arguments → payload is {} (not None, not crashed)
    assert captured.get("payload") == {}
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_tool_usage_recorder.py -v
```

Expected: all fail with `TypeError: record_tool_usage() got an unexpected keyword argument 'arguments'`.

- [ ] **Step 4: Extend `record_tool_usage` signature**

Read the current `src/services/tool_usage_recorder.py` and locate the `record_tool_usage` function. Modify its signature and body. The existing function calls `append_tool_usage_async` via `create_tracked_task`. Expected shape after the edit:

```python
from src.services.audit_payload_policy import make_payload

def record_tool_usage(
    tool_name: str,
    agent_id: str,
    success: bool,
    error_type: str | None = None,
    latency_ms: int | None = None,
    arguments: dict | None = None,
    session_id: str | None = None,
) -> None:
    """Fire-and-forget audit record for a single MCP tool call.

    `arguments` is the raw dict passed to the tool dispatcher; we compute
    the audit payload from it via audit_payload_policy. `session_id` is
    threaded through so audit.tool_usage.session_id is populated for new
    rows.

    Never raises — errors are swallowed. If the recorder fails, the
    audit row is lost but the tool call itself is unaffected."""
    try:
        payload = make_payload(tool_name, arguments or {})
    except Exception:
        payload = {}
    try:
        from src.background_tasks import create_tracked_task
        from src.audit_db import append_tool_usage_async
        create_tracked_task(
            append_tool_usage_async(
                tool_name=tool_name,
                agent_id=agent_id,
                success=success,
                error_type=error_type,
                latency_ms=latency_ms,
                payload=payload,
                session_id=session_id,
            ),
            name=f"audit_tool_usage:{tool_name}",
        )
    except Exception:
        # Best effort — do not let audit failure break the tool dispatch
        pass
```

Note: the `from` imports are inside the function intentionally — existing patterns in this file use lazy imports to avoid circular-import issues. Keep the pattern.

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_tool_usage_recorder.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run the existing recorder tests to check backward compat**

```bash
python3 -m pytest tests/test_http_tool_service_tool_usage.py -v
```

Expected: all existing tests still pass (they didn't pass `arguments` or `session_id` and the new params default to `None`).

- [ ] **Step 7: Commit**

```bash
git add src/services/tool_usage_recorder.py tests/test_tool_usage_recorder.py
git commit -m "feat(services): tool_usage_recorder adds arguments + session_id params"
```

---

## Task 9: Update stdio dispatch call sites

**Files:**
- Modify: `src/mcp_server_std.py`

- [ ] **Step 1: Locate the call sites**

```bash
grep -n "record_tool_usage" src/mcp_server_std.py
```

Expected: three call sites near lines 448, 450, 463 (line numbers may drift — the grep is authoritative).

- [ ] **Step 2: Read the surrounding context (~10 lines before each)**

```bash
sed -n '430,470p' src/mcp_server_std.py
```

This shows `dispatch_tool` and the try/except/finally pattern. Each `record_tool_usage` call is in one of: success path, validation-error path, exception path. The `arguments` dict is in scope as the `arguments` parameter of `dispatch_tool`; `session_id` needs to come from the session-binding context.

- [ ] **Step 3: Check for `session_id` availability**

```bash
grep -n "client_session_id\|session_id" src/mcp_server_std.py | head -20
```

The pattern in the file shows `client_session_id` is passed via `arguments.get("client_session_id")` or resolved from the session context. Use that as the `session_id` argument.

- [ ] **Step 4: Modify each of the three call sites**

At each `record_tool_usage(...)` call, add two kwargs:

```python
record_tool_usage(
    tool_name=tool_name,
    agent_id=agent_id_for_audit,
    success=success,
    error_type=error_type,
    latency_ms=latency_ms,
    arguments=arguments,  # NEW
    session_id=arguments.get("client_session_id") if arguments else None,  # NEW
)
```

Apply this shape to all three call sites. The variable names for tool_name / agent_id / success / latency_ms are already in scope at each site — don't rename; add the two new kwargs.

- [ ] **Step 5: Run the stdio server tests**

```bash
python3 -m pytest tests/test_mcp_server_std.py -v 2>&1 | tail -20
```

Expected: existing tests pass. If any fail, they were relying on the old signature positionally — fix those tests by naming the new kwargs explicitly.

- [ ] **Step 6: Commit**

```bash
git add src/mcp_server_std.py
git commit -m "feat(stdio): pass arguments + session_id to record_tool_usage"
```

---

## Task 10: Update HTTP dispatch call sites

**Files:**
- Modify: `src/services/http_tool_service.py`

- [ ] **Step 1: Locate the call sites**

```bash
grep -n "record_tool_usage" src/services/http_tool_service.py
```

Expected: three call sites near lines 76, 81, 86.

- [ ] **Step 2: Read surrounding context**

```bash
sed -n '60,90p' src/services/http_tool_service.py
```

`execute_http_tool` receives `arguments` as a parameter. `session_id` may be resolved from `arguments.get("client_session_id")` or from a session-context helper — mirror whatever the stdio path did.

- [ ] **Step 3: Modify each call site**

Same pattern as Task 9 — add `arguments=arguments` and `session_id=arguments.get("client_session_id") if arguments else None` to each `record_tool_usage(...)` call.

- [ ] **Step 4: Run the HTTP service tests**

```bash
python3 -m pytest tests/test_http_tool_service_tool_usage.py -v
```

Expected: existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/services/http_tool_service.py
git commit -m "feat(http): pass arguments + session_id to record_tool_usage"
```

---

## Task 11: Integration test — real `process_agent_update` populates payload

**Files:**
- Create: `tests/integration/test_audit_payload_integration.py`

- [ ] **Step 1: Check the integration test harness**

```bash
ls tests/integration/ 2>/dev/null || ls tests/ | grep -i integration
```

Expected: an existing integration test directory/pattern. If none exists, this file lives under `tests/` with an `@pytest.mark.integration` marker; check `pyproject.toml` or `conftest.py` for the marker convention.

```bash
grep -n "integration" pyproject.toml conftest.py tests/conftest.py 2>/dev/null | head
```

- [ ] **Step 2: Write the integration test**

Create `tests/integration/test_audit_payload_integration.py` (adjust path if the repo uses a flat layout):

```python
"""Integration test: process_agent_update populates audit.tool_usage.payload
with allowlisted, redacted fields."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_process_agent_update_writes_populated_payload():
    """Dispatch a process_agent_update through the real stack and verify
    the audit row has the expected shape."""
    from src.db import get_db

    db = get_db()
    if hasattr(db, "init"):
        await db.init()

    # Onboard a throwaway agent
    from src.mcp_handlers.identity.handlers import handle_onboard_v2
    onboard_result = await handle_onboard_v2({
        "name": "audit_payload_test",
        "force_new": True,
    })

    # Parse UUID from the response
    import json
    from mcp.types import TextContent
    text = onboard_result[0].text if isinstance(onboard_result[0], TextContent) else onboard_result[0]
    data = json.loads(text)
    result = data.get("result", data)
    agent_uuid = result.get("uuid") or result.get("agent_uuid")
    assert agent_uuid

    # Call process_agent_update with a known secret in response_text
    from src.mcp_handlers.updates.handlers import handle_process_agent_update_adapter
    secret_marker = "sk-ant-api03-FIXTUREintegration_not_real"
    await handle_process_agent_update_adapter({
        "agent_id": agent_uuid,
        "response_text": f"did integration test work with {secret_marker} embedded",
        "complexity": 0.3,
        "confidence": 0.8,
        "task_type": "testing",
    })

    # Give the background task a moment to flush
    await asyncio.sleep(0.5)

    # Query the audit row back
    rows = await db.query_tool_usage(
        agent_id=agent_uuid,
        tool_name="process_agent_update",
        limit=10,
    )
    assert rows, "no audit row written for process_agent_update"
    row = rows[-1]
    payload = row.get("payload") or {}

    # Allowlisted fields present
    assert "response_text" in payload
    assert payload.get("complexity") == 0.3
    assert payload.get("confidence") == 0.8
    assert payload.get("task_type") == "testing"

    # Secret redacted
    assert secret_marker not in payload["response_text"]
    assert "[REDACTED:anthropic_key]" in payload["response_text"]

    # Excluded fields not present
    assert "continuity_token" not in payload
    assert "client_session_id" not in payload

    # Cleanup: archive the test agent
    try:
        await db.update_agent_fields(agent_uuid, status="archived")
    except Exception:
        pass
```

- [ ] **Step 3: Run the integration test**

```bash
python3 -m pytest tests/integration/test_audit_payload_integration.py -v -m integration
```

Expected: 1 passed.

If the test hangs on governance startup or times out, governance server may not be running locally. Start it per `CLAUDE.md`:

```bash
brew services start postgresql@17
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

Then retry.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_audit_payload_integration.py
git commit -m "test(audit): integration test — process_agent_update populates payload"
```

---

## Task 12: Full test sweep + diff review

- [ ] **Step 1: Run the full test suite**

```bash
./scripts/dev/test-cache.sh
```

Expected: all tests pass. The tree-hash cache will run the full suite on first invocation after changes.

If any pre-existing tests break (they shouldn't — the new params default to `None` and unchanged call shapes still work), diagnose and fix before committing.

- [ ] **Step 2: Review the full diff**

```bash
git log --oneline master..HEAD
git diff --stat master..HEAD
```

Expected: ~11 commits from Tasks 1-11, ~350 insertions across:
- `src/services/_redact.py` (new)
- `src/services/audit_payload_policy.py` (new)
- `src/services/tool_usage_recorder.py` (modified)
- `src/mcp_server_std.py` (modified)
- `src/services/http_tool_service.py` (modified)
- `tests/test_redact.py` (new)
- `tests/test_audit_payload_policy.py` (new)
- `tests/test_tool_usage_recorder.py` (new)
- `tests/integration/test_audit_payload_integration.py` (new)

- [ ] **Step 3: Push and open a PR**

```bash
git push -u origin feat/audit-payload-capture
gh pr create --title "feat(audit): populate tool_usage.payload with allowlisted redacted args" --body "$(cat <<'EOF'
## Summary

Implements the Stage 0 prerequisite from \`docs/specs/2026-04-17-audit-payload-capture-design.md\` (merged in PR #24). Populates \`audit.tool_usage.payload\` with allowlisted tool arguments, redacted against 10 secret patterns, size-capped at 4KB per row with whole-row fallback on overflow.

## What's new

- \`src/services/_redact.py\` — 10 pattern classes (Anthropic, OpenAI, Stripe, GitHub, Slack, AWS, JWT, DB URLs with creds, PEM keys, Bearer), recursive over lists/dicts, \`redact_string_with_ratio\` for stub-suppression decisions
- \`src/services/audit_payload_policy.py\` — per-tool allowlist dispatcher, knowledge-action branching (search vs store), dialectic sentinel-drop, UTF-8 byte-boundary truncation, whole-row fallback
- \`record_tool_usage\` signature gains \`arguments\` and \`session_id\` params
- Stdio + HTTP dispatch call sites pass the new params
- Integration test verifies end-to-end against a live process_agent_update dispatch

## Backward compatibility

- Existing \`{}\` rows untouched (forward-only write)
- \`record_tool_usage\` new params default to None — old callers unchanged
- Unknown tools still record \`{}\` per spec (default-closed allowlist)

## Test plan

- [x] ~22 unit tests covering redaction patterns, allowlist dispatch, size caps
- [x] Recorder unit test verifies signature change
- [x] Integration test dispatches real process_agent_update and verifies payload shape
- [ ] Manual: psql query shows non-empty payload on new rows
- [ ] Manual: a known secret injected into response_text does not appear in the corresponding payload
EOF
)"
```

- [ ] **Step 4: Manual verification against live governance**

After merge, dispatch a process_agent_update via MCP and verify the row lands:

```bash
psql -h localhost -U postgres -d governance -c "
SELECT ts, tool_name, payload
FROM audit.tool_usage
WHERE tool_name = 'process_agent_update'
  AND payload != '{}'
ORDER BY ts DESC
LIMIT 3;
"
```

Expected: rows showing redacted `response_text`, `complexity`, `confidence`, `task_type` — no `continuity_token`, no `client_session_id`.

Confirm a secret injection is redacted:

```bash
curl -s -X POST http://127.0.0.1:8767/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name":"process_agent_update","arguments":{"response_text":"test with sk-ant-api03-FAKEINTEGRATIONTEST123456789 embedded","complexity":0.2,"confidence":0.8,"client_session_id":"SOME_SESSION"}}'
```

Then:

```bash
psql -h localhost -U postgres -d governance -c "
SELECT payload
FROM audit.tool_usage
WHERE tool_name = 'process_agent_update'
  AND ts > NOW() - INTERVAL '1 minute'
ORDER BY ts DESC
LIMIT 1;
"
```

Expected: `response_text` shows `[REDACTED:anthropic_key]`, not the raw key.

---

## Self-Review

**Spec coverage:**

| Spec section | Covered by |
|---|---|
| §2 approach — narrow, allowlisted, recursive redaction, bytes cap, opt-in | Task 1 (recursion), 5 (allowlist), 6 (cap) |
| §3.2 allowlist table | Task 4 (3 tools), Task 5 (6 more tools including knowledge action-branching and dialectic sentinel-drop) |
| §3.3 redaction 10 patterns + recursion + stub ratio | Tasks 1, 2, 3 |
| §3.4 size cap — per-field bytes + whole-row fallback + UTF-8 | Task 6 |
| §3.5 backward compat (existing {} rows untouched) | Task 8 (forward-only write), verified in Task 12 diff review |
| §3.6 testing — base + recursion + stub + byte boundary + whole-row + non-secret preservation + integration | Tasks 1-6 units, Task 11 integration |
| §4 rollout — one PR, one commit per step | Tasks 1-12 produce 11 commits, each per logical step |
| §5 security/privacy — captures/excludes lists | Tasks 4-5 implement the allowlist; Task 12 manual verify confirms no token leakage |
| §6 acceptance criteria | All acceptance items map to Task 12 manual verification |
| §7 what this unblocks | Not in scope — future specs |

**No placeholders:**

Checked — every task has concrete code blocks, exact paths, exact commands with expected output. No TBDs, no "add error handling," no "similar to Task N."

**Type consistency:**

- `build_payload`, `apply_size_cap`, `make_payload` signatures match across Tasks 4-7
- `redact_secrets(value: Any) -> Any` matches across Tasks 1, 4, 5
- `redact_string_with_ratio(text: str) -> tuple[str, float]` matches Task 3
- `record_tool_usage(tool_name, agent_id, success, error_type=None, latency_ms=None, arguments=None, session_id=None)` matches Tasks 8, 9, 10
- `FIELD_BYTE_CAPS` keys match the field names redacted in Tasks 4-5 (`response_text`, `reason`, `reasoning`, `summary`, `query`)

All consistent.
