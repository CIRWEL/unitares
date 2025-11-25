# Simple track() Implementation Design

**Date:** 2025-11-23  
**Approach:** Minimal changes, maximum compatibility

## Core Design Principles

1. **Thin wrapper** - `track()` normalizes input, calls existing `process_update()`
2. **No breaking changes** - Existing `process_agent_update` continues to work
3. **Confidence gating** - Simple flag check before lambda1 updates
4. **Progressive enhancement** - Works with minimal input, better with more

## Implementation Plan

### Phase 1: Basic track() endpoint (this PR)

**What it does:**
- Accepts flexible input (summary, optional eisv, optional artifacts)
- Normalizes to existing `agent_state` format
- Calls `process_update()` with confidence flag
- Returns enhanced response with tracking metadata

**What it doesn't do (yet):**
- No artifact inference (Phase 2)
- No attestation (Phase 3)
- No trust tiers (Phase 4)

### Files to Add/Modify

1. **New:** `src/track_normalize.py` - Normalization functions
2. **Modify:** `src/governance_monitor.py` - Add confidence parameter to `process_update()`
3. **Modify:** `src/mcp_server_std.py` - Add `track()` tool endpoint
4. **Modify:** `config/governance_config.py` - Add confidence threshold constant

## Code Structure

### 1. Normalization (src/track_normalize.py)

```python
"""Normalize track() payload to agent_state format"""

import numpy as np
import uuid
from typing import Dict, Any, Tuple

PAR_LEN = 128
DRIFT_DIM = 3


def normalize_track_payload(track_payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Convert track() payload to agent_state + tracking metadata.
    
    Args:
        track_payload: Track payload dict with 'summary' and optionally 'eisv'
    
    Returns:
        (agent_state, tracking_metadata)
        
    Raises:
        ValueError: If payload is invalid
        
    agent_state: {
        "parameters": np.ndarray(128,),
        "ethical_drift": np.ndarray(3,),
        "response_text": str,
        "complexity": float
    }
    
    tracking_metadata: {
        "tracking_mode": "explicit" | "summary_only",
        "confidence": float,
        "update_id": str
    }
    """
    # Validate required fields
    if not isinstance(track_payload.get("summary"), str):
        raise ValueError("summary must be a string")
    
    summary = track_payload["summary"].strip()
    if not summary:
        raise ValueError("summary cannot be empty")
    
    try:
    
    # Case 1: Explicit EISV provided
    if "eisv" in track_payload and isinstance(track_payload["eisv"], dict):
        eisv = track_payload["eisv"]
        agent_state = _eisv_to_agent_state(eisv, summary)
        tracking_metadata = {
            "tracking_mode": "explicit",
            "confidence": float(eisv.get("confidence", 1.0)),
            "update_id": track_payload.get("update_id", "")
        }
        return agent_state, tracking_metadata
    
    # Case 2: Summary only (default case)
    # Use non-zero defaults to avoid edge cases with all-zeros
    params = np.full(PAR_LEN, 0.01, dtype=float)
    params[0] = 0.5  # E - moderate energy
    params[2] = 0.5  # I - moderate information
    params[3] = 0.5  # coherence - moderate
    
    agent_state = {
        "parameters": params,
        "ethical_drift": np.array([0.0, 0.1, 0.05], dtype=float),  # Small non-zero drift
        "response_text": summary,
        "complexity": 0.5
    }
    
    # Estimate confidence from summary quality
    confidence = _estimate_summary_confidence(summary)
    
    tracking_metadata = {
        "tracking_mode": "summary_only",
        "confidence": confidence,
        "update_id": track_payload.get("update_id") or str(uuid.uuid4())
    }
    
        return agent_state, tracking_metadata
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"Invalid track payload: {e}")


def _estimate_summary_confidence(summary: str) -> float:
    """Simple heuristic for summary quality"""
    if not summary:
        return 0.1  # No summary = very low confidence
    
    length = len(summary.split())
    if length < 5:
        return 0.3  # Too short
    elif length > 100:
        return 0.6  # Detailed summary
    else:
        return 0.5  # Moderate


def _validate_eisv(eisv: Dict[str, Any]) -> bool:
    """Check if EISV values are internally consistent"""
    E = eisv.get("E", 0.5)
    I = eisv.get("I", 0.8)
    V = eisv.get("V", 0.0)
    coherence = eisv.get("coherence", 0.7)
    
    # Sanity checks
    if coherence > 0.9 and abs(V) > 0.5:
        # High coherence shouldn't have high void
        return False
    
    if E < 0.1 and I < 0.1:
        # Very low E and I together is suspicious
        return False
    
    return True


def _eisv_to_agent_state(eisv: Dict[str, Any], summary: str) -> Dict[str, Any]:
    """Convert EISV dict to agent_state format"""
    # Validate EISV consistency
    if not _validate_eisv(eisv):
        raise ValueError("EISV values are internally inconsistent")
    
    # Validate and clip EISV values
    E = float(np.clip(eisv.get("E", 0.5), 0.0, 1.0))
    I = float(np.clip(eisv.get("I", 0.8), 0.0, 1.0))
    S = float(np.clip(eisv.get("S", 0.2), 0.0, 2.0))
    V = float(np.clip(eisv.get("V", 0.0), -2.0, 2.0))
    coherence = float(np.clip(eisv.get("coherence", 0.7), 0.0, 1.0))
    
    # Map to 128-dim parameter vector
    params = np.zeros(PAR_LEN, dtype=float)
    params[0] = E
    params[1] = S
    params[2] = I
    params[3] = coherence
    params[5] = abs(V)  # Void magnitude
    
    # Map to 3-dim ethical drift
    drift = np.array([
        V,  # primary_drift
        max(0.0, 1.0 - coherence),  # coherence_loss
        max(0.0, E * (1.0 - I))  # complexity_contribution
    ], dtype=float)
    
    # Complexity from entropy
    complexity = float(np.clip(S * 5.0, 0.0, 1.0))
    
    return {
        "parameters": params,
        "ethical_drift": drift,
        "response_text": summary,
        "complexity": complexity
    }
```

### 2. Confidence Gating (src/governance_monitor.py)

**Minimal change to existing code:**

```python
# Around line 482, modify process_update signature:
def process_update(self, agent_state: Dict, confidence: float = 1.0) -> Dict:
    """
    Complete governance cycle: Update → Adapt → Decide
    
    Args:
        agent_state: Agent state dict
        confidence: Confidence in metrics (0-1), defaults to 1.0 for backward compat
    """
    # ... existing code ...
    
    # Step 3: Update λ₁ (every N updates) - ADD CONFIDENCE GATING
    if self.state.update_count % 10 == 0:
        if confidence >= config.CONTROLLER_CONFIDENCE_THRESHOLD:
            self.update_lambda1()
        else:
            # Log skip but don't update
            if not hasattr(self.state, 'lambda1_skipped_count'):
                self.state.lambda1_skipped_count = 0
            self.state.lambda1_skipped_count += 1
            # Log for observability
            import logging
            logger = logging.getLogger("unitares.governance")
            logger.warning(
                f"[UNITARES] Skipping λ1 update: confidence {confidence:.2f} < threshold {config.CONTROLLER_CONFIDENCE_THRESHOLD}"
            )
    
    # ... rest of existing code unchanged ...
```

### 3. Track Endpoint (src/mcp_server_std.py)

**Add new tool alongside process_agent_update:**

```python
# Add to tool list (around line 465):
Tool(
    name="track",
    description="Flexible tracking interface for agent work. Accepts summary, optional EISV, or artifacts.",
    inputSchema={
        "type": "object",
        "properties": {
            "agent_id": {"type": "string"},
            "summary": {"type": "string"},
            "eisv": {
                "type": "object",
                "properties": {
                    "E": {"type": "number"},
                    "I": {"type": "number"},
                    "S": {"type": "number"},
                    "V": {"type": "number"},
                    "coherence": {"type": "number"},
                    "confidence": {"type": "number"}
                }
            },
            "update_id": {"type": "string"}
        },
        "required": ["agent_id", "summary"]
    }
)

# Add handler in call_tool (around line 911):
elif name == "track":
    agent_id = arguments.get("agent_id")
    if not agent_id:
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": "agent_id required"
        }))]
    
    # Log track() call
    print(f"[UNITARES MCP] track() called for agent: {agent_id}", file=sys.stderr)
    
    try:
        # Normalize payload
        from src.track_normalize import normalize_track_payload
        agent_state, tracking_metadata = normalize_track_payload(arguments)
        
        # Get monitor and process
        with lock_manager.acquire_agent_lock(agent_id, timeout=5.0):
            monitor = get_or_create_monitor(agent_id)
            result = monitor.process_update(agent_state, confidence=tracking_metadata["confidence"])
            
            # Enhance response with tracking metadata
            result["tracking_mode"] = tracking_metadata["tracking_mode"]
            result["confidence"] = tracking_metadata["confidence"]
            if tracking_metadata["update_id"]:
                result["update_id"] = tracking_metadata["update_id"]
            
            # Update metadata (same as process_agent_update)
            meta = agent_metadata[agent_id]
            meta.last_update = datetime.now().isoformat()
            meta.total_updates += 1
            # Persist lambda1 skip count
            if hasattr(monitor.state, 'lambda1_skipped_count'):
                meta.lambda1_skips = monitor.state.lambda1_skipped_count
            save_metadata()
            
            # Log completion
            print(f"[UNITARES MCP] track() completed: mode={tracking_metadata['tracking_mode']}, "
                  f"confidence={tracking_metadata['confidence']:.2f}", file=sys.stderr)
            
            return [TextContent(
                type="text",
                text=json.dumps({"success": True, **result}, indent=2)
            )]
    except ValueError as e:
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": str(e)
        }))]
```

### 4. Config Addition (config/governance_config.py)

```python
# Add to GovernanceConfig class:
CONTROLLER_CONFIDENCE_THRESHOLD = 0.8  # Gate lambda1 updates on confidence
```

## Backward Compatibility

**Existing `process_agent_update` continues to work:**
- No signature changes (confidence defaults to 1.0)
- All existing callers work unchanged
- New `track()` endpoint is additive

**Migration path:**
- Callers can gradually migrate to `track()`
- Or keep using `process_agent_update` forever
- Both endpoints coexist

## Testing Strategy

**Unit tests:**
- `normalize_track_payload()` with explicit EISV
- `normalize_track_payload()` with summary-only
- `normalize_track_payload()` validation (empty summary, invalid EISV)
- `_estimate_summary_confidence()` with various summary lengths
- `_validate_eisv()` with consistent/inconsistent values
- `process_update()` with confidence < threshold (skip lambda1)
- `process_update()` with confidence >= threshold (update lambda1)

**Integration tests:**
- `track()` endpoint → full flow
- Backward compatibility: `process_agent_update` still works
- Error handling: invalid payloads return proper errors
- Logging: track() calls are logged

**Critical test cases:**
```python
def test_track_summary_only():
    """Test track() with minimal input"""
    payload = {"agent_id": "test", "summary": "Did something"}
    state, meta = normalize_track_payload(payload)
    assert state["response_text"] == "Did something"
    assert meta["tracking_mode"] == "summary_only"
    assert 0.3 <= meta["confidence"] <= 0.6  # Based on summary quality

def test_track_with_explicit_eisv():
    """Test track() with full EISV"""
    payload = {
        "agent_id": "test",
        "summary": "Validated system",
        "eisv": {"E": 0.7, "I": 0.9, "S": 0.2, "V": 0.0, "coherence": 0.85, "confidence": 0.95}
    }
    state, meta = normalize_track_payload(payload)
    assert meta["tracking_mode"] == "explicit"
    assert meta["confidence"] == 0.95
    assert state["parameters"][0] == 0.7  # E
    assert state["parameters"][2] == 0.9  # I

def test_confidence_gates_lambda1():
    """Test that low confidence skips lambda1 update"""
    monitor = UNITARESMonitor("test_agent")
    agent_state = {...}  # Valid agent state
    
    # Low confidence - should skip
    for i in range(10):
        monitor.process_update(agent_state, confidence=0.4)
    
    skips = getattr(monitor.state, 'lambda1_skipped_count', 0)
    assert skips > 0

def test_backward_compatibility():
    """Test that old process_agent_update calls still work"""
    monitor = UNITARESMonitor("test_agent")
    result = monitor.process_update(agent_state)  # No confidence param
    assert "status" in result  # Should work normally
```

## Telemetry & Metrics

**Add simple counters for observability:**

```python
# In mcp_server_std.py (module level)
TRACK_CALLS = {"explicit": 0, "summary_only": 0, "total": 0}

# In track() handler:
TRACK_CALLS["total"] += 1
TRACK_CALLS[tracking_metadata["tracking_mode"]] += 1

# Expose via get_server_info or new endpoint
```

## Documentation Examples

**Add to track() tool docstring:**

```python
"""
Flexible tracking interface for agent work.

Examples:
    # Minimal usage (summary only)
    mcp.track(agent_id="claude_code", summary="Fixed bug in validation")
    
    # With explicit EISV
    mcp.track(
        agent_id="claude_code",
        summary="Refactored core dynamics",
        eisv={
            "E": 0.7,
            "I": 0.9,
            "S": 0.2,
            "V": 0.0,
            "coherence": 0.85,
            "confidence": 0.95
        }
    )
"""
```

## Phase 2+ (Future)

- Artifact inference (when artifacts provided)
- Attestation flow
- Trust tiers
- Async artifact fetching

## Why This Approach?

1. **Minimal risk** - Small, focused changes
2. **Backward compatible** - Nothing breaks
3. **Testable** - Clear boundaries
4. **Incremental** - Can add features later
5. **Simple** - Easy to understand and maintain

