"""
Trajectory Identity Integration for UNITARES Governance.

Thin integration layer that:
1. Stores genesis signatures (Σ₀) at agent onboarding
2. Compares trajectory signatures on updates
3. Detects anomalies via trajectory deviation

Based on: "Trajectory Identity: A Mathematical Framework for Enactive AI Self-Hood"

This is a lightweight integration - trajectory data is optional and non-blocking.
Agents can operate without providing trajectory signatures; this is additive.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import json

from src.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class TrajectorySignature:
    """
    Minimal trajectory signature for governance integration.

    Full computation happens in anima-mcp; UNITARES receives and stores
    the computed signature for comparison and anomaly detection.
    """
    # Core components (as computed by anima-mcp trajectory.py)
    preferences: Dict[str, Any] = field(default_factory=dict)   # Π
    beliefs: Dict[str, Any] = field(default_factory=dict)       # B
    attractor: Optional[Dict[str, Any]] = None                  # A
    recovery: Dict[str, Any] = field(default_factory=dict)      # R
    relational: Dict[str, Any] = field(default_factory=dict)    # Δ

    # Metadata
    computed_at: Optional[str] = None
    observation_count: int = 0
    stability_score: float = 0.0
    identity_confidence: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrajectorySignature":
        """Create from dictionary (e.g., from MCP tool argument)."""
        return cls(
            preferences=data.get("preferences", {}),
            beliefs=data.get("beliefs", {}),
            attractor=data.get("attractor"),
            recovery=data.get("recovery", {}),
            relational=data.get("relational", {}),
            computed_at=data.get("computed_at"),
            observation_count=data.get("observation_count", 0),
            stability_score=data.get("stability_score", 0.0),
            identity_confidence=data.get("identity_confidence", 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "preferences": self.preferences,
            "beliefs": self.beliefs,
            "attractor": self.attractor,
            "recovery": self.recovery,
            "relational": self.relational,
            "computed_at": self.computed_at,
            "observation_count": self.observation_count,
            "stability_score": self.stability_score,
            "identity_confidence": self.identity_confidence,
        }

    def similarity(self, other: "TrajectorySignature") -> float:
        """
        Compute similarity to another signature.

        Simplified version - full computation is in anima-mcp.
        Returns weighted average of component similarities.
        """
        scores = []
        weights = []

        # Attractor center similarity (most important)
        if self.attractor and other.attractor:
            c1 = self.attractor.get("center", [])
            c2 = other.attractor.get("center", [])
            if c1 and c2 and len(c1) == len(c2):
                dist = sum((a - b)**2 for a, b in zip(c1, c2)) ** 0.5
                scores.append(2.71828 ** (-dist * 2))
                weights.append(0.4)

        # Belief values similarity
        if self.beliefs.get("values") and other.beliefs.get("values"):
            v1, v2 = self.beliefs["values"], other.beliefs["values"]
            if len(v1) == len(v2) and len(v1) > 0:
                sim = self._cosine_similarity(v1, v2)
                if sim is not None:
                    scores.append((sim + 1) / 2)
                    weights.append(0.3)

        # Recovery tau similarity
        t1 = self.recovery.get("tau_estimate")
        t2 = other.recovery.get("tau_estimate")
        if t1 and t2 and t1 > 0 and t2 > 0:
            import math
            log_ratio = abs(math.log(t1 / t2))
            scores.append(math.exp(-log_ratio))
            weights.append(0.2)

        # Stability score similarity (simple difference)
        if self.stability_score > 0 and other.stability_score > 0:
            scores.append(1 - abs(self.stability_score - other.stability_score))
            weights.append(0.1)

        if not scores:
            return 0.5  # No data to compare

        total_weight = sum(weights)
        return sum(s * w for s, w in zip(scores, weights)) / total_weight

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> Optional[float]:
        """Cosine similarity between vectors."""
        if len(v1) != len(v2) or len(v1) == 0:
            return None
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = sum(a * a for a in v1) ** 0.5
        norm2 = sum(b * b for b in v2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return None
        return dot / (norm1 * norm2)


async def store_genesis_signature(
    agent_id: str,
    signature: TrajectorySignature,
) -> bool:
    """
    Store genesis signature (Σ₀) for an agent.

    Called at onboarding or first trajectory submission.
    Genesis is immutable - once set, cannot be changed.

    Returns True if stored, False if already exists.
    """
    try:
        from src.db import get_db
        db = get_db()

        # Get current metadata
        identity = await db.get_identity(agent_id)
        if not identity:
            logger.warning(f"[Trajectory] Agent {agent_id[:8]}... not found")
            return False

        metadata = identity.metadata or {}

        # Check if genesis already exists (immutable)
        if metadata.get("trajectory_genesis"):
            logger.debug(f"[Trajectory] Genesis already exists for {agent_id[:8]}...")
            return False

        # Store genesis signature
        metadata["trajectory_genesis"] = signature.to_dict()
        metadata["trajectory_genesis_at"] = datetime.utcnow().isoformat()

        await db.update_identity_metadata(agent_id, metadata)
        logger.info(f"[Trajectory] Stored genesis Σ₀ for {agent_id[:8]}... (confidence={signature.identity_confidence:.2f})")
        return True

    except Exception as e:
        logger.error(f"[Trajectory] Failed to store genesis: {e}")
        return False


async def update_current_signature(
    agent_id: str,
    signature: TrajectorySignature,
) -> Dict[str, Any]:
    """
    Update current trajectory signature and check for anomalies.

    Returns comparison results including:
    - similarity to genesis (lineage check)
    - is_anomaly flag
    - recommendations
    """
    try:
        from src.db import get_db
        db = get_db()

        identity = await db.get_identity(agent_id)
        if not identity:
            return {"error": "Agent not found"}

        metadata = identity.metadata or {}

        # Store current signature
        metadata["trajectory_current"] = signature.to_dict()
        metadata["trajectory_updated_at"] = datetime.utcnow().isoformat()

        result = {
            "stored": True,
            "observation_count": signature.observation_count,
            "identity_confidence": signature.identity_confidence,
        }

        # Compare to genesis if exists
        genesis_data = metadata.get("trajectory_genesis")
        if genesis_data:
            genesis = TrajectorySignature.from_dict(genesis_data)
            lineage_sim = signature.similarity(genesis)

            result["lineage_similarity"] = round(lineage_sim, 4)
            result["lineage_threshold"] = 0.6
            result["is_anomaly"] = lineage_sim < 0.6

            if result["is_anomaly"]:
                result["warning"] = f"Trajectory drift detected: similarity to genesis is {lineage_sim:.2f} (threshold: 0.6)"
                logger.warning(f"[Trajectory] ANOMALY for {agent_id[:8]}...: lineage_sim={lineage_sim:.2f}")
        else:
            # No genesis - store this as genesis
            await store_genesis_signature(agent_id, signature)
            result["genesis_created"] = True

        # Compute and store trust tier before saving
        trust_tier = compute_trust_tier(metadata)
        metadata["trust_tier"] = trust_tier
        result["trust_tier"] = trust_tier

        # Save updated metadata
        await db.update_identity_metadata(agent_id, metadata)

        return result

    except Exception as e:
        logger.error(f"[Trajectory] Failed to update signature: {e}")
        return {"error": str(e)}


def compute_trust_tier(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute trust tier from trajectory metadata stored in identity.metadata.

    Pure function: takes metadata dict, returns tier assessment.
    No DB access, no side effects.

    Tiers:
        0 (unknown):     No trajectory data
        1 (emerging):    Has genesis, < 50 observations OR confidence < 0.5
        2 (established): 50+ observations, confidence >= 0.5, lineage > 0.7
        3 (verified):    200+ observations, confidence >= 0.7, lineage > 0.8
    """
    genesis = metadata.get("trajectory_genesis")
    current = metadata.get("trajectory_current")

    # Tier 0: No trajectory data at all
    if not genesis:
        return {
            "tier": 0,
            "name": "unknown",
            "observation_count": 0,
            "identity_confidence": 0.0,
            "lineage_similarity": None,
            "reason": "No trajectory data",
        }

    # Use current if available, otherwise genesis
    sig_data = current if current else genesis
    observation_count = sig_data.get("observation_count", 0)
    identity_confidence = sig_data.get("identity_confidence", 0.0)

    # Compute lineage similarity if both genesis and current exist
    lineage_similarity = None
    if genesis and current:
        try:
            g = TrajectorySignature.from_dict(genesis)
            c = TrajectorySignature.from_dict(current)
            lineage_similarity = round(c.similarity(g), 4)
        except Exception:
            pass

    # Tier 3: verified (200+ obs, confidence >= 0.7, lineage > 0.8)
    if (observation_count >= 200
            and identity_confidence >= 0.7
            and lineage_similarity is not None
            and lineage_similarity > 0.8):
        return {
            "tier": 3,
            "name": "verified",
            "observation_count": observation_count,
            "identity_confidence": round(identity_confidence, 4),
            "lineage_similarity": lineage_similarity,
            "reason": f"Strong behavioral continuity ({observation_count} obs, "
                      f"confidence={identity_confidence:.2f}, lineage={lineage_similarity:.2f})",
        }

    # Tier 2: established (50+ obs, confidence >= 0.5, lineage > 0.7)
    if (observation_count >= 50
            and identity_confidence >= 0.5
            and (lineage_similarity is None or lineage_similarity > 0.7)):
        return {
            "tier": 2,
            "name": "established",
            "observation_count": observation_count,
            "identity_confidence": round(identity_confidence, 4),
            "lineage_similarity": lineage_similarity,
            "reason": f"Stable identity ({observation_count} obs, "
                      f"confidence={identity_confidence:.2f})",
        }

    # Tier 1: emerging (has genesis but doesn't meet tier 2)
    return {
        "tier": 1,
        "name": "emerging",
        "observation_count": observation_count,
        "identity_confidence": round(identity_confidence, 4),
        "lineage_similarity": lineage_similarity,
        "reason": f"Building identity ({observation_count} obs, "
                  f"confidence={identity_confidence:.2f})",
    }


async def get_trajectory_status(agent_id: str) -> Dict[str, Any]:
    """Get trajectory identity status for an agent."""
    try:
        from src.db import get_db
        db = get_db()

        identity = await db.get_identity(agent_id)
        if not identity:
            return {"error": "Agent not found"}

        metadata = identity.metadata or {}

        genesis = metadata.get("trajectory_genesis")
        current = metadata.get("trajectory_current")

        result = {
            "has_genesis": genesis is not None,
            "has_current": current is not None,
            "genesis_at": metadata.get("trajectory_genesis_at"),
            "updated_at": metadata.get("trajectory_updated_at"),
        }

        if genesis:
            g = TrajectorySignature.from_dict(genesis)
            result["genesis_confidence"] = g.identity_confidence
            result["genesis_observations"] = g.observation_count

        if current:
            c = TrajectorySignature.from_dict(current)
            result["current_confidence"] = c.identity_confidence
            result["current_observations"] = c.observation_count

            if genesis:
                g = TrajectorySignature.from_dict(genesis)
                result["lineage_similarity"] = round(c.similarity(g), 4)
                result["is_drifting"] = result["lineage_similarity"] < 0.7

        return result

    except Exception as e:
        logger.error(f"[Trajectory] Failed to get status: {e}")
        return {"error": str(e)}


async def verify_trajectory_identity(
    agent_id: str,
    signature: TrajectorySignature,
    coherence_threshold: float = 0.7,
    lineage_threshold: float = 0.6,
) -> Dict[str, Any]:
    """
    Two-tier identity verification as per paper Section 6.1.2.

    Tier 1 (Coherence): Compare to recent signature
    Tier 2 (Lineage): Compare to genesis signature

    Returns verification result with both tiers.
    """
    try:
        from src.db import get_db
        db = get_db()

        identity = await db.get_identity(agent_id)
        if not identity:
            return {"verified": False, "error": "Agent not found"}

        metadata = identity.metadata or {}

        result = {
            "agent_id": agent_id[:8] + "...",
            "verified": True,
            "tiers": {},
        }

        # Tier 1: Coherence (compare to recent)
        current_data = metadata.get("trajectory_current")
        if current_data:
            current = TrajectorySignature.from_dict(current_data)
            coherence_sim = signature.similarity(current)
            tier1_passed = coherence_sim >= coherence_threshold
            result["tiers"]["coherence"] = {
                "similarity": round(coherence_sim, 4),
                "threshold": coherence_threshold,
                "passed": tier1_passed,
            }
            if not tier1_passed:
                result["verified"] = False
        else:
            result["tiers"]["coherence"] = {"skipped": True, "reason": "No current signature"}

        # Tier 2: Lineage (compare to genesis)
        genesis_data = metadata.get("trajectory_genesis")
        if genesis_data:
            genesis = TrajectorySignature.from_dict(genesis_data)
            lineage_sim = signature.similarity(genesis)
            tier2_passed = lineage_sim >= lineage_threshold
            result["tiers"]["lineage"] = {
                "similarity": round(lineage_sim, 4),
                "threshold": lineage_threshold,
                "passed": tier2_passed,
            }
            if not tier2_passed:
                result["verified"] = False
        else:
            result["tiers"]["lineage"] = {"skipped": True, "reason": "No genesis signature"}

        # Overall verdict
        if not result["verified"]:
            failed_tiers = [t for t, v in result["tiers"].items() if isinstance(v, dict) and not v.get("passed", True)]
            result["failed_tiers"] = failed_tiers
            result["warning"] = f"Identity verification failed: {', '.join(failed_tiers)}"

        return result

    except Exception as e:
        logger.error(f"[Trajectory] Verification failed: {e}")
        return {"verified": False, "error": str(e)}
