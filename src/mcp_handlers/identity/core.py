"""
Identity core — consolidated re-exports from persistence and resolution.

Provides a single import point for the tightly-coupled persistence + resolution
modules. The implementation remains split for git-blame and test-mock stability.

Usage:
    from src.mcp_handlers.identity.core import resolve_session_identity, ensure_agent_persisted
"""

from .persistence import (
    _redis_cache,
    _get_redis,
    _cache_session,
    _agent_exists_in_postgres,
    _get_agent_status,
    _get_agent_label,
    _get_agent_id_from_metadata,
    _find_agent_by_label,
    ensure_agent_persisted,
    set_agent_label,
)

from .resolution import (
    _generate_agent_id,
    _generate_auto_label,
    _normalize_model_type,
    resolve_session_identity,
)

__all__ = [
    # persistence
    "_redis_cache",
    "_get_redis",
    "_cache_session",
    "_agent_exists_in_postgres",
    "_get_agent_status",
    "_get_agent_label",
    "_get_agent_id_from_metadata",
    "_find_agent_by_label",
    "ensure_agent_persisted",
    "set_agent_label",
    # resolution
    "_generate_agent_id",
    "_generate_auto_label",
    "_normalize_model_type",
    "resolve_session_identity",
]
