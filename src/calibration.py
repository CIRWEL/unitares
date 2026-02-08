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
import os
from datetime import datetime

from src.calibration_db import CalibrationDB


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


@dataclass
class ComplexityCalibrationBin:
    """Complexity calibration bin statistics"""
    bin_range: Tuple[float, float]  # (min, max) discrepancy
    count: int
    mean_discrepancy: float  # Mean absolute discrepancy in this bin
    mean_reported: float     # Mean reported complexity
    mean_derived: float      # Mean derived complexity
    high_discrepancy_rate: float  # Percentage with discrepancy > 0.3


class CalibrationChecker:
    """
    Checks calibration of confidence estimates.
    
    TWO-DIMENSIONAL CALIBRATION (per dialectic resolution 2025-12-10):
    
    1. TACTICAL CALIBRATION (per-decision):
       - Measures if individual decisions were correct at the time they were made
       - NO retroactive marking - decision correctness is fixed at decision time
       - Used for: sampling parameter adjustment (temperature, top_p)
       
    2. STRATEGIC CALIBRATION (trajectory health):
       - Measures if agents with high confidence end up in healthy states
       - Retroactive marking IS valid - trajectory outcomes matter
       - Used for: agent trust scoring, confidence estimates
    
    The "inverted curve" (high confidence = low accuracy) is VALID for strategic
    calibration - it reveals that overconfident agents have worse trajectories.
    But it was WRONG to use for tactical decisions.
    """
    
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

        # Backend: postgres (recommended), sqlite (legacy), json (fallback), auto
        self._backend = os.getenv("UNITARES_CALIBRATION_BACKEND", "sqlite").strip().lower()
        # Calibration DB path - used for SQLite fallback
        self._db_path = Path(
            os.getenv("UNITARES_CALIBRATION_DB_PATH", str(Path(__file__).parent.parent / "data" / "governance.db"))
        )
        # JSON snapshots disabled by default (DB is canonical). Set to "1" to enable for debugging.
        self._write_json_snapshot = os.getenv("UNITARES_CALIBRATION_WRITE_JSON_SNAPSHOT", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        self._db: CalibrationDB | None = None
        self._pg_db = None  # PostgreSQL backend (lazy init)

        # Resolve backend once (auto prefers postgres if DB_BACKEND=postgres, else sqlite)
        if self._backend not in ("json", "sqlite", "postgres"):
            # Auto: use postgres if main DB is postgres, else sqlite
            if os.getenv("DB_BACKEND", "").lower() == "postgres":
                self._backend = "postgres"
            else:
                self._backend = "sqlite" if self._db_path.exists() else "json"
        
        # Initialize complexity bins (always needed)
        self.complexity_bins = [
            (0.0, 0.1),   # Low discrepancy (well-calibrated)
            (0.1, 0.3),   # Medium discrepancy (moderate calibration)
            (0.3, 0.5),   # High discrepancy (poor calibration)
            (0.5, 1.0)    # Very high discrepancy (severe mis-calibration)
        ]
        
        # Load existing state or reset
        self.load_state()

    def _get_db(self) -> CalibrationDB:
        """Get SQLite backend (legacy)."""
        if self._db is None:
            self._db = CalibrationDB(self._db_path)
        return self._db

    def _get_pg_db(self):
        """Get PostgreSQL backend (lazy init)."""
        if self._pg_db is None:
            from src.db import get_db
            self._pg_db = get_db()
        return self._pg_db

    def _run_async(self, async_fn, *args, **kwargs):
        """Run async function from sync context. Always uses thread pool for safety."""
        import asyncio
        import concurrent.futures

        def run_in_new_loop():
            """Run async function in a fresh event loop (for thread execution)."""
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(async_fn(*args, **kwargs))
            finally:
                new_loop.close()

        # Always use thread pool - safer in mixed sync/async environments
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_in_new_loop)
            return future.result(timeout=10.0)
    
    def reset(self):
        """Reset calibration statistics"""
        # STRATEGIC calibration (trajectory health) - retroactive marking allowed
        # This is the ORIGINAL bin_stats - renamed conceptually to "strategic"
        self.bin_stats = defaultdict(lambda: {
            'count': 0,
            'predicted_correct': 0,
            'actual_correct': 0,  # This gets updated retroactively
            'confidence_sum': 0.0
        })
        
        # TACTICAL calibration (per-decision) - NO retroactive marking
        # Decision correctness is fixed at decision time
        self.tactical_bin_stats = defaultdict(lambda: {
            'count': 0,
            'predicted_correct': 0,
            'actual_correct': 0,  # Fixed at decision time, never updated retroactively
            'confidence_sum': 0.0
        })
        
        # Ensure complexity_bins is initialized (may already be set in __init__)
        if not hasattr(self, 'complexity_bins'):
            self.complexity_bins = [
                (0.0, 0.1),   # Low discrepancy (well-calibrated)
                (0.1, 0.3),   # Medium discrepancy (moderate calibration)
                (0.3, 0.5),   # High discrepancy (poor calibration)
                (0.5, 1.0)    # Very high discrepancy (severe mis-calibration)
            ]
        self.complexity_stats = defaultdict(lambda: {
            'count': 0,
            'discrepancy_sum': 0.0,
            'reported_sum': 0.0,
            'derived_sum': 0.0,
            'high_discrepancy_count': 0  # Count with discrepancy > 0.3
        })
    
    def record_prediction(
        self,
        confidence: float,
        predicted_correct: bool,
        actual_correct: Optional[float],
        complexity_discrepancy: Optional[float] = None
    ):
        """
        Record a prediction for calibration checking.
        
        This records to STRATEGIC calibration (trajectory health).
        For tactical calibration, use record_tactical_decision().
        
        Args:
            confidence: Confidence estimate (0-1)
            predicted_correct: Whether we predicted correct (based on confidence threshold)
            actual_correct: Whether prediction was actually correct (ground truth)
            complexity_discrepancy: Optional complexity-EISV discrepancy (0-1) for calibration weighting
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
        
        # Update actual correctness signal if provided.
        #
        # IMPORTANT: In UNITARES, "actual_correct" is allowed to be a *weighted* signal
        # (e.g. peer verification weight, or a trajectory-health proxy in [0,1]),
        # not only a strict boolean. This enables dynamic (non-manual) calibration.
        if actual_correct is not None:
            stats['actual_correct'] += float(actual_correct)
            # Auto-save after recording a prediction with any correctness signal
            self.save_state()
        
        # Record complexity discrepancy if provided
        if complexity_discrepancy is not None:
            self.record_complexity_discrepancy(abs(complexity_discrepancy))
    
    def record_tactical_decision(self, confidence: float, decision: str, 
                                  immediate_outcome: bool):
        """
        Record a decision for TACTICAL calibration (per-decision, no retroactive).
        
        This measures if individual decisions were correct AT THE TIME they were made.
        Unlike strategic calibration, this is NEVER updated retroactively.
        
        Args:
            confidence: Confidence estimate at decision time (0-1)
            decision: The decision made ("proceed", "pause", etc.)
            immediate_outcome: Whether the decision was correct based on immediate context
                              (not trajectory outcomes - that's strategic calibration)
        
        Example:
            - Decision "proceed" is tactically correct if agent could proceed without immediate issues
            - Decision "pause" is tactically correct if there was a genuine reason to pause
            - This is independent of whether the agent later has problems (that's strategic)
        """
        # Find which bin this confidence falls into
        bin_key = None
        for bin_min, bin_max in self.bins:
            if bin_min <= confidence < bin_max or (bin_max == 1.0 and confidence == 1.0):
                bin_key = f"{bin_min:.1f}-{bin_max:.1f}"
                break
        
        if bin_key is None:
            bin_key = f"{self.bins[-1][0]:.1f}-{self.bins[-1][1]:.1f}"
        
        # Initialize tactical_bin_stats if needed (backward compatibility)
        if not hasattr(self, 'tactical_bin_stats'):
            self.tactical_bin_stats = defaultdict(lambda: {
                'count': 0,
                'predicted_correct': 0,
                'actual_correct': 0,
                'confidence_sum': 0.0
            })
        
        stats = self.tactical_bin_stats[bin_key]
        stats['count'] += 1
        stats['confidence_sum'] += confidence
        
        # FIXED: predicted_correct is based on confidence, not decision
        # High confidence (>=0.5) = we predicted correct
        # Low confidence (<0.5) = we predicted incorrect
        # This measures calibration: "When I said I was X% confident, was I right?"
        predicted_correct = confidence >= 0.5
        if predicted_correct:
            stats['predicted_correct'] += 1
        
        # Tactical correctness is fixed at decision time - no retroactive updates!
        if immediate_outcome:
            stats['actual_correct'] += 1
        
        # Save state
        self.save_state()
    
    def record_complexity_discrepancy(self, discrepancy: float, reported_complexity: Optional[float] = None,
                                     derived_complexity: Optional[float] = None):
        """
        Record complexity-EISV discrepancy for calibration tracking.
        
        Args:
            discrepancy: Absolute discrepancy between reported and derived complexity (0-1)
            reported_complexity: Optional reported complexity value
            derived_complexity: Optional derived complexity value
        """
        # Find which complexity bin this discrepancy falls into
        bin_key = None
        for bin_min, bin_max in self.complexity_bins:
            if bin_min <= discrepancy < bin_max or (bin_max == 1.0 and discrepancy == 1.0):
                bin_key = f"{bin_min:.1f}-{bin_max:.1f}"
                break
        
        if bin_key is None:
            # Fallback to highest bin
            bin_key = f"{self.complexity_bins[-1][0]:.1f}-{self.complexity_bins[-1][1]:.1f}"
        
        stats = self.complexity_stats[bin_key]
        stats['count'] += 1
        stats['discrepancy_sum'] += discrepancy
        
        if reported_complexity is not None:
            stats['reported_sum'] += reported_complexity
        if derived_complexity is not None:
            stats['derived_sum'] += derived_complexity
        
        # Track high discrepancies (>0.3 threshold)
        if discrepancy > 0.3:
            stats['high_discrepancy_count'] += 1
    
    def get_complexity_calibration_weight(self, discrepancy: Optional[float]) -> float:
        """
        Get calibration weight based on complexity discrepancy.
        
        Lower discrepancy = higher weight (more reliable calibration signal)
        Higher discrepancy = lower weight (less reliable calibration signal)
        
        Args:
            discrepancy: Complexity-EISV discrepancy (0-1), or None if unavailable
        
        Returns:
            Weight factor (0.0-1.0) for confidence calibration updates
        """
        if discrepancy is None:
            return 1.0  # Default weight if no complexity data
        
        abs_discrepancy = abs(discrepancy)
        
        # Weight function: inverse relationship with discrepancy
        # Low discrepancy (<0.1) → high weight (1.0)
        # Medium discrepancy (0.1-0.3) → medium weight (0.7)
        # High discrepancy (>0.3) → low weight (0.4)
        if abs_discrepancy < 0.1:
            return 1.0
        elif abs_discrepancy < 0.3:
            # Linear interpolation: 0.1 → 1.0, 0.3 → 0.7
            return 1.0 - (abs_discrepancy - 0.1) * 1.5  # (0.3-0.1) * 1.5 = 0.3, so 1.0-0.3=0.7
        else:
            # High discrepancy: weight decreases further
            # 0.3 → 0.4, 0.5 → 0.2, 1.0 → 0.0
            if abs_discrepancy >= 1.0:
                return 0.0
            # Linear: 0.3 → 0.4, 1.0 → 0.0
            return max(0.0, 0.4 - (abs_discrepancy - 0.3) * (0.4 / 0.7))  # 0.4/0.7 ≈ 0.57
    
    def compute_complexity_calibration_metrics(self) -> Dict[str, ComplexityCalibrationBin]:
        """Compute complexity calibration metrics for each bin"""
        results = {}
        
        for bin_key, stats in self.complexity_stats.items():
            if stats['count'] == 0:
                continue
            
            # Parse bin range
            bin_min, bin_max = map(float, bin_key.split('-'))
            
            mean_discrepancy = stats['discrepancy_sum'] / stats['count']
            mean_reported = stats['reported_sum'] / stats['count'] if stats['reported_sum'] > 0 else None
            mean_derived = stats['derived_sum'] / stats['count'] if stats['derived_sum'] > 0 else None
            high_discrepancy_rate = stats['high_discrepancy_count'] / stats['count']
            
            results[bin_key] = ComplexityCalibrationBin(
                bin_range=(bin_min, bin_max),
                count=stats['count'],
                mean_discrepancy=mean_discrepancy,
                mean_reported=mean_reported or 0.0,
                mean_derived=mean_derived or 0.0,
                high_discrepancy_rate=high_discrepancy_rate
            )
        
        return results
    
    def compute_calibration_metrics(self) -> Dict[str, CalibrationBin]:
        """
        Compute STRATEGIC calibration metrics (trajectory health).
        
        This measures trajectory outcomes by confidence level.
        High confidence agents SHOULD end up in better states.
        If they don't, the inverted curve is a VALID signal of overconfidence.
        """
        results = {}
        
        for bin_key, stats in self.bin_stats.items():
            if stats['count'] == 0:
                continue
            
            # Parse bin range
            bin_min, bin_max = map(float, bin_key.split('-'))
            
            # Rename "accuracy" to "trajectory_health" conceptually
            # (keeping variable names for backward compatibility)
            accuracy = stats['actual_correct'] / stats['count']
            expected_accuracy = stats['confidence_sum'] / stats['count']
            calibration_error = abs(accuracy - expected_accuracy)
            
            results[bin_key] = CalibrationBin(
                bin_range=(bin_min, bin_max),
                count=stats['count'],
                predicted_correct=stats['predicted_correct'],
                actual_correct=stats['actual_correct'],
                accuracy=accuracy,  # This is really "trajectory_health"
                expected_accuracy=expected_accuracy,
                calibration_error=calibration_error
            )
        
        return results
    
    def compute_tactical_metrics(self) -> Dict[str, CalibrationBin]:
        """
        Compute TACTICAL calibration metrics (per-decision correctness).
        
        This measures if individual decisions were correct at the time.
        NO retroactive marking - this reflects decision quality, not trajectory.
        Use this for sampling parameter adjustment.
        """
        results = {}
        
        # Initialize tactical_bin_stats if needed (backward compatibility)
        if not hasattr(self, 'tactical_bin_stats'):
            return results  # No tactical data yet
        
        for bin_key, stats in self.tactical_bin_stats.items():
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
                accuracy=accuracy,  # This is real per-decision accuracy
                expected_accuracy=expected_accuracy,
                calibration_error=calibration_error
            )
        
        return results
    
    def check_calibration(self, min_samples_per_bin: int = 10, include_complexity: bool = True) -> Tuple[bool, Dict]:
        """
        Check if calibration is acceptable.
        
        Returns TWO-DIMENSIONAL calibration:
        - STRATEGIC (trajectory_health): Do confident agents end up healthy?
        - TACTICAL (per_decision): Are individual decisions correct at the time?
        
        Args:
            min_samples_per_bin: Minimum samples per bin to consider calibrated
            include_complexity: Whether to include complexity calibration metrics
        
        Returns:
            (is_calibrated, metrics_dict)
        """
        # STRATEGIC calibration (trajectory health)
        strategic_metrics = self.compute_calibration_metrics()
        
        # TACTICAL calibration (per-decision)
        tactical_metrics = self.compute_tactical_metrics()
        
        if not strategic_metrics and not tactical_metrics:
            return False, {"error": "No calibration data"}
        
        # Check strategic calibration
        issues = []
        strategic_issues = []
        for bin_key, bin_metrics in strategic_metrics.items():
            if bin_metrics.count < min_samples_per_bin:
                strategic_issues.append(f"Bin {bin_key}: insufficient samples ({bin_metrics.count} < {min_samples_per_bin})")
                continue
            
            # High confidence bins should have high trajectory health
            if bin_metrics.bin_range[0] >= 0.8:
                if bin_metrics.accuracy < 0.7:
                    strategic_issues.append(
                        f"Bin {bin_key}: high confidence ({bin_metrics.expected_accuracy:.2f}) "
                        f"but low trajectory health ({bin_metrics.accuracy:.2f})"
                    )
            
            # Large calibration error indicates miscalibration
            if bin_metrics.calibration_error > 0.2:
                strategic_issues.append(
                    f"Bin {bin_key}: large calibration error ({bin_metrics.calibration_error:.2f})"
                )
        
        # Check tactical calibration (if we have data)
        tactical_issues = []
        for bin_key, bin_metrics in tactical_metrics.items():
            if bin_metrics.count < min_samples_per_bin:
                continue
            
            # For tactical: high confidence should mean high per-decision accuracy
            if bin_metrics.bin_range[0] >= 0.8:
                if bin_metrics.accuracy < 0.7:
                    tactical_issues.append(
                        f"Bin {bin_key}: high confidence ({bin_metrics.expected_accuracy:.2f}) "
                        f"but low decision accuracy ({bin_metrics.accuracy:.2f})"
                    )
        
        is_calibrated = len(strategic_issues) == 0 and len(tactical_issues) == 0
        
        result = {
            "is_calibrated": is_calibrated,
            "issues": strategic_issues + tactical_issues,
            # STRATEGIC calibration (trajectory health) - formerly just "bins"
            "strategic_calibration": {
                "description": "Trajectory health by confidence level (retroactive marking)",
                "use_for": "Agent trust scoring, confidence estimates",
                "bins": {k: {
                    "count": v.count,
                    "trajectory_health": v.accuracy,  # Renamed from "accuracy"
                    "expected_confidence": v.expected_accuracy,
                    "calibration_error": v.calibration_error
                } for k, v in strategic_metrics.items()}
            },
            # Backward compatibility: keep "bins" key pointing to strategic
            "bins": {k: {
                "count": v.count,
                "accuracy": v.accuracy,  # Keep old name for backward compat
                "trajectory_health": v.accuracy,  # Also provide new name
                "expected_accuracy": v.expected_accuracy,
                "calibration_error": v.calibration_error
            } for k, v in strategic_metrics.items()}
        }
        
        # TACTICAL calibration (per-decision)
        if tactical_metrics:
            result["tactical_calibration"] = {
                "description": "Per-decision correctness (no retroactive marking)",
                "use_for": "Sampling parameter adjustment (temperature, top_p)",
                "bins": {k: {
                    "count": v.count,
                    "decision_accuracy": v.accuracy,
                    "expected_confidence": v.expected_accuracy,
                    "calibration_error": v.calibration_error
                } for k, v in tactical_metrics.items()}
            }
        else:
            result["tactical_calibration"] = {
                "description": "Per-decision correctness (no retroactive marking)",
                "use_for": "Sampling parameter adjustment (temperature, top_p)",
                "bins": {},
                "note": "No tactical data yet - call record_tactical_decision() to populate"
            }
        
        # Add complexity calibration if requested
        if include_complexity:
            complexity_metrics = self.compute_complexity_calibration_metrics()
            if complexity_metrics:
                result["complexity_calibration"] = {
                    k: {
                        "count": v.count,
                        "mean_discrepancy": v.mean_discrepancy,
                        "mean_reported": v.mean_reported,
                        "mean_derived": v.mean_derived,
                        "high_discrepancy_rate": v.high_discrepancy_rate
                    } for k, v in complexity_metrics.items()
                }
                
                # Add complexity calibration issues
                total_complexity_samples = sum(v.count for v in complexity_metrics.values())
                high_discrepancy_total = sum(
                    v.count * v.high_discrepancy_rate for v in complexity_metrics.values()
                )
                high_discrepancy_rate = high_discrepancy_total / total_complexity_samples if total_complexity_samples > 0 else 0
                
                if high_discrepancy_rate > 0.5:  # More than 50% high discrepancy
                    issues.append(
                        f"Complexity calibration: {high_discrepancy_rate:.1%} of samples show high discrepancy (>0.3)"
                    )
                    is_calibrated = False
        
        result["is_calibrated"] = is_calibrated
        result["issues"] = strategic_issues + tactical_issues
        
        # HONESTY NOTE: Surface what calibration actually measures
        result["honesty_note"] = (
            "IMPORTANT: 'Calibration' measures peer consensus (dialectic agreement), "
            "NOT actual external correctness. Strategic calibration asks 'did peer agree agent was healthy?' "
            "Tactical calibration asks 'did decision match peer-observable state?' "
            "Neither validates against task success, test results, or user satisfaction. "
            "The 0.7 peer_weight acknowledges this limitation."
        )
        
        return is_calibrated, result
    
    def update_ground_truth(self, confidence: float, predicted_correct: bool, 
                           actual_correct: bool, complexity_discrepancy: Optional[float] = None):
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
        """
        Deprecated: historical "pending ground truth" counter.
        
        The original implementation attempted to infer 'pending' from aggregate bin stats,
        but that is not well-defined once `actual_correct` is treated as a weighted
        correctness/trajectory-health signal (float), and it also failed to decrement
        when `actual_correct=False`.
        
        Dynamic calibration does not require a per-prediction pending queue, so this
        is kept for backward compatibility and always returns 0.
        """
        return 0
    
    def update_from_peer_verification(self, confidence: float, predicted_correct: bool, 
                                     peer_agreed: bool, weight: float = 0.7, 
                                     complexity_discrepancy: Optional[float] = None):
        """
        Update calibration from peer verification (dialectic convergence).
        
        Uses peer agreement weighted at 0.7 to account for overconfidence.
        The "elephant in the room": agents show 1.0 confidence but achieve ~0.7 accuracy.
        This weight calibrates for that reality - peer verification is valuable but not perfect.
        
        Complexity discrepancy further adjusts the weight: agents with high complexity-EISV
        divergence get lower weight (they're less reliable at self-assessment).
        
        Args:
            confidence: Original confidence estimate
            predicted_correct: Whether we predicted correct
            peer_agreed: Whether peer agents agreed (converged)
            weight: Weight for peer verification (default 0.7 = calibrates for overconfidence)
            complexity_discrepancy: Optional complexity-EISV discrepancy for calibration weighting
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
        
        # Apply complexity calibration weight if available
        complexity_weight = self.get_complexity_calibration_weight(complexity_discrepancy)
        effective_weight = weight * complexity_weight
        
        # Update actual correctness with weighted peer agreement
        # Weight accounts for overconfidence: agents show 1.0 confidence but achieve ~0.7 accuracy
        # This is the "elephant in the room" - high confidence doesn't mean perfect correctness
        # Complexity weight further adjusts: agents with high complexity discrepancy get lower weight
        if peer_agreed:
            # Weighted update: peer agreement counts as partial correctness (weight * complexity_weight)
            # This calibrates for the reality that agents are overconfident
            # AND accounts for complexity mis-assessment (lower weight if high discrepancy)
            stats['actual_correct'] += effective_weight
        
        # Record complexity discrepancy if provided
        if complexity_discrepancy is not None:
            self.record_complexity_discrepancy(abs(complexity_discrepancy))
        
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
            # Convert defaultdict to regular dict for JSON serialization
            state_data = {
                'bins': {k: dict(v) for k, v in self.bin_stats.items()},
                'complexity_bins': {k: dict(v) for k, v in self.complexity_stats.items()},
                # NEW: Tactical calibration (per-decision, no retroactive marking)
                'tactical_bins': {k: dict(v) for k, v in self.tactical_bin_stats.items()} if hasattr(self, 'tactical_bin_stats') else {}
            }

            now = datetime.now().isoformat()

            # PostgreSQL backend (recommended)
            if self._backend == "postgres":
                async def _save(data):
                    from src.db import get_db
                    db = get_db()
                    # Note: do NOT call db.close() here — this is the shared singleton pool.
                    # Closing it breaks all other concurrent users.
                    return await db.update_calibration(data)
                self._run_async(_save, state_data)
            # SQLite backend (legacy)
            elif self._backend == "sqlite":
                self._get_db().save_state(state_data, updated_at_iso=now)

            # Optional JSON snapshot for backward compatibility / transparency
            if self._write_json_snapshot:
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.state_file, 'w') as f:
                    json.dump(state_data, f, indent=2)
        except Exception as e:
            # Don't fail silently, but don't crash either
            print(f"Warning: Failed to save calibration state: {e}", file=sys.stderr)
    
    def load_state(self):
        """Load calibration state from file"""
        try:
            state_data = None

            # PostgreSQL backend (recommended)
            if self._backend == "postgres":
                try:
                    async def _load():
                        from src.db import get_db
                        db = get_db()
                        # Note: do NOT call db.close() — shared singleton pool
                        return await db.get_calibration()
                    result = self._run_async(_load)
                    if result and isinstance(result, dict):
                        # PostgreSQL returns calibration state directly (bins, tactical_bins, etc.)
                        # Filter out metadata fields that start with '_'
                        state_data = {k: v for k, v in result.items() if not k.startswith('_')}
                except Exception as e:
                    print(f"Warning: PostgreSQL calibration load failed: {e}, trying fallback", file=sys.stderr)
                    state_data = None

            # SQLite backend (legacy) - also used as fallback
            elif self._backend == "sqlite":
                # Auto-migrate JSON -> SQLite if sqlite enabled and db missing.
                if (not self._db_path.exists()) and self.state_file.exists():
                    try:
                        with open(self.state_file, "r") as f:
                            state_data = json.load(f)
                        # Save into sqlite as canonical state
                        self._get_db().save_state(state_data, updated_at_iso=datetime.now().isoformat())
                    except Exception:
                        state_data = None
                else:
                    try:
                        state_data = self._get_db().load_state()
                    except Exception:
                        state_data = None

            # Fallback to JSON file if db empty/unavailable
            if state_data is None:
                if not self.state_file.exists():
                    self.reset()
                    return
                with open(self.state_file, 'r') as f:
                    state_data = json.load(f)
            
            # Restore bin_stats (STRATEGIC calibration)
            self.bin_stats = defaultdict(lambda: {
                'count': 0,
                'predicted_correct': 0,
                'actual_correct': 0,
                'confidence_sum': 0.0
            })
            
            for bin_key, stats in state_data.get('bins', {}).items():
                self.bin_stats[bin_key] = stats
            
            # Restore complexity_stats (backward compatible - may not exist in old state files)
            self.complexity_stats = defaultdict(lambda: {
                'count': 0,
                'discrepancy_sum': 0.0,
                'reported_sum': 0.0,
                'derived_sum': 0.0,
                'high_discrepancy_count': 0
            })
            
            for bin_key, stats in state_data.get('complexity_bins', {}).items():
                self.complexity_stats[bin_key] = stats
            
            # Restore tactical_bin_stats (NEW - may not exist in old state files)
            self.tactical_bin_stats = defaultdict(lambda: {
                'count': 0,
                'predicted_correct': 0,
                'actual_correct': 0,
                'confidence_sum': 0.0
            })
            
            for bin_key, stats in state_data.get('tactical_bins', {}).items():
                self.tactical_bin_stats[bin_key] = stats
        except Exception as e:
            # If loading fails, reset to empty state
            print(f"Warning: Failed to load calibration state: {e}, resetting", file=sys.stderr)
            self.reset()

    def compute_correction_factors(self, min_samples: int = 5) -> Dict[str, float]:
        """
        Compute correction factors for each confidence bin based on historical accuracy.

        AUTO-CALIBRATION: If agents report 90% confidence but are only 70% accurate,
        the correction factor is 0.70/0.90 = 0.78. Multiply reported confidence by
        this factor to get calibrated confidence.

        Args:
            min_samples: Minimum samples in a bin to compute correction (default 5)

        Returns:
            Dict mapping bin_key to correction factor (1.0 = well-calibrated)
        """
        corrections = {}

        # Use tactical metrics (per-decision accuracy) for correction
        for bin_key, stats in self.tactical_bin_stats.items():
            if stats['count'] < min_samples:
                continue

            # Parse bin range for midpoint
            bin_min, bin_max = map(float, bin_key.split('-'))
            expected_accuracy = stats['confidence_sum'] / stats['count']  # Average confidence in bin
            actual_accuracy = stats['actual_correct'] / stats['count']

            if expected_accuracy > 0.01:  # Avoid division by near-zero
                # Correction factor: actual/expected
                # If expected 0.9 but actual 0.7, factor = 0.78
                # If expected 0.5 but actual 0.6, factor = 1.2 (underconfident)
                factor = actual_accuracy / expected_accuracy
                # Clip to reasonable range [0.5, 1.5] to avoid extreme corrections
                factor = max(0.5, min(1.5, factor))
                corrections[bin_key] = factor

        return corrections

    def apply_confidence_correction(self, reported_confidence: float,
                                    min_samples: int = 5) -> Tuple[float, Optional[str]]:
        """
        Apply calibration correction to a reported confidence value.

        AUTO-CALIBRATION LOOP: This closes the learning loop by automatically
        adjusting confidence based on historical accuracy.

        Args:
            reported_confidence: The confidence value reported by the agent [0, 1]
            min_samples: Minimum samples needed to apply correction

        Returns:
            Tuple of (corrected_confidence, correction_info)
            - corrected_confidence: Calibrated confidence value [0, 1]
            - correction_info: String describing correction applied, or None
        """
        # Clamp input to valid range
        reported_confidence = max(0.0, min(1.0, reported_confidence))

        # Find the bin for this confidence
        bin_key = None
        for bin_min, bin_max in self.bins:
            if bin_min <= reported_confidence < bin_max or (bin_max == 1.0 and reported_confidence == 1.0):
                bin_key = f"{bin_min:.1f}-{bin_max:.1f}"
                break

        if bin_key is None:
            return reported_confidence, None

        # Check if we have enough samples for this bin
        stats = self.tactical_bin_stats.get(bin_key)
        if not stats or stats['count'] < min_samples:
            return reported_confidence, None

        # Compute correction
        expected_accuracy = stats['confidence_sum'] / stats['count']
        actual_accuracy = stats['actual_correct'] / stats['count']

        if expected_accuracy < 0.01:
            return reported_confidence, None

        factor = actual_accuracy / expected_accuracy
        factor = max(0.5, min(1.5, factor))  # Clip to reasonable range

        corrected = reported_confidence * factor
        corrected = max(0.0, min(1.0, corrected))  # Clamp to [0, 1]

        # Only report if correction is significant (> 5%)
        if abs(factor - 1.0) > 0.05:
            info = f"calibration_adjusted: {reported_confidence:.2f} → {corrected:.2f} (factor={factor:.2f}, n={stats['count']})"
            return corrected, info

        return corrected, None


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

