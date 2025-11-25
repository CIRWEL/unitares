"""
Audit Log for Governance System
Records all skipped lambda1 updates and auto-attestations for analysis.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import fcntl
import os


@dataclass
class AuditEntry:
    """Single audit log entry"""
    timestamp: str
    agent_id: str
    event_type: str  # "lambda1_skip", "auto_attest", "calibration_check"
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
    
    def _write_entry(self, entry: AuditEntry):
        """Write audit entry to log file with locking"""
        try:
            with open(self.log_file, 'a') as f:
                # Acquire exclusive lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(asdict(entry), f)
                    f.write('\n')
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            # Don't crash on audit log failures
            print(f"[AUDIT] Warning: Could not write audit log: {e}", file=sys.stderr)
    
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
            print(f"[AUDIT] Warning: Could not rotate log: {e}", file=sys.stderr)
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
            print(f"[AUDIT] Warning: Could not query audit log: {e}", file=sys.stderr)
            return []
        
        return results
    
    def get_skip_rate_metrics(self, agent_id: Optional[str] = None, 
                             window_hours: int = 24) -> Dict:
        """Calculate skip rate metrics from audit log"""
        if not self.log_file.exists():
            return {
                "total_skips": 0,
                "total_updates": 0,
                "skip_rate": 0.0,
                "avg_confidence": 0.0,
                "suspicious": False
            }
        
        from datetime import timedelta
        cutoff_time = datetime.now() - timedelta(hours=window_hours)
        
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
            print(f"[AUDIT] Warning: Could not read audit log: {e}", file=sys.stderr)
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

