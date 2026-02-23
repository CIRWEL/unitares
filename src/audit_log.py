"""
Audit Log for Governance System
Records all skipped lambda1 updates and auto-attestations for analysis.

JSONL is the raw truth log. PostgreSQL provides queryable indexing.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import fcntl
import os

# Import structured logging
from src.logging_utils import get_logger
logger = get_logger(__name__)


@dataclass
class AuditEntry:
    """Single audit log entry"""
    timestamp: str
    agent_id: str
    event_type: str  # "lambda1_skip", "auto_attest", "calibration_check", "complexity_derivation"
    confidence: float
    details: Dict
    metadata: Optional[Dict] = None


class AuditLogger:
    """Manages audit logging for governance system"""

    def __init__(self, log_file: Optional[Path] = None):
        if log_file is None:
            project_root = Path(__file__).parent.parent
            log_file = project_root / "data" / "audit_log.jsonl"

        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self._jsonl_enabled = os.getenv("UNITARES_AUDIT_WRITE_JSONL", "1").strip().lower() not in ("0", "false", "no")
    
    def log_lambda1_skip(self, agent_id: str, confidence: float, threshold: float, 
                         update_count: int, reason: str = None):
        """Log a skipped lambda1 update"""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            event_type="lambda1_skip",
            confidence=confidence,
            details={
                "threshold": threshold,
                "update_count": update_count,
                "reason": reason or f"confidence {confidence:.3f} < threshold {threshold:.3f}"
            }
        )
        self._write_entry(entry)
    
    def log_auto_attest(self, agent_id: str, confidence: float, ci_passed: bool,
                       risk_score: float, decision: str, details: Dict = None):
        """Log an auto-attestation event"""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            event_type="auto_attest",
            confidence=confidence,
            details={
                "ci_passed": ci_passed,
                "risk_score": risk_score,
                "decision": decision,
                **(details or {})
            }
        )
        self._write_entry(entry)
    
    def log_complexity_derivation(self, agent_id: str, reported_complexity: Optional[float],
                                 derived_complexity: float, final_complexity: float,
                                 discrepancy: Optional[float] = None, details: Dict = None):
        """
        Log complexity derivation for tracking and calibration.
        
        Tracks reported vs derived complexity to:
        - Calibrate the 0.3 discrepancy threshold
        - Identify gaming attempts
        - Validate effectiveness of derivation
        """
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            event_type="complexity_derivation",
            confidence=1.0,  # Not a confidence event, but required field
            details={
                "reported_complexity": reported_complexity,
                "derived_complexity": round(derived_complexity, 3),
                "final_complexity": round(final_complexity, 3),
                "discrepancy": round(discrepancy, 3) if discrepancy is not None else None,
                "discrepancy_threshold_exceeded": discrepancy is not None and abs(discrepancy) > 0.3 if discrepancy is not None else False,
                **(details or {})
            }
        )
        self._write_entry(entry)
    
    def log_calibration_check(self, agent_id: str, confidence_bin: str, 
                            predicted_correct: bool, actual_correct: bool,
                            calibration_metrics: Dict):
        """Log a calibration check result"""
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            event_type="calibration_check",
            confidence=float(confidence_bin.split('-')[0]) if '-' in confidence_bin else 0.0,
            details={
                "confidence_bin": confidence_bin,
                "predicted_correct": predicted_correct,
                "actual_correct": actual_correct,
                "calibration_metrics": calibration_metrics
            }
        )
        self._write_entry(entry)
    
    def log_auto_resume(self, agent_id: str, previous_status: str, 
                       trigger: str, archived_at: Optional[str] = None,
                       details: Optional[Dict] = None):
        """
        Log an auto-resume event when an archived agent engages with the system.
        
        Args:
            agent_id: Agent identifier
            previous_status: Previous lifecycle status (should be "archived")
            trigger: What triggered the auto-resume (e.g., "process_agent_update")
            archived_at: ISO timestamp when agent was archived (if available)
            details: Additional context (e.g., days_since_archive)
        """
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            event_type="auto_resume",
            confidence=1.0,  # Not a confidence event, but required field
            details={
                "previous_status": previous_status,
                "trigger": trigger,
                "archived_at": archived_at,
                **(details or {})
            }
        )
        self._write_entry(entry)

    def log_dialectic_nudge(self, agent_id: str, session_id: str, phase: str,
                            next_actor: Optional[str] = None,
                            idle_seconds: Optional[float] = None,
                            details: Optional[Dict] = None):
        """
        Log a lightweight dialectic/exploration 'nudge' event.

        This is intentionally low-ceremony and does NOT mutate session transcripts
        (so it won't interfere with timeout/auto-resolve logic).
        """
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id or "system",
            event_type="dialectic_nudge",
            confidence=1.0,
            details={
                "session_id": session_id,
                "phase": phase,
                "next_actor": next_actor,
                "idle_seconds": idle_seconds,
                **(details or {})
            }
        )
        self._write_entry(entry)
    
    # NOTE: log_knowledge_visibility_warning removed (knowledge layer archived November 28, 2025)

    # ============================================================
    # Cross-Device Audit Events (Mac↔Pi Orchestration)
    # ============================================================

    def log_cross_device_call(self, agent_id: str, source_device: str, target_device: str,
                              tool_name: str, arguments: Dict, status: str = "initiated",
                              latency_ms: Optional[float] = None, error: Optional[str] = None,
                              details: Optional[Dict] = None):
        """
        Log a cross-device MCP tool call (Mac↔Pi orchestration).

        Args:
            agent_id: Agent making the call
            source_device: Device initiating call ("mac" or "pi")
            target_device: Device receiving call ("mac" or "pi")
            tool_name: Name of the tool being called
            arguments: Tool arguments (sanitized - no secrets)
            status: "initiated", "success", "error", "timeout"
            latency_ms: Round-trip latency in milliseconds
            error: Error message if status is "error"
            details: Additional context
        """
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            event_type="cross_device_call",
            confidence=1.0,
            details={
                "source_device": source_device,
                "target_device": target_device,
                "tool_name": tool_name,
                "arguments": arguments,
                "status": status,
                "latency_ms": latency_ms,
                "error": error,
                **(details or {})
            }
        )
        self._write_entry(entry)

    def log_orchestration_request(self, agent_id: str, workflow: str, target_device: str,
                                  tools_planned: List[str], context: Optional[Dict] = None,
                                  details: Optional[Dict] = None):
        """
        Log an orchestration request (Mac planning multi-step Pi coordination).

        Args:
            agent_id: Agent initiating orchestration
            workflow: Name of the workflow being executed
            target_device: Target device for orchestration
            tools_planned: List of tools to be called
            context: Workflow context (e.g., trigger, goals)
            details: Additional metadata
        """
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            event_type="orchestration_request",
            confidence=1.0,
            details={
                "workflow": workflow,
                "target_device": target_device,
                "tools_planned": tools_planned,
                "context": context,
                **(details or {})
            }
        )
        self._write_entry(entry)

    def log_orchestration_complete(self, agent_id: str, workflow: str, target_device: str,
                                   tools_executed: List[str], success: bool,
                                   total_latency_ms: float, errors: Optional[List[str]] = None,
                                   results_summary: Optional[Dict] = None,
                                   details: Optional[Dict] = None):
        """
        Log orchestration completion with summary metrics.

        Args:
            agent_id: Agent that ran orchestration
            workflow: Name of the completed workflow
            target_device: Target device
            tools_executed: List of tools that were executed
            success: Whether all tools completed successfully
            total_latency_ms: Total workflow latency
            errors: List of any errors encountered
            results_summary: High-level summary of results
            details: Additional metadata
        """
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            event_type="orchestration_complete",
            confidence=1.0,
            details={
                "workflow": workflow,
                "target_device": target_device,
                "tools_executed": tools_executed,
                "success": success,
                "total_latency_ms": total_latency_ms,
                "errors": errors or [],
                "results_summary": results_summary,
                **(details or {})
            }
        )
        self._write_entry(entry)

    def log_device_health_check(self, agent_id: str, device: str, status: str,
                                latency_ms: Optional[float] = None,
                                components: Optional[Dict[str, str]] = None,
                                details: Optional[Dict] = None):
        """
        Log a device health check (connectivity, service status).

        Args:
            agent_id: Agent performing health check
            device: Device being checked ("mac" or "pi")
            status: "healthy", "degraded", "unreachable", "error"
            latency_ms: Health check latency
            components: Component-level status (e.g., {"sensors": "ok", "display": "ok"})
            details: Additional context
        """
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            event_type="device_health_check",
            confidence=1.0,
            details={
                "device": device,
                "status": status,
                "latency_ms": latency_ms,
                "components": components or {},
                **(details or {})
            }
        )
        self._write_entry(entry)

    def log_eisv_sync(self, agent_id: str, source_device: str, target_device: str,
                      anima_state: Dict, eisv_mapped: Dict, sync_direction: str = "pi_to_mac",
                      details: Optional[Dict] = None):
        """
        Log EISV state synchronization between devices.

        Maps Anima state (Pi) to EISV governance state (Mac):
        - Warmth → Energy (E)
        - Clarity → Integrity (I)
        - 1 - Stability → Entropy (S)
        - (1 - Presence) × 0.3 → Void (V)  [observation-layer seed; ODE evolves independently]

        Args:
            agent_id: Agent performing sync
            source_device: Device providing state
            target_device: Device receiving state
            anima_state: Raw anima values from Pi
            eisv_mapped: Mapped EISV values
            sync_direction: "pi_to_mac" or "mac_to_pi"
            details: Additional context
        """
        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            agent_id=agent_id,
            event_type="eisv_sync",
            confidence=1.0,
            details={
                "source_device": source_device,
                "target_device": target_device,
                "anima_state": anima_state,
                "eisv_mapped": eisv_mapped,
                "sync_direction": sync_direction,
                **(details or {})
            }
        )
        self._write_entry(entry)

    def _write_entry(self, entry: AuditEntry):
        """Write audit entry to JSONL log file with locking"""
        try:
            entry_dict = asdict(entry)

            # Raw truth: JSONL append
            if self._jsonl_enabled:
                with open(self.log_file, 'a') as f:
                    # Acquire exclusive lock
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        json.dump(entry_dict, f)
                        f.write('\n')
                        f.flush()
                        os.fsync(f.fileno())
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            # Don't crash on audit log failures
            logger.warning(f"Could not write audit log: {e}", exc_info=True)
    
    def rotate_log(self, max_age_days: int = 30):
        """
        Rotate audit log: archive old entries, keep recent ones.
        
        Args:
            max_age_days: Keep entries newer than this many days
        """
        if not self.log_file.exists():
            return
        
        from datetime import timedelta
        cutoff_time = datetime.now() - timedelta(days=max_age_days)
        
        # Create archive directory
        archive_dir = self.log_file.parent / "audit_log_archive"
        archive_dir.mkdir(exist_ok=True)
        
        # Archive old entries
        archived_file = archive_dir / f"audit_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
        recent_entries = []
        
        try:
            with open(self.log_file, 'r') as f:
                for line in f:
                    try:
                        entry_dict = json.loads(line.strip())
                        entry_time = datetime.fromisoformat(entry_dict['timestamp'])
                        
                        if entry_time < cutoff_time:
                            # Archive old entry
                            with open(archived_file, 'a') as af:
                                af.write(line)
                        else:
                            # Keep recent entry
                            recent_entries.append(line)
                    except (json.JSONDecodeError, KeyError):
                        continue
            
            # Rewrite log file with only recent entries
            with open(self.log_file, 'w') as f:
                f.writelines(recent_entries)
            
            return len(recent_entries), archived_file
        except Exception as e:
            logger.warning(f"Could not rotate log: {e}", exc_info=True)
            return None, None
    
    def query_audit_log(self, agent_id: Optional[str] = None,
                       event_type: Optional[str] = None,
                       start_time: Optional[str] = None,
                       end_time: Optional[str] = None,
                       limit: int = 1000) -> List[Dict]:
        """
        Query audit log with filters.
        
        Args:
            agent_id: Filter by agent ID
            event_type: Filter by event type ("lambda1_skip", "auto_attest", "calibration_check")
            start_time: ISO format timestamp (inclusive)
            end_time: ISO format timestamp (inclusive)
            limit: Maximum number of entries to return
        """
        if not self.log_file.exists():
            return []
        
        results = []
        
        try:
            start_dt = datetime.fromisoformat(start_time) if start_time else None
            end_dt = datetime.fromisoformat(end_time) if end_time else None
            
            with open(self.log_file, 'r') as f:
                for line in f:
                    if len(results) >= limit:
                        break
                    
                    try:
                        entry_dict = json.loads(line.strip())
                        
                        # Apply filters
                        if agent_id and entry_dict.get('agent_id') != agent_id:
                            continue
                        
                        if event_type and entry_dict.get('event_type') != event_type:
                            continue
                        
                        if start_dt or end_dt:
                            entry_time = datetime.fromisoformat(entry_dict['timestamp'])
                            if start_dt and entry_time < start_dt:
                                continue
                            if end_dt and entry_time > end_dt:
                                continue
                        
                        results.append(entry_dict)
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception as e:
            logger.warning(f"Could not query audit log: {e}", exc_info=True)
            return []
        
        return results
    
    def get_skip_rate_metrics(self, agent_id: Optional[str] = None, 
                             window_hours: int = 24) -> Dict:
        """Calculate skip rate metrics from audit log"""
        from datetime import timedelta
        cutoff_time = datetime.now() - timedelta(hours=window_hours)

        if not self.log_file.exists():
            return {
                "total_skips": 0,
                "total_updates": 0,
                "skip_rate": 0.0,
                "avg_confidence": 0.0,
                "suspicious": False
            }
        
        total_skips = 0
        total_updates = 0
        confidence_sum = 0.0
        confidence_count = 0
        
        try:
            with open(self.log_file, 'r') as f:
                for line in f:
                    try:
                        entry_dict = json.loads(line.strip())
                        entry_time = datetime.fromisoformat(entry_dict['timestamp'])
                        
                        if entry_time < cutoff_time:
                            continue
                        
                        if agent_id and entry_dict['agent_id'] != agent_id:
                            continue
                        
                        if entry_dict['event_type'] == 'lambda1_skip':
                            total_skips += 1
                            confidence_sum += entry_dict['confidence']
                            confidence_count += 1
                        elif entry_dict['event_type'] == 'auto_attest':
                            total_updates += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception as e:
            logger.warning(f"Could not read audit log: {e}", exc_info=True)
            return {"error": str(e)}
        
        avg_confidence = confidence_sum / confidence_count if confidence_count > 0 else 0.0
        skip_rate = total_skips / (total_skips + total_updates) if (total_skips + total_updates) > 0 else 0.0
        
        # Suspicious pattern: low skip rate but low average confidence (configurable thresholds)
        from config.governance_config import config
        suspicious = (skip_rate < config.SUSPICIOUS_LOW_SKIP_RATE and 
                     avg_confidence < config.SUSPICIOUS_LOW_CONFIDENCE and 
                     total_skips + total_updates > 10)
        
        return {
            "total_skips": total_skips,
            "total_updates": total_updates,
            "skip_rate": skip_rate,
            "avg_confidence": avg_confidence,
            "suspicious": suspicious,
            "window_hours": window_hours
        }


# Global audit logger instance
audit_logger = AuditLogger()

