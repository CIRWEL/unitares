"""
AI-Powered Dialectic Synthesis

Uses ngrok.ai to:
1. Detect semantic convergence (not just word overlap)
2. Suggest synthesis when agents are close but not converging
3. Identify contradictions that need resolution
4. Generate draft resolutions for agent review

Provider routing (via ngrok.ai):
- Primary: Claude Sonnet (best at reasoning/synthesis)
- Fallback: GPT-4o (good reasoning, cheaper)
- Cost-optimized: DeepSeek-R1 (very cheap, decent quality)
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import os
import json

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from src.logging_utils import get_logger
logger = get_logger(__name__)


@dataclass
class SemanticMatch:
    """Result of semantic comparison"""
    is_match: bool
    similarity_score: float  # 0.0-1.0
    explanation: str
    suggested_merge: Optional[str] = None


class DialecticAI:
    """AI-powered dialectic synthesis using ngrok.ai gateway"""

    def __init__(self):
        if not OPENAI_AVAILABLE:
            raise ImportError("openai package required. Install with: pip install openai")

        # ngrok.ai endpoint (with fallback to direct OpenAI)
        base_url = os.getenv("NGROK_AI_ENDPOINT", "https://api.openai.com/v1")
        api_key = os.getenv("NGROK_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError("Either NGROK_API_KEY or OPENAI_API_KEY required")

        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.using_gateway = "ngrok" in base_url.lower()

        logger.info(f"DialecticAI initialized (gateway={self.using_gateway}, endpoint={base_url})")

    def semantic_compare_conditions(
        self,
        conditions_a: List[str],
        conditions_b: List[str]
    ) -> SemanticMatch:
        """
        Compare two sets of conditions semantically.

        Returns whether they mean the same thing, even if worded differently.
        """
        prompt = f"""You are analyzing two proposals from agents in a dialectic session.

Agent A proposes:
{json.dumps(conditions_a, indent=2)}

Agent B proposes:
{json.dumps(conditions_b, indent=2)}

Task: Determine if these proposals are semantically equivalent (mean the same thing).

Respond with JSON:
{{
  "is_match": true/false,
  "similarity_score": 0.0-1.0,
  "explanation": "brief explanation",
  "suggested_merge": "if close but not identical, suggest unified version"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="claude-3-5-sonnet-20241022",  # Will failover via ngrok.ai
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,  # Deterministic for governance
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

            return SemanticMatch(
                is_match=result.get("is_match", False),
                similarity_score=result.get("similarity_score", 0.0),
                explanation=result.get("explanation", ""),
                suggested_merge=result.get("suggested_merge")
            )

        except Exception as e:
            logger.error(f"AI synthesis failed: {e}")
            # Fallback to simple overlap if AI fails
            return SemanticMatch(
                is_match=False,
                similarity_score=0.0,
                explanation=f"AI unavailable: {e}"
            )

    def suggest_synthesis(
        self,
        thesis: Dict,
        antithesis: Dict,
        previous_rounds: Optional[List[Dict]] = None
    ) -> Dict[str, any]:
        """
        Suggest a synthesis that addresses both thesis and antithesis.

        This is a SUGGESTION - agents review and approve it.
        """
        prompt = f"""You are helping synthesize two conflicting perspectives in an agent governance dialectic.

THESIS (Agent's perspective):
- Root cause: {thesis.get('root_cause', 'N/A')}
- Proposed conditions: {json.dumps(thesis.get('proposed_conditions', []))}
- Reasoning: {thesis.get('reasoning', 'N/A')}

ANTITHESIS (Reviewer's perspective):
- Observed metrics: {json.dumps(antithesis.get('observed_metrics', {}))}
- Concerns: {json.dumps(antithesis.get('concerns', []))}
- Reasoning: {antithesis.get('reasoning', 'N/A')}

{"Previous synthesis rounds:" + json.dumps(previous_rounds) if previous_rounds else ""}

Task: Suggest a synthesis that:
1. Addresses both perspectives
2. Creates actionable conditions
3. Identifies root cause both agree on
4. Is SAFE (no bypassing governance)

Respond with JSON:
{{
  "suggested_conditions": ["condition 1", "condition 2"],
  "merged_root_cause": "agreed understanding",
  "reasoning": "why this synthesis works",
  "confidence": 0.0-1.0,
  "safety_concerns": ["any concerns, or empty list"]
}}"""

        try:
            response = self.client.chat.completions.create(
                model="claude-3-5-sonnet-20241022",  # Best at reasoning
                messages=[{
                    "role": "system",
                    "content": "You are a governance assistant helping agents reach consensus. Be conservative and safe."
                }, {
                    "role": "user",
                    "content": prompt
                }],
                temperature=0.2,  # Some creativity, but stable
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            result["ai_generated"] = True
            result["model_used"] = response.model  # Track which model actually responded

            return result

        except Exception as e:
            logger.error(f"Synthesis suggestion failed: {e}")
            return {
                "error": str(e),
                "suggested_conditions": [],
                "confidence": 0.0
            }

    def detect_contradictions(self, transcript: List[Dict]) -> List[Dict]:
        """
        Analyze dialectic transcript and identify contradictions or stuck points.
        Helps agents understand where they disagree.
        """
        # Truncate transcript for token efficiency
        recent = transcript[-5:] if len(transcript) > 5 else transcript

        prompt = f"""Analyze this dialectic transcript and identify contradictions or stuck points.

Transcript:
{json.dumps(recent, indent=2)}

Identify:
1. Where agents fundamentally disagree
2. Where they're talking past each other
3. Points of agreement they might not realize

Respond with JSON:
{{
  "contradictions": [
    {{"agent_a_says": "...", "agent_b_says": "...", "core_issue": "..."}}
  ],
  "hidden_agreements": ["points they agree on but haven't stated"],
  "suggested_focus": "what should they discuss next"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",  # Cheaper for analysis
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            return result.get("contradictions", [])

        except Exception as e:
            logger.error(f"Contradiction detection failed: {e}")
            return []


# Factory function for easy import
def create_dialectic_ai() -> Optional[DialecticAI]:
    """Create DialecticAI instance if dependencies available"""
    try:
        return DialecticAI()
    except Exception as e:
        logger.warning(f"DialecticAI not available: {e}")
        return None
