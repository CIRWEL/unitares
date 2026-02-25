"""
UpdateContext — Shared state for process_agent_update phases.

Replaces the ~20+ local variables threaded through the original monolithic function.
Each phase reads/writes fields on this dataclass instead of relying on closure scope.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UpdateContext:
    """Carries state between extracted update phases and enrichments."""

    # ── Raw arguments ──────────────────────────────────────────────
    arguments: Dict[str, Any] = field(default_factory=dict)

    # ── Identity (Phase 1) ─────────────────────────────────────────
    agent_uuid: str = ""
    agent_id: str = ""           # Same as agent_uuid (backward compat alias)
    session_key: Optional[str] = None
    declared_agent_id: str = ""
    label: Optional[str] = None
    is_new_agent: bool = False
    meta: Optional[Any] = None   # AgentMetadata instance

    # ── Validated inputs (Phase 3) ─────────────────────────────────
    response_text: str = ""
    complexity: float = 0.5
    confidence: Optional[float] = None
    ethical_drift: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    task_type: str = "mixed"
    calibration_correction_info: Optional[str] = None

    # ── Onboarding / auto-resume (Phase 2) ─────────────────────────
    onboarding_guidance: Optional[Dict] = None
    auto_resume_info: Optional[Dict] = None
    dialectic_enforcement_warning: Optional[str] = None

    # ── Core result (Phase 4) ──────────────────────────────────────
    result: Dict[str, Any] = field(default_factory=dict)
    monitor: Optional[Any] = None   # UNITARESMonitor instance
    agent_state: Dict[str, Any] = field(default_factory=dict)

    # ── Side effects (Phase 5) ─────────────────────────────────────
    health_status: Optional[Any] = None
    health_message: str = ""
    metrics_dict: Dict[str, Any] = field(default_factory=dict)
    risk_score: Optional[float] = None
    coherence: Optional[float] = None
    cirs_alert: Optional[Dict] = None
    cirs_state_announce: Optional[Dict] = None
    outcome_event_id: Optional[str] = None

    # ── Response accumulator (Phase 6) ─────────────────────────────
    response_data: Dict[str, Any] = field(default_factory=dict)

    # ── Flags ──────────────────────────────────────────────────────
    key_was_generated: bool = False
    api_key_auto_retrieved: bool = False
    api_key: Optional[str] = None
    policy_warnings: List[str] = field(default_factory=list)
    loop_info: Optional[Dict] = None
    warnings: List[str] = field(default_factory=list)
    previous_void_active: bool = False

    # ── Runtime references (set by orchestrator) ─────────────────
    loop: Optional[Any] = None       # asyncio event loop
    mcp_server: Optional[Any] = None # mcp_server_std module (from core.py's patched ref)
