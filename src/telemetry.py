"""
Telemetry and Metrics for Governance System
Surfaces skip rates, confidence distributions, and suspicious patterns.
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import json
from pathlib import Path

from src.audit_log import audit_logger
from src.calibration import calibration_checker


class TelemetryCollector:
    """Collects and surfaces governance telemetry"""
    
    def __init__(self):
        self.audit_logger = audit_logger
        self.calibration_checker = calibration_checker
    
    def get_skip_rate_metrics(self, agent_id: Optional[str] = None,
                             window_hours: int = 24) -> Dict:
        """Get skip rate metrics from audit log"""
        return self.audit_logger.get_skip_rate_metrics(agent_id, window_hours)
    
    def get_confidence_distribution(self, agent_id: Optional[str] = None,
                                    window_hours: int = 24) -> Dict:
        """Get confidence distribution statistics"""
        if not self.audit_logger.log_file.exists():
            return {"error": "No audit log data"}
        
        cutoff_time = datetime.now() - timedelta(hours=window_hours)
        
        confidences = []
        
        try:
            with open(self.audit_logger.log_file, 'r') as f:
                for line in f:
                    try:
                        entry_dict = json.loads(line.strip())
                        entry_time = datetime.fromisoformat(entry_dict['timestamp'])
                        
                        if entry_time < cutoff_time:
                            continue
                        
                        if agent_id and entry_dict['agent_id'] != agent_id:
                            continue
                        
                        if 'confidence' in entry_dict:
                            confidences.append(entry_dict['confidence'])
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception as e:
            return {"error": str(e)}
        
        if not confidences:
            return {"error": "No confidence data"}
        
        import numpy as np
        confidences_array = np.array(confidences)
        
        return {
            "count": len(confidences),
            "mean": float(np.mean(confidences_array)),
            "median": float(np.median(confidences_array)),
            "std": float(np.std(confidences_array)),
            "min": float(np.min(confidences_array)),
            "max": float(np.max(confidences_array)),
            "percentiles": {
                "p25": float(np.percentile(confidences_array, 25)),
                "p50": float(np.percentile(confidences_array, 50)),
                "p75": float(np.percentile(confidences_array, 75)),
                "p90": float(np.percentile(confidences_array, 90)),
                "p95": float(np.percentile(confidences_array, 95))
            },
            "low_confidence_rate": float(np.mean(confidences_array < 0.8)),
            "high_confidence_rate": float(np.mean(confidences_array >= 0.8))
        }
    
    def get_calibration_metrics(self) -> Dict:
        """Get calibration metrics"""
        is_calibrated, metrics = self.calibration_checker.check_calibration()
        return {
            "is_calibrated": is_calibrated,
            **metrics
        }
    
    def detect_suspicious_patterns(self, agent_id: Optional[str] = None) -> Dict:
        """
        Detect suspicious patterns:
        - Low skip rate but low average confidence (suggests agreeableness)
        - High skip rate but high average confidence (suggests over-conservatism)
        """
        skip_metrics = self.get_skip_rate_metrics(agent_id)
        conf_dist = self.get_confidence_distribution(agent_id)
        
        if "error" in skip_metrics or "error" in conf_dist:
            return {"error": "Insufficient data"}
        
        patterns = []
        
        # Use configurable thresholds
        from config.governance_config import config
        
        # Pattern 1: Low skip rate + low confidence = suspicious (agreeableness)
        if (skip_metrics['skip_rate'] < config.SUSPICIOUS_LOW_SKIP_RATE and 
            conf_dist['mean'] < config.SUSPICIOUS_LOW_CONFIDENCE):
            patterns.append({
                "pattern": "low_skip_low_confidence",
                "severity": "high",
                "description": "Low skip rate but low average confidence suggests agreeableness (auto-approving everything)",
                "skip_rate": skip_metrics['skip_rate'],
                "avg_confidence": conf_dist['mean'],
                "thresholds_used": {
                    "skip_rate": config.SUSPICIOUS_LOW_SKIP_RATE,
                    "confidence": config.SUSPICIOUS_LOW_CONFIDENCE
                }
            })
        
        # Pattern 2: High skip rate + high confidence = suspicious (over-conservatism)
        if (skip_metrics['skip_rate'] > config.SUSPICIOUS_HIGH_SKIP_RATE and 
            conf_dist['mean'] > config.SUSPICIOUS_HIGH_CONFIDENCE):
            patterns.append({
                "pattern": "high_skip_high_confidence",
                "severity": "medium",
                "description": "High skip rate despite high confidence suggests over-conservatism",
                "skip_rate": skip_metrics['skip_rate'],
                "avg_confidence": conf_dist['mean'],
                "thresholds_used": {
                    "skip_rate": config.SUSPICIOUS_HIGH_SKIP_RATE,
                    "confidence": config.SUSPICIOUS_HIGH_CONFIDENCE
                }
            })
        
        return {
            "suspicious_patterns": patterns,
            "skip_metrics": skip_metrics,
            "confidence_distribution": conf_dist
        }
    
    def get_comprehensive_metrics(self, agent_id: Optional[str] = None) -> Dict:
        """Get comprehensive telemetry metrics"""
        return {
            "skip_rate": self.get_skip_rate_metrics(agent_id),
            "confidence_distribution": self.get_confidence_distribution(agent_id),
            "calibration": self.get_calibration_metrics(),
            "suspicious_patterns": self.detect_suspicious_patterns(agent_id)
        }


# Global telemetry collector instance
telemetry_collector = TelemetryCollector()

