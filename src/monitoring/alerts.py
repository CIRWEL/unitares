"""
Alert System for Critical Events

Monitors system health and triggers alerts for critical conditions.
"""

from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from enum import Enum
import json
from pathlib import Path

from src.logging_utils import get_logger

logger = get_logger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alert:
    """Represents a system alert"""
    
    def __init__(
        self,
        severity: AlertSeverity,
        component: str,
        message: str,
        details: Optional[str] = None,
        timestamp: Optional[datetime] = None
    ):
        self.severity = severity
        self.component = component
        self.message = message
        self.details = details or ""
        self.timestamp = timestamp or datetime.now()
        self.acknowledged = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary"""
        return {
            "severity": self.severity.value,
            "component": self.component,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged
        }
    
    def __repr__(self):
        return f"Alert({self.severity.value}, {self.component}, {self.message})"


class AlertManager:
    """Manages system alerts"""
    
    def __init__(self, alert_file: Optional[Path] = None):
        self.alerts: List[Alert] = []
        self.alert_file = alert_file or Path("data/alerts.json")
        self.alert_handlers: List[Callable[[Alert], None]] = []
        self._load_alerts()
    
    def _load_alerts(self):
        """Load alerts from disk"""
        if self.alert_file.exists():
            try:
                with open(self.alert_file, 'r') as f:
                    data = json.load(f)
                    self.alerts = [
                        Alert(
                            severity=AlertSeverity(a["severity"]),
                            component=a["component"],
                            message=a["message"],
                            details=a.get("details"),
                            timestamp=datetime.fromisoformat(a["timestamp"])
                        )
                        for a in data.get("alerts", [])
                    ]
            except Exception as e:
                logger.warning(f"Failed to load alerts: {e}")
                self.alerts = []
    
    def _save_alerts(self):
        """Save alerts to disk"""
        try:
            self.alert_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.alert_file, 'w') as f:
                json.dump({
                    "alerts": [a.to_dict() for a in self.alerts],
                    "updated_at": datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save alerts: {e}")
    
    def register_handler(self, handler: Callable[[Alert], None]):
        """Register an alert handler (e.g., email, webhook, log)"""
        self.alert_handlers.append(handler)
    
    def trigger_alert(
        self,
        severity: AlertSeverity,
        component: str,
        message: str,
        details: Optional[str] = None
    ) -> Alert:
        """Trigger a new alert"""
        alert = Alert(severity, component, message, details)
        self.alerts.append(alert)
        
        # Keep only last 100 alerts
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]
        
        # Save to disk
        self._save_alerts()
        
        # Notify handlers
        for handler in self.alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Alert handler error: {e}")
        
        # Log alert
        log_level = {
            AlertSeverity.INFO: logger.info,
            AlertSeverity.WARNING: logger.warning,
            AlertSeverity.CRITICAL: logger.error
        }.get(severity, logger.info)
        
        log_level(f"ALERT [{severity.value.upper()}] {component}: {message}")
        if details:
            log_level(f"  Details: {details}")
        
        return alert
    
    def get_active_alerts(self, severity: Optional[AlertSeverity] = None) -> List[Alert]:
        """Get active (unacknowledged) alerts"""
        alerts = [a for a in self.alerts if not a.acknowledged]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return alerts
    
    def acknowledge_alert(self, alert_index: int):
        """Acknowledge an alert"""
        if 0 <= alert_index < len(self.alerts):
            self.alerts[alert_index].acknowledged = True
            self._save_alerts()
    
    def clear_alerts(self, severity: Optional[AlertSeverity] = None):
        """Clear alerts (optionally by severity)"""
        if severity:
            self.alerts = [a for a in self.alerts if a.severity != severity]
        else:
            self.alerts = []
        self._save_alerts()


# Global alert manager instance
_alert_manager: Optional[AlertManager] = None


def get_alert_manager(alert_file: Optional[Path] = None) -> AlertManager:
    """Get or create global alert manager"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager(alert_file)
    return _alert_manager


def trigger_alert(
    severity: AlertSeverity,
    component: str,
    message: str,
    details: Optional[str] = None
) -> Alert:
    """Convenience function to trigger an alert"""
    return get_alert_manager().trigger_alert(severity, component, message, details)


# Alert checkers for common conditions
async def check_system_health() -> List[Alert]:
    """Check system health and return any alerts"""
    alerts = []
    
    try:
        from src.mcp_handlers.shared import get_mcp_server
        mcp_server = get_mcp_server()
        
        # Check for too many paused agents
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, mcp_server.load_metadata)
        
        paused_count = sum(1 for meta in mcp_server.agent_metadata.values() 
                          if meta.status == "paused")
        if paused_count > 10:
            alerts.append(Alert(
                AlertSeverity.WARNING,
                "agents",
                f"High number of paused agents: {paused_count}",
                "Consider investigating why agents are paused"
            ))
        
        # Check for connection issues
        from src.mcp_server import connection_tracker
        connections = await connection_tracker.get_all_connections()
        if len(connections) == 0:
            alerts.append(Alert(
                AlertSeverity.WARNING,
                "connections",
                "No active connections",
                "Server may be idle or clients disconnected"
            ))
        
        # Check knowledge graph size
        try:
            from src.knowledge_graph import get_knowledge_graph
            graph = await get_knowledge_graph()
            stats = await graph.get_stats()
            nodes = stats.get("total_nodes", 0)
            if nodes > 50000:
                alerts.append(Alert(
                    AlertSeverity.INFO,
                    "knowledge_graph",
                    f"Large knowledge graph: {nodes} nodes",
                    "Consider archiving old discoveries"
                ))
        except Exception:
            pass
        
    except Exception as e:
        alerts.append(Alert(
            AlertSeverity.CRITICAL,
            "system",
            f"Health check failed: {str(e)}",
            "System health monitoring is not functioning"
        ))
    
    return alerts

