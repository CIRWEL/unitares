"""Identity v2 — session binding, persistence, resolution."""

from .handlers import (
    handle_identity_adapter,
    handle_onboard_v2,
    handle_verify_trajectory_identity,
    handle_get_trajectory_status,
    ensure_agent_persisted,
    derive_session_key,
    _agent_exists_in_postgres,
)
from .shared import get_bound_agent_id, is_session_bound
from .core import (
    resolve_session_identity,
    set_agent_label,
)
# Concurrent identity binding invariant (#123) — registers list_process_bindings.
from .process_binding_handler import handle_list_process_bindings

__all__ = [
    "handle_identity_adapter",
    "handle_onboard_v2",
    "handle_verify_trajectory_identity",
    "handle_get_trajectory_status",
    "get_bound_agent_id",
    "is_session_bound",
    "ensure_agent_persisted",
    "derive_session_key",
    "_agent_exists_in_postgres",
    "resolve_session_identity",
    "set_agent_label",
    "handle_list_process_bindings",
]
