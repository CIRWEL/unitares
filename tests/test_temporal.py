"""Tests for temporal narrator."""
from config.governance_config import GovernanceConfig


def test_temporal_config_exists():
    """Temporal narrator thresholds are defined in config."""
    assert hasattr(GovernanceConfig, 'TEMPORAL_LONG_SESSION_HOURS')
    assert hasattr(GovernanceConfig, 'TEMPORAL_GAP_HOURS')
    assert hasattr(GovernanceConfig, 'TEMPORAL_IDLE_MINUTES')
    assert hasattr(GovernanceConfig, 'TEMPORAL_CROSS_AGENT_MINUTES')
    assert hasattr(GovernanceConfig, 'TEMPORAL_HIGH_CHECKIN_COUNT')
    assert hasattr(GovernanceConfig, 'TEMPORAL_HIGH_CHECKIN_WINDOW_MINUTES')


def test_temporal_config_values():
    """Config values are sensible defaults."""
    assert GovernanceConfig.TEMPORAL_LONG_SESSION_HOURS == 2
    assert GovernanceConfig.TEMPORAL_GAP_HOURS == 24
    assert GovernanceConfig.TEMPORAL_IDLE_MINUTES == 30
    assert GovernanceConfig.TEMPORAL_CROSS_AGENT_MINUTES == 60
    assert GovernanceConfig.TEMPORAL_HIGH_CHECKIN_COUNT == 10
    assert GovernanceConfig.TEMPORAL_HIGH_CHECKIN_WINDOW_MINUTES == 30


def test_get_last_inactive_session_exists():
    """SessionMixin has get_last_inactive_session method."""
    from src.db.mixins.session import SessionMixin
    assert hasattr(SessionMixin, 'get_last_inactive_session')


def test_cross_agent_activity_method_exists():
    """StateMixin has get_recent_cross_agent_activity method."""
    from src.db.mixins.state import StateMixin
    assert hasattr(StateMixin, 'get_recent_cross_agent_activity')


def test_kg_query_accepts_created_after():
    """kg_query accepts a created_after parameter."""
    import inspect
    from src.db.mixins.knowledge_graph import KnowledgeGraphMixin
    sig = inspect.signature(KnowledgeGraphMixin.kg_query)
    assert 'created_after' in sig.parameters
