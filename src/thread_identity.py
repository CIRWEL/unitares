"""
Thread-based identity with honest forking.

Pure logic module — no I/O, no database calls.
Imported by identity_v2.py for thread context construction.

A thread is the user's conversation — the true identity anchor.
A fork is each new agent instance, with a numbered position.
Discontinuities are made legible, not hidden (kintsugi model).
"""

from __future__ import annotations

import hashlib
from typing import Optional


def generate_thread_id(session_key: str) -> str:
    """
    Derive a stable thread ID from a session key.

    For MCP sessions (stable per connection): use the session ID portion.
    For IP:UA fingerprints: use the UA hash (stable across IP rotation).
    For stdio:{pid}: use pid-based key.

    Returns a short opaque ID prefixed with "t-".
    """
    if session_key.startswith("mcp:"):
        raw = session_key[4:]
    elif ":" in session_key:
        # IP:UA or model-suffixed key — use the stable portion
        parts = session_key.split(":")
        # Skip IP-like first parts, use the rest
        raw = ":".join(parts[1:]) if len(parts) >= 2 else session_key
    else:
        raw = session_key

    return "t-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def infer_spawn_reason(
    arguments: dict,
    existing_nodes: list[dict],
) -> str:
    """
    Infer why this fork was created from available signals.

    Priority:
    1. Explicit caller-provided spawn_reason
    2. Claude Code client + existing thread nodes → "compaction"
    3. parent_agent_id present → "subagent"
    4. Existing thread nodes → "new_session"
    5. Default → "new_session"
    """
    explicit = arguments.get("spawn_reason")
    if explicit:
        return explicit

    if existing_nodes:
        client_hint = arguments.get("client_hint", "")
        if "claude_code" in client_hint or "claude-code" in client_hint:
            return "compaction"
        if arguments.get("parent_agent_id"):
            return "subagent"
        return "new_session"

    return "new_session"


_REASON_DESCRIPTIONS = {
    "compaction": "context compaction (context window reset)",
    "subagent": "subagent spawn (Task tool)",
    "new_session": "new session start",
    "explicit": "explicit fork request",
}


def build_fork_context(
    thread_id: str,
    position: int,
    parent_uuid: Optional[str],
    spawn_reason: str,
    all_nodes: list[dict],
) -> dict:
    """
    Build the fork context dict that the onboard response embeds.

    This is the kintsugi structure — the legible discontinuity map.

    Returns dict with: thread_id, position, spawn_reason, predecessor,
    thread_size, is_root, is_fork, honest_message.
    """
    is_root = position == 1
    is_fork = position > 1

    # Find predecessor
    predecessor = None
    if parent_uuid:
        parent_node = next(
            (n for n in all_nodes if n.get("agent_id") == parent_uuid),
            None,
        )
        if parent_node:
            predecessor = {
                "uuid": parent_uuid,
                "position": parent_node.get("thread_position"),
                "label": parent_node.get("label"),
            }

    # If no explicit parent but we're a fork, use the previous position as predecessor
    if not predecessor and is_fork and all_nodes:
        prev_nodes = [
            n for n in all_nodes
            if n.get("thread_position") is not None
            and n["thread_position"] < position
        ]
        if prev_nodes:
            prev_node = max(prev_nodes, key=lambda n: n["thread_position"])
            predecessor = {
                "uuid": prev_node.get("agent_id"),
                "position": prev_node.get("thread_position"),
                "label": prev_node.get("label"),
            }

    # Build honest message
    thread_short = thread_id[:12]
    reason_str = _REASON_DESCRIPTIONS.get(spawn_reason, spawn_reason or "unknown reason")

    if is_root:
        honest_message = (
            f"You are node 1 in thread {thread_short}. "
            "This is the start of this conversation thread."
        )
    else:
        if predecessor and predecessor.get("label"):
            pred_desc = predecessor["label"]
        elif predecessor and predecessor.get("position"):
            pred_desc = f"node {predecessor['position']}"
        else:
            pred_desc = "a previous instance"

        honest_message = (
            f"You are node {position} in thread {thread_short}. "
            f"Your predecessor was {pred_desc} — "
            f"a new context was created due to {reason_str}. "
            "You share the same trajectory lineage but you are a distinct instance. "
            "This discontinuity is real and has been recorded."
        )

    return {
        "thread_id": thread_id,
        "position": position,
        "spawn_reason": spawn_reason,
        "predecessor": predecessor,
        "thread_size": len(all_nodes),
        "is_root": is_root,
        "is_fork": is_fork,
        "honest_message": honest_message,
    }
