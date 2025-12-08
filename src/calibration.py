"""
Calibration Checking System
Bins predictions by confidence and measures real accuracy to detect miscalibration.
"""

from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import json
import sys
import numpy as np


@dataclass
class CalibrationBin:
    """Calibration bin statistics"""
    bin_range: Tuple[float, float]  # (min, max) confidence
    count: int
    predicted_correct: int  # How many times we predicted correct
    actual_correct: int     # How many times we were actually correct
    accuracy: float         # actual_correct / count
    expected_accuracy: float  # Mean confidence in this bin
    calibration_error: float   # |accuracy - expected_accuracy|


class CalibrationChecker:
    """Checks calibration of confidence estimates"""
    
    def __init__(self, bins: List[Tuple[float, float]] = None, state_file: Path = None):
        """
        Initialize calibration checker with confidence bins.
        
        Default bins:
        - [0.0, 0.5]: Low confidence
        - [0.5, 0.7]: Medium-low confidence
        - [0.7, 0.8]: Medium-high confidence
        - [0.8, 0.9]: High confidence
        - [0.9, 1.0]: Very high confidence
        
        Args:
            bins: Confidence bins for calibration
            state_file: Path to calibration state file (defaults to data/calibration_state.json)
        """
        if bins is None:
            bins = [
                (0.0, 0.5),
                (0.5, 0.7),
                (0.7, 0.8),
                (0.8, 0.9),
                (0.9, 1.0)
            ]
        self.bins = bins
        
        # Set up state file path
        if state_file is None:
            state_file = Path(__file__).parent.parent / "data" / "calibration_state.json"
        self.state_file = Path(state_file)
        
        # Load existing state or reset
        if self.state_file.exists():
            self.load_state()
        else:
            self.reset()
    
    def reset(self):
        """Reset calibration statistics"""
        self.bin_stats = defaultdict(lambda: {
            'count': 0,
            'predicted_correct': 0,
            'actual_correct': 0,
            'confidence_sum': 0.0
        })
    
    def record_prediction(self, confidence: float, predicted_correct: bool, 
                         actual_correct: bool):
        """
        Record a prediction for calibration checking.
        
        Args:
            confidence: Confidence estimate (0-1)
            predicted_correct: Whether we predicted correct (based on confidence threshold)
            actual_correct: Whether prediction was actually correct (ground truth)
        """
        # Find which bin this confidence falls into
        bin_key = None
        for bin_min, bin_max in self.bins:
            if bin_min <= confidence < bin_max or (bin_max == 1.0 and confidence == 1.0):
                bin_key = f"{bin_min:.1f}-{bin_max:.1f}"
                break
        
        if bin_key is None:
            # Fallback to nearest bin
            bin_key = f"{self.bins[-1][0]:.1f}-{self.bins[-1][1]:.1f}"
        
        stats = self.bin_stats[bin_key]
        stats['count'] += 1
        stats['confidence_sum'] += confidence
        
        if predicted_correct:
            stats['predicted_correct'] += 1
        
        # Only update actual_correct if provided (ground truth)
        if actual_correct is not None:
            if actual_correct:
                stats['actual_correct'] += 1
            # Auto-save after recording prediction with ground truth
            self.save_state()
    
    def compute_calibration_metrics(self) -> Dict[str, CalibrationBin]:
        """Compute calibration metrics for each bin"""
        results = {}
        
        for bin_key, stats in self.bin_stats.items():
            if stats['count'] == 0:
                continue
            
            # Parse bin range
            bin_min, bin_max = map(float, bin_key.split('-'))
            
            accuracy = stats['actual_correct'] / stats['count']
            expected_accuracy = stats['confidence_sum'] / stats['count']
            calibration_error = abs(accuracy - expected_accuracy)
            
            results[bin_key] = CalibrationBin(
                bin_range=(bin_min, bin_max),
                count=stats['count'],
                predicted_correct=stats['predicted_correct'],
                actual_correct=stats['actual_correct'],
                accuracy=accuracy,
                expected_accuracy=expected_accuracy,
                calibration_error=calibration_error
            )
        
        return results
    
    def check_calibration(self, min_samples_per_bin: int = 10) -> Tuple[bool, Dict]:
        """
        Check if calibration is acceptable.
        
        Returns:
            (is_calibrated, metrics_dict)
        """
        metrics = self.compute_calibration_metrics()
        
        if not metrics:
            return False, {"error": "No calibration data"}
        
        # Check each bin
        issues = []
        for bin_key, bin_metrics in metrics.items():
            if bin_metrics.count < min_samples_per_bin:
                issues.append(f"Bin {bin_key}: insufficient samples ({bin_metrics.count} < {min_samples_per_bin})")
                continue
            
            # High confidence bins should have high accuracy
            if bin_metrics.bin_range[0] >= 0.8:
                if bin_metrics.accuracy < 0.7:  # 0.8→0.9 bin only 50% accurate = miscalibrated
                    issues.append(
                        f"Bin {bin_key}: high confidence ({bin_metrics.expected_accuracy:.2f}) "
                        f"but low accuracy ({bin_metrics.accuracy:.2f})"
                    )
            
            # Large calibration error indicates miscalibration
            if bin_metrics.calibration_error > 0.2:
                issues.append(
                    f"Bin {bin_key}: large calibration error ({bin_metrics.calibration_error:.2f})"
                )
        
        is_calibrated = len(issues) == 0
        
        return is_calibrated, {
            "is_calibrated": is_calibrated,
            "issues": issues,
            "bins": {k: {
                "count": v.count,
                "accuracy": v.accuracy,
                "expected_accuracy": v.expected_accuracy,
                "calibration_error": v.calibration_error
            } for k, v in metrics.items()}
        }
    
    def update_ground_truth(self, confidence: float, predicted_correct: bool, 
                           actual_correct: bool):
        """
        Update calibration with ground truth after human review.
        
        This allows calibration to work properly by updating actual_correct
        after the fact (e.g., after human review determines if decision was correct).
        
        IMPORTANT: Each call to update_ground_truth represents a NEW prediction.
        If you're updating ground truth for a prediction that was already recorded
        via record_prediction(), you should track that separately. This method
        will always increment count to ensure proper accounting.
        """
        # Find the bin
        bin_key = None
        for bin_min, bin_max in self.bins:
            if bin_min <= confidence < bin_max or (bin_max == 1.0 and confidence == 1.0):
                bin_key = f"{bin_min:.1f}-{bin_max:.1f}"
                break
        
        if bin_key is None:
            bin_key = f"{self.bins[-1][0]:.1f}-{self.bins[-1][1]:.1f}"
        
        stats = self.bin_stats[bin_key]
        
        # Always record this as a new prediction
        # This ensures count tracks all predictions, even if record_prediction wasn't called
        stats['count'] += 1
        stats['confidence_sum'] += confidence
        if predicted_correct:
            stats['predicted_correct'] += 1
        
        # Update actual correctness
        if actual_correct:
            stats['actual_correct'] += 1
        # Note: We don't increment actual_correct if actual_correct=False because
        # we're tracking how many were actually correct, not total ground truth updates
        
        # Ensure actual_correct never exceeds count (safety check)
        if stats['actual_correct'] > stats['count']:
            stats['actual_correct'] = stats['count']
    
    def get_pending_updates(self) -> int:
        """Get count of predictions waiting for ground truth"""
        total_predictions = sum(s['count'] for s in self.bin_stats.values())
        total_ground_truth = sum(s['actual_correct'] for s in self.bin_stats.values())
        pending = total_predictions - total_ground_truth
        # Ensure pending_updates never goes negative (safety check)
        return max(0, pending)
    
    def update_from_peer_verification(self, confidence: float, predicted_correct: bool, 
                                     peer_agreed: bool, weight: float = 0.7):
        """
        Update calibration from peer verification (dialectic convergence).
        
        Uses peer agreement as a proxy for correctness, with configurable weight.
        This acknowledges that peer verification is valuable for uncertainty detection
        but is not definitive ground truth.
        
        Args:
            confidence: Original confidence estimate
            predicted_correct: Whether we predicted correct
            peer_agreed: Whether peer agents agreed (converged)
            weight: Weight for peer verification (default 0.7 = 70% of human ground truth)
        """
        # Find the bin
        bin_key = None
        for bin_min, bin_max in self.bins:
            if bin_min <= confidence < bin_max or (bin_max == 1.0 and confidence == 1.0):
                bin_key = f"{bin_min:.1f}-{bin_max:.1f}"
                break
        
        if bin_key is None:
            bin_key = f"{self.bins[-1][0]:.1f}-{self.bins[-1][1]:.1f}"
        
        stats = self.bin_stats[bin_key]
        
        # Record prediction
        stats['count'] += 1
        stats['confidence_sum'] += confidence
        if predicted_correct:
            stats['predicted_correct'] += 1
        
        # Update actual correctness with weighted peer agreement
        # If peers agreed, treat as "probably correct" (weighted)
        # This is a proxy, not ground truth - acknowledge uncertainty
        if peer_agreed:
            # Weighted update: peer agreement counts as partial correctness
            # We increment by weight (0.7 = 70% confidence in correctness)
            # This is tracked separately from human ground truth
            stats['actual_correct'] += weight
        
        # Ensure actual_correct never exceeds count (safety check)
        if stats['actual_correct'] > stats['count']:
            stats['actual_correct'] = stats['count']
        
        # Save state after update
        self.save_state()
    
    def update_from_peer_disagreement(self, confidence: float, predicted_correct: bool, 
                                      disagreement_severity: float = 0.5):
        """
        Update calibration from peer disagreement (dialectic escalation/failure).
        
        Disagreement indicates the agent was overconfident - their confidence was too high
        for the actual uncertainty in the situation. This lowers the effective calibration
        by treating disagreement as a signal that confidence should have been lower.
        
        Args:
            confidence: Original confidence estimate (which was too high)
            predicted_correct: Whether we predicted correct
            disagreement_severity: How severe the disagreement was (0.0-1.0)
                                  - 0.5 = moderate disagreement (default)
                                  - 1.0 = complete failure to converge
                                  - 0.0 = minor disagreement
        """
        # Find the bin
        bin_key = None
        for bin_min, bin_max in self.bins:
            if bin_min <= confidence < bin_max or (bin_max == 1.0 and confidence == 1.0):
                bin_key = f"{bin_min:.1f}-{bin_max:.1f}"
                break
        
        if bin_key is None:
            bin_key = f"{self.bins[-1][0]:.1f}-{self.bins[-1][1]:.1f}"
        
        stats = self.bin_stats[bin_key]
        
        # Record prediction
        stats['count'] += 1
        stats['confidence_sum'] += confidence
        if predicted_correct:
            stats['predicted_correct'] += 1
        
        # Disagreement means confidence was too high
        # We treat this as "actual correctness was lower than predicted"
        # The severity determines how much we lower the actual_correct count
        # Higher severity = more overconfidence = lower actual correctness
        
        # If agent predicted correct but peers disagreed, that's a mismatch
        # We reduce actual_correct by the disagreement severity
        # This effectively lowers the calibration accuracy for that confidence bin
        
        # For disagreement: if predicted_correct=True but peers disagreed,
        # then actual correctness should be lower (we were overconfident)
        if predicted_correct:
            # Disagreement means we were wrong to be confident
            # Reduce actual_correct by severity (e.g., 0.5 = half credit)
            # This penalizes overconfidence
            stats['actual_correct'] += (1.0 - disagreement_severity)
        else:
            # If we predicted incorrect, disagreement might actually mean we were right
            # But this is less clear - for now, treat as neutral
            # (Could be enhanced to track "disagreement when predicted wrong" separately)
            stats['actual_correct'] += 0.3  # Small credit for being cautious
        
        # Ensure actual_correct never goes negative (safety check)
        if stats['actual_correct'] < 0:
            stats['actual_correct'] = 0
        
        # Ensure actual_correct never exceeds count (safety check)
        if stats['actual_correct'] > stats['count']:
            stats['actual_correct'] = stats['count']
        
        # Save state after update
        self.save_state()
    
    def save_state(self):
        """Save calibration state to file"""
        try:
            # Ensure data directory exists
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert defaultdict to regular dict for JSON serialization
            state_data = {
                'bins': {k: dict(v) for k, v in self.bin_stats.items()}
            }
            
            with open(self.state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            # Don't fail silently, but don't crash either
            print(f"Warning: Failed to save calibration state: {e}", file=sys.stderr)
    
    def load_state(self):
        """Load calibration state from file"""
        try:
            if not self.state_file.exists():
                self.reset()
                return
            
            with open(self.state_file, 'r') as f:
                state_data = json.load(f)
            
            # Restore bin_stats
            self.bin_stats = defaultdict(lambda: {
                'count': 0,
                'predicted_correct': 0,
                'actual_correct': 0,
                'confidence_sum': 0.0
            })
            
            for bin_key, stats in state_data.get('bins', {}).items():
                self.bin_stats[bin_key] = stats
        except Exception as e:
            # If loading fails, reset to empty state
            print(f"Warning: Failed to load calibration state: {e}, resetting", file=sys.stderr)
            self.reset()


# Global calibration checker instance (lazy initialization to avoid blocking at import time)
_calibration_checker_instance = None

def get_calibration_checker() -> CalibrationChecker:
    """Get or create calibration checker instance (lazy initialization)"""
    global _calibration_checker_instance
    if _calibration_checker_instance is None:
        _calibration_checker_instance = CalibrationChecker()
    return _calibration_checker_instance

# Create a module-level proxy object that acts like the old calibration_checker
# This defers initialization until first use, preventing blocking at import time
class _CalibrationCheckerProxy:
    """Proxy for calibration_checker that provides lazy access"""
    def __getattr__(self, name):
        return getattr(get_calibration_checker(), name)
    
    def __call__(self, *args, **kwargs):
        # If someone tries to call calibration_checker() directly
        return get_calibration_checker()

calibration_checker = _CalibrationCheckerProxy()

