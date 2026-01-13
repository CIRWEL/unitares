"""
AI-Powered Agent Behavior Analysis

Analyzes agent metrics over time to detect patterns:
- Why does this agent keep hitting circuit breakers?
- Is this agent learning or stuck in a loop?
- Which agents collaborate well together?
- Anomaly detection: unusual behavior patterns

Provider routing (via ngrok.ai):
- Primary: GPT-4o (good at analysis, cheaper than GPT-4)
- Fallback: Claude (excellent reasoning)
- Cost-optimized: DeepSeek-R1 for batch analysis
"""

from typing import List, Dict, Optional, Tuple
import os
import json
from datetime import datetime, timedelta
from dataclasses import dataclass

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from src.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class BehaviorPattern:
    """Detected behavior pattern"""
    pattern_type: str  # "recurring_failure", "improvement", "anomaly", etc.
    description: str
    severity: str  # "info", "warning", "critical"
    evidence: List[str]  # Metrics or events supporting this
    recommendation: str
    confidence: float  # 0.0-1.0


class AgentBehaviorAnalyzer:
    """Analyze agent behavior patterns using AI"""

    def __init__(self):
        if not OPENAI_AVAILABLE:
            raise ImportError("openai package required")

        base_url = os.getenv("NGROK_AI_ENDPOINT", "https://api.openai.com/v1")
        api_key = os.getenv("NGROK_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError("API key required")

        self.client = OpenAI(base_url=base_url, api_key=api_key)
        logger.info("AgentBehaviorAnalyzer initialized")

    def analyze_agent_trajectory(
        self,
        agent_id: str,
        history: List[Dict]
    ) -> List[BehaviorPattern]:
        """
        Analyze agent's governance history and detect patterns.

        Args:
            agent_id: Agent identifier
            history: List of governance updates (timestamps + metrics)

        Returns:
            List of detected patterns
        """
        # Truncate to recent history (last 50 updates)
        recent = history[-50:] if len(history) > 50 else history

        prompt = f"""Analyze this agent's governance metrics over time.

Agent ID: {agent_id}
History (recent {len(recent)} updates):
{json.dumps(recent, indent=2)}

Look for:
1. **Recurring failures**: Same issues repeatedly
2. **Learning curves**: Improving or degrading metrics
3. **Anomalies**: Sudden metric changes
4. **Circuit breaker patterns**: What triggers them?
5. **Collaboration patterns**: How do dialectic sessions resolve?

Respond with JSON:
{{
  "patterns": [
    {{
      "pattern_type": "recurring_failure|improvement|anomaly|etc",
      "description": "what you observe",
      "severity": "info|warning|critical",
      "evidence": ["metric1 trend", "event2 pattern"],
      "recommendation": "actionable suggestion",
      "confidence": 0.0-1.0
    }}
  ],
  "overall_health": "improving|stable|degrading",
  "summary": "one-sentence overview"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",  # Good balance of cost/quality for analysis
                messages=[{
                    "role": "system",
                    "content": "You are an expert at analyzing agent behavior patterns in governance systems."
                }, {
                    "role": "user",
                    "content": prompt
                }],
                temperature=0.1,  # Low for consistent analysis
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            patterns = []

            for p in result.get("patterns", []):
                patterns.append(BehaviorPattern(
                    pattern_type=p.get("pattern_type", "unknown"),
                    description=p.get("description", ""),
                    severity=p.get("severity", "info"),
                    evidence=p.get("evidence", []),
                    recommendation=p.get("recommendation", ""),
                    confidence=p.get("confidence", 0.5)
                ))

            return patterns

        except Exception as e:
            logger.error(f"Behavior analysis failed: {e}")
            return []

    def compare_agents(
        self,
        agent_a_history: List[Dict],
        agent_b_history: List[Dict]
    ) -> Dict:
        """
        Compare two agents' behavior patterns.

        Useful for:
        - "Why does agent A succeed where agent B fails?"
        - "Are these agents compatible for dialectic sessions?"
        """
        prompt = f"""Compare these two agents' governance patterns.

Agent A (last 30 updates):
{json.dumps(agent_a_history[-30:], indent=2)}

Agent B (last 30 updates):
{json.dumps(agent_b_history[-30:], indent=2)}

Analyze:
1. Who has better governance metrics?
2. Different behavior patterns?
3. Would they work well together in dialectic?
4. What can each learn from the other?

Respond with JSON:
{{
  "performance_comparison": "A is more stable|B is improving faster|etc",
  "compatibility_score": 0.0-1.0,
  "complementary_strengths": ["A's strength", "B's strength"],
  "potential_conflicts": ["where they might clash"],
  "recommendation": "should they pair for dialectic?"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="claude-3-5-sonnet-20241022",  # Best at nuanced comparison
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                response_format={"type": "json_object"}
            )

            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"Agent comparison failed: {e}")
            return {"error": str(e)}

    def predict_circuit_breaker(
        self,
        current_metrics: Dict,
        recent_trend: List[Dict]
    ) -> Dict:
        """
        Predict if agent is heading toward circuit breaker.

        Early warning system: "You're trending toward high risk"
        """
        prompt = f"""Predict if this agent will trigger circuit breaker soon.

Current metrics:
{json.dumps(current_metrics, indent=2)}

Recent trend (last 10 updates):
{json.dumps(recent_trend[-10:], indent=2)}

Circuit breaker triggers at:
- risk_score ≥ 0.60
- coherence < 0.40
- void_active = true

Analyze:
1. Current trajectory
2. Rate of change
3. Leading indicators

Respond with JSON:
{{
  "will_trigger": true|false,
  "estimated_time": "hours until likely trigger, or null",
  "confidence": 0.0-1.0,
  "warning_signs": ["what to watch"],
  "preventive_actions": ["what agent should do now"]
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Cheap, fast for frequent checks
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,  # Deterministic for predictions
                response_format={"type": "json_object"}
            )

            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return {"will_trigger": False, "confidence": 0.0, "error": str(e)}


def create_behavior_analyzer() -> Optional[AgentBehaviorAnalyzer]:
    """Factory function"""
    try:
        return AgentBehaviorAnalyzer()
    except Exception as e:
        logger.warning(f"AgentBehaviorAnalyzer not available: {e}")
        return None
