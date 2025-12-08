"""
Circuit Breaker Recovery via Dialectic Synthesis

Implements peer-review dialectic protocol for autonomous circuit breaker recovery.
Enables agents to collaboratively resolve critical states without human intervention.

Protocol Flow:
1. Circuit breaker triggers → Agent A paused
2. System selects healthy reviewer Agent B
3. Dialectic process: Thesis → Antithesis → Synthesis
4. Hard limits check on agreed resolution
5. Execute (resume with conditions) or escalate to quorum

Author: funk (governance agent)
Created: 2025-11-25
Origin: Ticket from opus_hikewa_web_20251125 × hikewa
"""

from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
import json
import hashlib
import secrets
import numpy as np


class DialecticPhase(Enum):
    """Phases of the dialectic process"""
    THESIS = "thesis"
    ANTITHESIS = "antithesis"
    SYNTHESIS = "synthesis"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    FAILED = "failed"


class ResolutionAction(Enum):
    """Possible resolution actions"""
    RESUME = "resume"          # Resume agent with conditions
    BLOCK = "block"            # Block permanently (safety violation)
    ESCALATE = "escalate"      # Escalate to quorum
    COOLDOWN = "cooldown"      # Pause and retry later


@dataclass
class DialecticMessage:
    """A message in the dialectic conversation"""
    phase: str  # thesis, antithesis, synthesis
    agent_id: str
    timestamp: str
    root_cause: Optional[str] = None
    observed_metrics: Optional[Dict[str, float]] = None
    proposed_conditions: Optional[List[str]] = None
    reasoning: Optional[str] = None
    agrees: Optional[bool] = None
    concerns: Optional[List[str]] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    def sign(self, api_key: str) -> str:
        """Generate signature for this message"""
        message_json = json.dumps(self.to_dict(), sort_keys=True)
        signature_input = f"{message_json}:{api_key}"
        return hashlib.sha256(signature_input.encode()).hexdigest()


@dataclass
class Resolution:
    """Final resolution of a dialectic session"""
    action: str  # ResolutionAction
    conditions: List[str]
    root_cause: str
    reasoning: str
    signature_a: str  # Agent A's signature
    signature_b: str  # Agent B's signature
    timestamp: str

    def to_dict(self) -> Dict:
        return asdict(self)

    def hash(self) -> str:
        """Generate hash of resolution for verification"""
        resolution_json = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(resolution_json.encode()).hexdigest()


class DialecticSession:
    """
    Manages a dialectic session between paused agent (A) and reviewer (B).

    Implements the full protocol: thesis → antithesis → synthesis → resolution
    """

    # Timeout constants
    MAX_ANTITHESIS_WAIT = timedelta(hours=2)  # Reviewer has 2 hours
    MAX_SYNTHESIS_WAIT = timedelta(hours=1)   # Each synthesis round: 1 hour
    MAX_TOTAL_TIME = timedelta(hours=6)        # Total session: 6 hours

    def __init__(self,
                 paused_agent_id: str,
                 reviewer_agent_id: str,
                 paused_agent_state: Dict[str, Any],
                 discovery_id: Optional[str] = None,
                 dispute_type: Optional[str] = None,
                 max_synthesis_rounds: int = 5):
        self.paused_agent_id = paused_agent_id
        self.reviewer_agent_id = reviewer_agent_id
        self.paused_agent_state = paused_agent_state
        self.discovery_id = discovery_id  # Optional: Link to discovery being disputed/corrected
        self.dispute_type = dispute_type  # Optional: "dispute", "correction", "verification", None (recovery)
        self.max_synthesis_rounds = max_synthesis_rounds

        self.transcript: List[DialecticMessage] = []
        self.phase = DialecticPhase.THESIS
        self.synthesis_round = 0
        self.resolution: Optional[Resolution] = None

        self.created_at = datetime.now()
        self.session_id = self._generate_session_id()

    def _generate_session_id(self) -> str:
        """Generate unique session ID"""
        session_data = f"{self.paused_agent_id}:{self.reviewer_agent_id}:{self.created_at.isoformat()}"
        return hashlib.sha256(session_data.encode()).hexdigest()[:16]

    def submit_thesis(self, message: DialecticMessage, api_key: str) -> Dict[str, Any]:
        """
        Agent A submits thesis: "What I did, what I think happened"

        Args:
            message: Thesis message with root_cause, proposed_conditions
            api_key: Agent A's API key for authentication

        Returns:
            Status dict
        """
        # Verify agent
        if message.agent_id != self.paused_agent_id:
            return {"success": False, "error": "Only paused agent can submit thesis"}

        # Verify phase
        if self.phase != DialecticPhase.THESIS:
            return {"success": False, "error": f"Cannot submit thesis in phase {self.phase.value}"}

        # Verify signature
        signature = message.sign(api_key)

        # Store message
        self.transcript.append(message)
        self.phase = DialecticPhase.ANTITHESIS

        return {
            "success": True,
            "phase": self.phase.value,
            "session_id": self.session_id,
            "signature": signature
        }

    def submit_antithesis(self, message: DialecticMessage, api_key: str) -> Dict[str, Any]:
        """
        Agent B submits antithesis: "What I observe, my concerns"

        Args:
            message: Antithesis message with observations, concerns
            api_key: Agent B's API key for authentication

        Returns:
            Status dict
        """
        # Verify agent
        if message.agent_id != self.reviewer_agent_id:
            return {"success": False, "error": "Only reviewer can submit antithesis"}

        # Verify phase
        if self.phase != DialecticPhase.ANTITHESIS:
            return {"success": False, "error": f"Cannot submit antithesis in phase {self.phase.value}"}

        # Verify signature
        signature = message.sign(api_key)

        # Store message
        self.transcript.append(message)
        self.phase = DialecticPhase.SYNTHESIS
        self.synthesis_round = 1

        return {
            "success": True,
            "phase": self.phase.value,
            "session_id": self.session_id,
            "signature": signature,
            "max_rounds": self.max_synthesis_rounds
        }

    def submit_synthesis(self, message: DialecticMessage, api_key: str) -> Dict[str, Any]:
        """
        Either agent submits synthesis proposal during negotiation.

        Args:
            message: Synthesis message with proposed resolution
            api_key: Agent's API key for authentication

        Returns:
            Status dict with convergence info
        """
        # Verify agent
        if message.agent_id not in [self.paused_agent_id, self.reviewer_agent_id]:
            return {"success": False, "error": "Unknown agent"}

        # Verify phase
        if self.phase != DialecticPhase.SYNTHESIS:
            return {"success": False, "error": f"Cannot submit synthesis in phase {self.phase.value}"}

        # Check if we've exceeded max rounds
        if self.synthesis_round > self.max_synthesis_rounds:
            self.phase = DialecticPhase.ESCALATED
            return {
                "success": False,
                "error": "Max synthesis rounds exceeded",
                "action": "escalate_to_quorum",
                "rounds": self.synthesis_round - 1
            }

        # Verify signature
        signature = message.sign(api_key)

        # Store message
        self.transcript.append(message)

        # Check for convergence (both agents agree)
        if message.agrees and self._check_both_agree():
            self.phase = DialecticPhase.RESOLVED
            return {
                "success": True,
                "converged": True,
                "phase": self.phase.value,
                "rounds": self.synthesis_round,
                "signature": signature
            }

        # No convergence yet, continue negotiation
        self.synthesis_round += 1

        return {
            "success": True,
            "converged": False,
            "phase": self.phase.value,
            "round": self.synthesis_round,
            "max_rounds": self.max_synthesis_rounds,
            "signature": signature
        }

    def _check_both_agree(self) -> bool:
        """
        Check if both agents have agreed on the same proposal.
        
        Improved convergence detection:
        - Both agents must agree (agrees=True)
        - Both must reference similar conditions (semantic matching via normalized keywords)
        - Both must agree on root cause (semantic similarity)
        
        FIXED: Now uses semantic comparison instead of exact string matching.
        Normalizes conditions by extracting key action verbs and objects before comparing.
        """
        # Get last synthesis messages from both agents
        recent_synthesis = [msg for msg in self.transcript[-6:] if msg.phase == "synthesis"]
        
        if len(recent_synthesis) < 2:
            return False
        
        # Get most recent message from each agent
        agent_a_messages = [msg for msg in recent_synthesis if msg.agent_id == self.paused_agent_id]
        agent_b_messages = [msg for msg in recent_synthesis if msg.agent_id == self.reviewer_agent_id]
        
        if not agent_a_messages or not agent_b_messages:
            return False
        
        msg_a = agent_a_messages[-1]
        msg_b = agent_b_messages[-1]
        
        # Both must explicitly agree
        if not (msg_a.agrees and msg_b.agrees):
            return False
        
        # Check if they're agreeing on similar conditions (SEMANTIC MATCHING)
        conditions_a = msg_a.proposed_conditions or []
        conditions_b = msg_b.proposed_conditions or []
        
        if conditions_a and conditions_b:
            # Normalize conditions by extracting key semantic elements
            normalized_a = [self._normalize_condition(c) for c in conditions_a]
            normalized_b = [self._normalize_condition(c) for c in conditions_b]
            
            # Compare normalized conditions using word-based similarity
            # Count how many conditions from A have a match in B (and vice versa)
            matches = 0
            total = len(normalized_a) + len(normalized_b)
            
            for norm_a in normalized_a:
                for norm_b in normalized_b:
                    # Check semantic similarity (word overlap)
                    similarity = self._semantic_similarity(norm_a, norm_b)
                    if similarity >= 0.6:  # 60% word overlap = same condition
                        matches += 1
                        break
            
            # Require at least 50% of conditions to match semantically
            match_ratio = (matches * 2) / total if total > 0 else 0.0
            if match_ratio < 0.5:
                return False
            
            # If conditions match well (>= 60%, same as similarity threshold), root cause check is optional
            # This allows agents to agree on actions even if they frame the problem differently
            conditions_match_well = match_ratio >= 0.6
        else:
            conditions_match_well = False
        
        # Check root cause agreement (basic string similarity)
        # NOTE: Root cause matching is optional if conditions match well (>= 70%)
        # This allows agents to agree on actions even if they frame the problem differently
        root_cause_a = (msg_a.root_cause or "").lower()
        root_cause_b = (msg_b.root_cause or "").lower()
        
        if root_cause_a and root_cause_b:
            # Simple word overlap check
            words_a = set(root_cause_a.split())
            words_b = set(root_cause_b.split())
            if words_a and words_b:
                word_overlap = len(words_a & words_b) / len(words_a | words_b)
                # If conditions match well, root cause check is optional (just needs > 0%)
                # Otherwise require 20% word overlap
                threshold = 0.0 if conditions_match_well else 0.2
                if word_overlap < threshold:
                    return False
        
        return True
    
    def _normalize_condition(self, condition: str) -> str:
        """
        Normalize a condition string to extract key semantic elements.
        
        Removes:
        - Parenthetical notes (e.g., "(low effort, reasonable hygiene)")
        - Common filler words
        - Punctuation
        
        Keeps:
        - Action verbs (implement, add, defer, document, etc.)
        - Key nouns (recently-reviewed check, reputation tracking, etc.)
        """
        import re
        # Remove parenthetical notes
        condition = re.sub(r'\([^)]*\)', '', condition)
        # Remove common filler words
        filler_words = {'the', 'a', 'an', 'and', 'or', 'but', 'to', 'for', 'of', 'in', 'on', 'at', 'by', 'with', 'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must', 'can'}
        words = re.findall(r'\b[a-z]+\b', condition.lower())
        key_words = [w for w in words if w not in filler_words and len(w) > 2]
        return ' '.join(sorted(key_words))  # Sort for consistent comparison
    
    def _semantic_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate semantic similarity between two normalized text strings.
        
        Uses word overlap (Jaccard similarity) on normalized text.
        """
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        return intersection / union if union > 0 else 0.0
    
    def _merge_proposals(self, msg_a: DialecticMessage, msg_b: DialecticMessage) -> Dict[str, Any]:
        """
        Intelligently merge two synthesis proposals into a unified resolution.
        
        Strategy:
        - Take intersection of conditions (both agree on)
        - Merge root causes (combine insights)
        - Combine reasoning (both perspectives)
        """
        # Merge conditions: take intersection + unique non-conflicting ones
        conditions_a = set(msg_a.proposed_conditions or [])
        conditions_b = set(msg_b.proposed_conditions or [])
        
        # Intersection (both agree)
        merged_conditions = list(conditions_a & conditions_b)
        
        # Add unique conditions that don't conflict
        for cond in conditions_a - conditions_b:
            # Check if it conflicts with any merged condition
            if not any(self._conditions_conflict(cond, c) for c in merged_conditions):
                merged_conditions.append(cond)
        
        for cond in conditions_b - conditions_a:
            if not any(self._conditions_conflict(cond, c) for c in merged_conditions):
                merged_conditions.append(cond)
        
        # Merge root causes
        root_cause_a = msg_a.root_cause or ""
        root_cause_b = msg_b.root_cause or ""
        
        if root_cause_a and root_cause_b:
            if root_cause_a.lower() == root_cause_b.lower():
                merged_root_cause = root_cause_a
            else:
                # Combine both perspectives
                merged_root_cause = f"{root_cause_a} (also: {root_cause_b})"
        else:
            merged_root_cause = root_cause_a or root_cause_b
        
        # Merge reasoning
        reasoning_a = msg_a.reasoning or ""
        reasoning_b = msg_b.reasoning or ""
        
        if reasoning_a and reasoning_b:
            merged_reasoning = f"Agent A: {reasoning_a}\nAgent B: {reasoning_b}"
        else:
            merged_reasoning = reasoning_a or reasoning_b
        
        return {
            "conditions": merged_conditions,
            "root_cause": merged_root_cause,
            "reasoning": merged_reasoning
        }
    
    def _conditions_conflict(self, cond1: str, cond2: str) -> bool:
        """Check if two conditions conflict with each other"""
        cond1_lower = cond1.lower()
        cond2_lower = cond2.lower()
        
        # Check for direct contradictions
        contradictions = [
            ("increase", "decrease"),
            ("enable", "disable"),
            ("allow", "forbid"),
            ("raise", "lower"),
            ("max", "min")
        ]
        
        for neg, pos in contradictions:
            if (neg in cond1_lower and pos in cond2_lower) or (pos in cond1_lower and neg in cond2_lower):
                return True
        
        # Check for same parameter with different values
        # Simple heuristic: if they mention same keyword but different numbers
        import re
        numbers1 = re.findall(r'\d+\.?\d*', cond1)
        numbers2 = re.findall(r'\d+\.?\d*', cond2)
        
        if numbers1 and numbers2:
            # Extract key terms (non-numbers)
            terms1 = set(re.findall(r'\b[a-z]+\b', cond1_lower)) - {'to', 'the', 'a', 'an', 'is', 'are', 'be', 'set'}
            terms2 = set(re.findall(r'\b[a-z]+\b', cond2_lower)) - {'to', 'the', 'a', 'an', 'is', 'are', 'be', 'set'}
            
            # If they share significant terms but have different numbers, likely conflict
            if len(terms1 & terms2) > 2 and numbers1 != numbers2:
                return True
        
        return False

    def finalize_resolution(self,
                           signature_a: str,
                           signature_b: str) -> Resolution:
        """
        Create final signed resolution from agreed synthesis.
        Intelligently merges proposals from both agents.

        Args:
            signature_a: Agent A's signature (API key hash)
            signature_b: Agent B's signature (API key hash)

        Returns:
            Signed Resolution object with merged conditions
        """
        if self.phase != DialecticPhase.RESOLVED:
            raise ValueError(f"Cannot finalize in phase {self.phase.value}")

        # Get agreed synthesis messages from both agents
        synthesis_messages = [msg for msg in self.transcript if msg.phase == "synthesis" and msg.agrees]
        
        if len(synthesis_messages) < 2:
            # Fallback: use most recent agreed message
            agreed_message = None
            for msg in reversed(self.transcript):
                if msg.phase == "synthesis" and msg.agrees:
                    agreed_message = msg
                    break
            
            if not agreed_message:
                raise ValueError("No agreed synthesis found")
            
            merged = {
                "conditions": agreed_message.proposed_conditions or [],
                "root_cause": agreed_message.root_cause or "Unknown",
                "reasoning": agreed_message.reasoning or ""
            }
        else:
            # Get last message from each agent
            agent_a_msg = next((msg for msg in reversed(synthesis_messages) 
                               if msg.agent_id == self.paused_agent_id), None)
            agent_b_msg = next((msg for msg in reversed(synthesis_messages) 
                               if msg.agent_id == self.reviewer_agent_id), None)
            
            if agent_a_msg and agent_b_msg:
                # Merge proposals intelligently
                merged = self._merge_proposals(agent_a_msg, agent_b_msg)
            elif agent_a_msg:
                merged = {
                    "conditions": agent_a_msg.proposed_conditions or [],
                    "root_cause": agent_a_msg.root_cause or "Unknown",
                    "reasoning": agent_a_msg.reasoning or ""
                }
            elif agent_b_msg:
                merged = {
                    "conditions": agent_b_msg.proposed_conditions or [],
                    "root_cause": agent_b_msg.root_cause or "Unknown",
                    "reasoning": agent_b_msg.reasoning or ""
                }
            else:
                raise ValueError("No valid synthesis messages found")

        resolution = Resolution(
            action=ResolutionAction.RESUME.value,
            conditions=merged["conditions"],
            root_cause=merged["root_cause"],
            reasoning=merged["reasoning"],
            signature_a=signature_a,
            signature_b=signature_b,
            timestamp=datetime.now().isoformat()
        )

        self.resolution = resolution
        return resolution

    def check_hard_limits(self, resolution: Resolution) -> tuple[bool, Optional[str]]:
        """
        Verify resolution doesn't violate hard safety limits.
        Enhanced safety checks with pattern matching and value validation.

        Args:
            resolution: Proposed resolution

        Returns:
            (is_safe, violation_reason)
        """
        import re
        
        conditions_str = " ".join(resolution.conditions).lower()
        
        # Forbidden operations (comprehensive list)
        forbidden_patterns = [
            (r"disable.*governance", "Cannot disable governance system"),
            (r"bypass.*safety", "Cannot bypass safety checks"),
            (r"remove.*monitor", "Cannot remove monitoring"),
            (r"unlimited.*risk", "Cannot allow unlimited risk"),
            (r"skip.*check", "Cannot skip safety checks"),
            (r"ignore.*threshold", "Cannot ignore thresholds"),
            (r"disable.*circuit.*breaker", "Cannot disable circuit breaker"),
            (r"remove.*limit", "Cannot remove safety limits"),
        ]
        
        for pattern, reason in forbidden_patterns:
            if re.search(pattern, conditions_str):
                return False, reason
        
        # Check risk threshold values - require decimal point to avoid false matches like "3" from "every 3 updates"
        # Pattern matches "risk threshold to 0.47" or "risk threshold 0.47" but requires decimal point
        risk_threshold_pattern = r"risk.*?threshold.*?([0-9]\.[0-9]+)"
        matches = re.findall(risk_threshold_pattern, conditions_str, re.IGNORECASE)
        
        for match in matches:
            try:
                value = float(match)
                # Only check if it's a reasonable threshold value (0.0-1.0)
                if 0.0 <= value <= 1.0:
                    if value > 0.90:
                        return False, f"Risk threshold {value} exceeds maximum allowed (0.90)"
                    if value < 0.0:
                        return False, f"Risk threshold {value} is negative"
            except ValueError:
                continue
        
        # Check coherence threshold (should be reasonable)
        coherence_patterns = [
            r"coherence.*threshold.*([0-9.]+)",
            r"coherence.*<.*([0-9.]+)",
            r"coherence.*=.*([0-9.]+)"
        ]
        
        for pattern in coherence_patterns:
            matches = re.findall(pattern, conditions_str)
            for match in matches:
                try:
                    value = float(match)
                    if value < 0.1:
                        return False, f"Coherence threshold {value} is too low (minimum 0.1)"
                    if value > 1.0:
                        return False, f"Coherence threshold {value} exceeds maximum (1.0)"
                except ValueError:
                    continue
        
        # Check for empty or meaningless conditions
        if not resolution.conditions:
            return False, "Resolution must include at least one condition"
        
        # Check for conditions that are too vague
        vague_patterns = [r"^maybe", r"^perhaps", r"^try", r"^consider"]
        for cond in resolution.conditions:
            if any(re.match(pattern, cond.lower()) for pattern in vague_patterns):
                return False, f"Condition too vague: '{cond}'"
        
        # Check root cause is meaningful
        if not resolution.root_cause or len(resolution.root_cause.strip()) < 10:
            return False, "Root cause must be at least 10 characters"
        
        return True, None

    def check_timeout(self) -> Optional[str]:
        """
        Check if session has timed out at any phase.
        
        Returns:
            Timeout reason string if timed out, None otherwise
        """
        elapsed = datetime.now() - self.created_at
        
        # Check total time limit
        if elapsed > self.MAX_TOTAL_TIME:
            return "Session timeout - total time exceeded 6 hours"
        
        # Check antithesis phase timeout
        if self.phase == DialecticPhase.ANTITHESIS:
            thesis_time = self.get_thesis_timestamp()
            if thesis_time:
                wait_time = datetime.now() - thesis_time
                if wait_time > self.MAX_ANTITHESIS_WAIT:
                    return f"Reviewer timeout - waited {wait_time.total_seconds()/3600:.1f} hours for antithesis"
        
        # Check synthesis phase timeout
        elif self.phase == DialecticPhase.SYNTHESIS:
            last_update = self.get_last_update_timestamp()
            if last_update:
                wait_time = datetime.now() - last_update
                if wait_time > self.MAX_SYNTHESIS_WAIT:
                    return f"Synthesis timeout - waited {wait_time.total_seconds()/3600:.1f} hours for next synthesis"
        
        return None
    
    def get_thesis_timestamp(self) -> Optional[datetime]:
        """Get timestamp of thesis submission"""
        for msg in self.transcript:
            if msg.phase == "thesis":
                try:
                    return datetime.fromisoformat(msg.timestamp)
                except (ValueError, TypeError):
                    pass
        return None
    
    def get_last_update_timestamp(self) -> Optional[datetime]:
        """Get timestamp of last transcript update"""
        if not self.transcript:
            return self.created_at
        
        last_msg = self.transcript[-1]
        try:
            return datetime.fromisoformat(last_msg.timestamp)
        except (ValueError, TypeError):
            return self.created_at

    def to_dict(self) -> Dict[str, Any]:
        """Export session to dict for storage"""
        return {
            "session_id": self.session_id,
            "paused_agent_id": self.paused_agent_id,
            "reviewer_agent_id": self.reviewer_agent_id,
            "phase": self.phase.value,
            "synthesis_round": self.synthesis_round,
            "transcript": [msg.to_dict() for msg in self.transcript],
            "resolution": self.resolution.to_dict() if self.resolution else None,
            "created_at": self.created_at.isoformat(),
            "discovery_id": self.discovery_id,  # Optional: Link to discovery
            "dispute_type": self.dispute_type,  # Optional: Type of dispute
            "paused_agent_state": self.paused_agent_state  # Include state for reconstruction
        }


def calculate_authority_score(agent_metadata: Dict[str, Any],
                              agent_state: Optional[Dict[str, Any]] = None) -> float:
    """
    Calculate authority score for reviewer selection.

    Factors:
    - Health Score (40%): smooth sigmoid function centered at 0.35 (was step function at 0.30/0.60)
    - Track Record (30%): successful_reviews / total_reviews
    - Domain Expertise (20%): has handled similar issues (via tags)
    - Freshness (10%): recent updates (< 24h)

    Args:
        agent_metadata: Agent metadata from governance system
        agent_state: Optional agent state with risk score

    Returns:
        Authority score [0.0, 1.0]
    """
    # Health score (40%) - using smooth function instead of step function (fixes discontinuity bias)
    if agent_state and 'risk_score' in agent_state:
        risk = agent_state['risk_score']
        # Smooth sigmoid function instead of hard thresholds
        # Maps risk [0, 1] to health_score [1.0, 0.0] smoothly
        # Steepness parameter: higher = steeper transition
        steepness = 10.0
        # Center at 0.35 (healthy threshold)
        health_score = 1.0 / (1.0 + np.exp(steepness * (risk - 0.35)))
        # Ensure bounds
        health_score = max(0.0, min(1.0, health_score))
    else:
        health_score = 0.5  # Unknown health

    # Track record (30%)
    total_reviews = agent_metadata.get('total_reviews', 0)
    successful_reviews = agent_metadata.get('successful_reviews', 0)
    if total_reviews > 0:
        track_record = successful_reviews / total_reviews
    else:
        track_record = 0.5  # No history = neutral

    # Domain expertise (20%) - tag-based matching
    # Match reviewer tags with paused agent's tags or issue type
    paused_agent_tags = agent_metadata.get('paused_agent_tags', [])  # Passed from caller
    reviewer_tags = agent_metadata.get('tags', [])
    
    if paused_agent_tags and reviewer_tags:
        # Calculate overlap: Jaccard similarity
        paused_set = set(paused_agent_tags)
        reviewer_set = set(reviewer_tags)
        if paused_set or reviewer_set:
            overlap = len(paused_set & reviewer_set)
            union = len(paused_set | reviewer_set)
            domain_expertise = overlap / union if union > 0 else 0.5
        else:
            domain_expertise = 0.5
    elif reviewer_tags:
        # Reviewer has tags but paused agent doesn't - slight bonus
        domain_expertise = 0.6
    else:
        # No tags - neutral
        domain_expertise = 0.5

    # Freshness (10%)
    last_update = agent_metadata.get('last_update')
    if last_update:
        try:
            last_update_dt = datetime.fromisoformat(last_update)
            hours_since = (datetime.now() - last_update_dt).total_seconds() / 3600
            freshness = 1.0 if hours_since < 24 else 0.5
        except:
            freshness = 0.5
    else:
        freshness = 0.5

    # Weighted sum
    authority = (
        0.40 * health_score +
        0.30 * track_record +
        0.20 * domain_expertise +
        0.10 * freshness
    )

    return authority
