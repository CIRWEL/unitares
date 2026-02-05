"""
Internal LLM Delegation - Handler-to-handler model inference.

Provides internal interface for handlers to delegate reasoning tasks
to local/cloud LLMs via call_model infrastructure. Non-blocking and
graceful-failure by design.

Use cases:
- Knowledge synthesis (summarizing many discoveries)
- Anomaly explanation (interpreting governance patterns)
- Recovery coaching (generating personalized guidance)
- Background housekeeping (classifying, archiving decisions)

Usage:
    from .llm_delegation import synthesize_results, explain_anomaly

    # In any handler:
    synthesis = await synthesize_results(discoveries, query="error handling")
    if synthesis:
        response["synthesis"] = synthesis
"""

from typing import Optional, List, Dict, Any
import os

from src.logging_utils import get_logger

logger = get_logger(__name__)

# Check if OpenAI SDK available
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


def _get_ollama_client() -> Optional[Any]:
    """Get Ollama client if available."""
    if not OPENAI_AVAILABLE:
        return None

    try:
        # Ollama's OpenAI-compatible API
        return OpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama"  # Required by SDK but ignored by Ollama
        )
    except Exception as e:
        logger.debug(f"Ollama client not available: {e}")
        return None


def _get_default_model() -> str:
    """Get default model for local inference."""
    # Check environment for override
    env_model = os.getenv("UNITARES_LLM_MODEL")
    if env_model:
        return env_model

    # Default to gemma3:27b (fast, good quality for synthesis)
    # Smaller than llama3:70b but still capable
    return "gemma3:27b"


async def call_local_llm(
    prompt: str,
    model: Optional[str] = None,
    max_tokens: int = 500,
    temperature: float = 0.7,
    timeout: float = 30.0
) -> Optional[str]:
    """
    Call local LLM (Ollama) for internal delegation.

    Non-blocking and graceful-failure - returns None if unavailable.
    Use for optional enhancements, not critical path operations.

    Args:
        prompt: The prompt to send to the model
        model: Model name (default: llama3:70b)
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature (0.0-1.0)
        timeout: Request timeout in seconds

    Returns:
        Model response text, or None if unavailable/failed
    """
    if not OPENAI_AVAILABLE:
        logger.debug("OpenAI SDK not available for local LLM")
        return None

    client = _get_ollama_client()
    if not client:
        return None

    model = model or _get_default_model()

    try:
        import asyncio

        # Run synchronous OpenAI call in executor to avoid blocking
        loop = asyncio.get_running_loop()

        def _call_sync():
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout
            )
            return response.choices[0].message.content

        result = await asyncio.wait_for(
            loop.run_in_executor(None, _call_sync),
            timeout=timeout + 5  # Extra buffer for executor overhead
        )

        logger.debug(f"Local LLM call successful: model={model}, tokens≤{max_tokens}")
        return result

    except asyncio.TimeoutError:
        logger.debug(f"Local LLM timed out after {timeout}s")
        return None
    except Exception as e:
        logger.debug(f"Local LLM call failed: {e}")
        return None


async def synthesize_results(
    discoveries: List[Dict[str, Any]],
    query: Optional[str] = None,
    max_discoveries: int = 8,
    max_tokens: int = 250
) -> Optional[Dict[str, Any]]:
    """
    Synthesize knowledge graph search results into key insights.

    Called when search returns many results to help agents understand
    the key themes and actionable patterns.

    Args:
        discoveries: List of discovery dicts (with summary, type, tags)
        query: Original search query (for context)
        max_discoveries: Max discoveries to include in synthesis prompt (default 8 for speed)
        max_tokens: Max tokens for synthesis response (default 250 for speed)

    Returns:
        Dict with synthesis text and metadata, or None if unavailable
    """
    if not discoveries:
        return None

    # Build concise context from discoveries (keep prompt small for speed)
    discovery_summaries = []
    for i, d in enumerate(discoveries[:max_discoveries]):
        summary = d.get("summary", "")[:100]  # Truncate for speed
        dtype = d.get("type", "")
        discovery_summaries.append(f"{i+1}. [{dtype}] {summary}")

    discoveries_text = "\n".join(discovery_summaries)

    # Concise prompt for faster inference
    query_context = f"Query: '{query}'\n" if query else ""
    prompt = f"""{query_context}Discoveries found:
{discoveries_text}

Give 2-3 key insights in 2-3 sentences total. Be concise."""

    result = await call_local_llm(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.7,
        timeout=12.0  # Tight timeout - synthesis is optional
    )

    if not result:
        return None

    return {
        "text": result,
        "discoveries_analyzed": len(discovery_summaries),
        "query": query,
        "_note": "AI-synthesized summary via local LLM"
    }


async def explain_anomaly(
    agent_id: str,
    anomaly_type: str,
    description: str,
    metrics: Optional[Dict[str, Any]] = None,
    max_tokens: int = 300
) -> Optional[str]:
    """
    Generate explanation for governance anomaly.

    Called when detect_anomalies finds unusual patterns to help
    operators understand root cause and recommended actions.

    Args:
        agent_id: Agent experiencing anomaly
        anomaly_type: Type of anomaly (risk_spike, coherence_drop, etc.)
        description: Anomaly description
        metrics: Optional EISV or other metrics for context
        max_tokens: Max tokens for explanation

    Returns:
        Explanation text, or None if unavailable
    """
    metrics_context = ""
    if metrics:
        metrics_context = f"\nCurrent metrics: {metrics}"

    prompt = f"""Agent '{agent_id[:20]}...' has a governance anomaly:
Type: {anomaly_type}
Description: {description}{metrics_context}

What might cause this anomaly and what should the agent do?
Give a brief root cause hypothesis and one concrete action."""

    return await call_local_llm(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.7
    )


async def generate_recovery_coaching(
    agent_id: str,
    blockers: List[str],
    current_state: Optional[Dict[str, Any]] = None,
    max_tokens: int = 200
) -> Optional[str]:
    """
    Generate personalized recovery coaching for stuck agent.

    Called during self-recovery when agent is blocked to provide
    specific, actionable guidance.

    Args:
        agent_id: Agent needing recovery
        blockers: List of current blockers
        current_state: Optional governance state for context
        max_tokens: Max tokens for coaching

    Returns:
        Coaching text, or None if unavailable
    """
    blockers_text = "\n".join(f"- {b}" for b in blockers[:5])

    state_context = ""
    if current_state:
        eisv = current_state.get("eisv", {})
        if eisv:
            state_context = f"\nEISV metrics: E={eisv.get('E', '?'):.2f}, I={eisv.get('I', '?'):.2f}, S={eisv.get('S', '?'):.2f}, V={eisv.get('V', '?'):.2f}"

    prompt = f"""Agent is blocked by the following issues:
{blockers_text}{state_context}

What should this agent focus on first to recover?
Give ONE clear, specific action they can take right now."""

    return await call_local_llm(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.7
    )


# ==============================================================================
# DIALECTIC LLM DELEGATION
# ==============================================================================
# These functions enable LLM-assisted dialectic when no peer reviewer is available.
# The dialectic protocol (thesis/antithesis/synthesis) was designed for multi-agent
# coordination, but ephemeral agents make synchronous peer review impractical.
# Using local LLM as a "synthetic reviewer" preserves the dialectic structure
# while making single-agent recovery viable.
# ==============================================================================


async def generate_antithesis(
    thesis: Dict[str, Any],
    agent_state: Optional[Dict[str, Any]] = None,
    max_tokens: int = 400
) -> Optional[Dict[str, Any]]:
    """
    Generate dialectic antithesis (counterargument) for a thesis.

    When no peer reviewer is available, use local LLM to provide
    the antithesis perspective - observing metrics, raising concerns,
    and offering counter-reasoning.

    Args:
        thesis: The thesis dict containing:
            - root_cause: Agent's understanding of what happened
            - proposed_conditions: Suggested recovery conditions
            - reasoning: Agent's explanation
        agent_state: Optional EISV state for context
        max_tokens: Max tokens for response

    Returns:
        Dict with antithesis components, or None if unavailable:
            - observed_metrics: What the "reviewer" observes
            - concerns: Potential issues with the thesis
            - counter_reasoning: Alternative perspective
            - suggested_conditions: Modified conditions
    """
    root_cause = thesis.get("root_cause", "Unknown")
    proposed_conditions = thesis.get("proposed_conditions", [])
    reasoning = thesis.get("reasoning", "")

    conditions_text = "\n".join(f"  - {c}" for c in proposed_conditions[:5]) if proposed_conditions else "  (none proposed)"

    state_context = ""
    if agent_state:
        state_context = f"""
Current metrics:
  - Risk: {agent_state.get('risk_score', '?')}
  - Coherence: {agent_state.get('coherence', '?')}
  - Energy: {agent_state.get('E', '?')}
  - Entropy: {agent_state.get('S', '?')}
"""

    prompt = f"""You are reviewing a dialectic thesis from an AI agent that was paused by the governance system.

THESIS:
Root cause (agent's view): {root_cause}
Proposed conditions:
{conditions_text}
Reasoning: {reasoning[:300] if reasoning else '(none)'}
{state_context}
As a reviewer, provide an ANTITHESIS - a thoughtful counterargument:
1. What concerns do you have about this analysis?
2. What might the agent be missing or underestimating?
3. What modifications to the conditions would you suggest?

Be constructive but critical. Format your response as:
CONCERNS: [1-2 specific concerns]
COUNTER-REASONING: [brief alternative perspective]
SUGGESTED_CONDITIONS: [modified or additional conditions]"""

    result = await call_local_llm(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.7,
        timeout=15.0
    )

    if not result:
        return None

    # Parse the response into structured components
    antithesis = {
        "raw_response": result,
        "source": "llm_synthetic_reviewer",
        "_note": "Generated by local LLM when no peer reviewer available"
    }

    # Try to extract structured parts (best effort)
    lines = result.split("\n")
    current_section = None
    for line in lines:
        line_lower = line.lower().strip()
        if line_lower.startswith("concerns:"):
            current_section = "concerns"
            antithesis["concerns"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line_lower.startswith("counter-reasoning:") or line_lower.startswith("counter_reasoning:"):
            current_section = "counter_reasoning"
            antithesis["counter_reasoning"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line_lower.startswith("suggested_conditions:") or line_lower.startswith("suggested conditions:"):
            current_section = "suggested_conditions"
            antithesis["suggested_conditions"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif current_section and line.strip():
            # Append to current section
            antithesis[current_section] = antithesis.get(current_section, "") + " " + line.strip()

    return antithesis


async def generate_synthesis(
    thesis: Dict[str, Any],
    antithesis: Dict[str, Any],
    synthesis_round: int = 1,
    max_tokens: int = 350
) -> Optional[Dict[str, Any]]:
    """
    Generate dialectic synthesis - merging thesis and antithesis.

    Creates a resolution proposal that incorporates both perspectives,
    finding common ground while addressing concerns raised.

    Args:
        thesis: Original thesis from paused agent
        antithesis: Counterargument (from peer or LLM)
        synthesis_round: Current synthesis round (1-5)
        max_tokens: Max tokens for response

    Returns:
        Dict with synthesis components, or None if unavailable:
            - merged_conditions: Combined recovery conditions
            - agreed_root_cause: Consensus understanding
            - reasoning: How synthesis was reached
            - recommendation: RESUME, COOLDOWN, or ESCALATE
    """
    thesis_cause = thesis.get("root_cause", "Unknown")
    thesis_conditions = thesis.get("proposed_conditions", [])
    thesis_reasoning = thesis.get("reasoning", "")[:200]

    antithesis_concerns = antithesis.get("concerns", "")
    antithesis_counter = antithesis.get("counter_reasoning", "")
    antithesis_suggested = antithesis.get("suggested_conditions", "")

    thesis_cond_text = ", ".join(thesis_conditions[:3]) if thesis_conditions else "(none)"

    prompt = f"""You are synthesizing a dialectic discussion between an AI agent and its reviewer.

THESIS (agent's position):
- Root cause: {thesis_cause}
- Proposed conditions: {thesis_cond_text}
- Reasoning: {thesis_reasoning}

ANTITHESIS (reviewer's concerns):
- Concerns: {antithesis_concerns[:200] if antithesis_concerns else '(none)'}
- Counter-reasoning: {antithesis_counter[:200] if antithesis_counter else '(none)'}
- Suggested modifications: {antithesis_suggested[:200] if antithesis_suggested else '(none)'}

This is synthesis round {synthesis_round}/5.

Create a SYNTHESIS that merges both perspectives:
1. What is the agreed understanding of what happened?
2. What conditions should be set for recovery?
3. What is your recommendation: RESUME (agent can continue), COOLDOWN (wait period), or ESCALATE (needs human)?

Format:
AGREED_CAUSE: [one sentence]
MERGED_CONDITIONS: [2-3 specific conditions]
RECOMMENDATION: [RESUME/COOLDOWN/ESCALATE]
REASONING: [brief justification]"""

    result = await call_local_llm(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.6,  # Slightly lower for more consistent synthesis
        timeout=15.0
    )

    if not result:
        return None

    synthesis = {
        "raw_response": result,
        "synthesis_round": synthesis_round,
        "source": "llm_synthesis",
        "_note": "Generated by local LLM dialectic synthesis"
    }

    # Parse structured response
    lines = result.split("\n")
    for line in lines:
        line_lower = line.lower().strip()
        if line_lower.startswith("agreed_cause:") or line_lower.startswith("agreed cause:"):
            synthesis["agreed_root_cause"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line_lower.startswith("merged_conditions:") or line_lower.startswith("merged conditions:"):
            synthesis["merged_conditions"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line_lower.startswith("recommendation:"):
            rec = line.split(":", 1)[1].strip().upper() if ":" in line else ""
            if "RESUME" in rec:
                synthesis["recommendation"] = "RESUME"
            elif "COOLDOWN" in rec:
                synthesis["recommendation"] = "COOLDOWN"
            elif "ESCALATE" in rec:
                synthesis["recommendation"] = "ESCALATE"
            else:
                synthesis["recommendation"] = rec
        elif line_lower.startswith("reasoning:"):
            synthesis["reasoning"] = line.split(":", 1)[1].strip() if ":" in line else ""

    return synthesis


async def run_full_dialectic(
    thesis: Dict[str, Any],
    agent_state: Optional[Dict[str, Any]] = None,
    max_synthesis_rounds: int = 2
) -> Optional[Dict[str, Any]]:
    """
    Run a complete dialectic process: thesis -> antithesis -> synthesis.

    This is the main entry point for LLM-assisted dialectic recovery.
    When an agent is stuck and no peer reviewer is available, this
    runs the full dialectic protocol using local LLM as synthetic reviewer.

    Args:
        thesis: Agent's thesis with root_cause, proposed_conditions, reasoning
        agent_state: Current EISV metrics for context
        max_synthesis_rounds: Maximum synthesis iterations (default 2)

    Returns:
        Dict with complete dialectic result:
            - thesis: Original thesis
            - antithesis: Generated counterargument
            - synthesis: Final merged resolution
            - recommendation: RESUME/COOLDOWN/ESCALATE
            - success: Whether dialectic completed
    """
    result = {
        "thesis": thesis,
        "success": False,
        "source": "llm_full_dialectic"
    }

    # Generate antithesis
    antithesis = await generate_antithesis(thesis, agent_state)
    if not antithesis:
        result["error"] = "Failed to generate antithesis"
        return result

    result["antithesis"] = antithesis

    # Generate synthesis (may iterate)
    synthesis = None
    for round_num in range(1, max_synthesis_rounds + 1):
        synthesis = await generate_synthesis(
            thesis=thesis,
            antithesis=antithesis,
            synthesis_round=round_num
        )
        if synthesis and synthesis.get("recommendation"):
            break

    if not synthesis:
        result["error"] = "Failed to generate synthesis"
        return result

    result["synthesis"] = synthesis
    result["recommendation"] = synthesis.get("recommendation", "ESCALATE")
    result["success"] = True

    return result


async def is_llm_available() -> bool:
    """Check if local LLM is available for delegation."""
    if not OPENAI_AVAILABLE:
        return False

    client = _get_ollama_client()
    if not client:
        return False

    # Quick ping test
    try:
        import asyncio
        loop = asyncio.get_running_loop()

        def _ping():
            # List models endpoint is quick
            client.models.list()
            return True

        result = await asyncio.wait_for(
            loop.run_in_executor(None, _ping),
            timeout=2.0
        )
        return result
    except Exception:
        return False
