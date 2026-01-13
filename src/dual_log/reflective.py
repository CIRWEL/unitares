"""
Reflective Log - What Agent Thinks Happened

Self-reported values from the agent. This is one half of the dual-log architecture.
The divergence between this and the operational log is the grounding signal.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ReflectiveEntry:
    """
    What agent thinks happened. Self-reported values.
    """
    timestamp: datetime
    agent_id: str
    
    # Direct from process_agent_update params
    self_complexity: Optional[float] = None
    self_confidence: Optional[float] = None
    task_type: Optional[str] = None
    
    # Knowledge graph activity (can be filled from KG queries)
    notes_count: int = 0
    insights_count: int = 0
    questions_count: int = 0
    
    def to_dict(self) -> dict:
        """Serialize for storage."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'agent_id': self.agent_id,
            'self_complexity': self.self_complexity,
            'self_confidence': self.self_confidence,
            'task_type': self.task_type,
            'notes_count': self.notes_count,
            'insights_count': self.insights_count,
            'questions_count': self.questions_count,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ReflectiveEntry':
        """Deserialize from storage."""
        data = data.copy()
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


def create_reflective_entry(
    agent_id: str,
    complexity: Optional[float] = None,
    confidence: Optional[float] = None,
    task_type: Optional[str] = None,
    notes_count: int = 0,
    insights_count: int = 0,
    questions_count: int = 0,
) -> ReflectiveEntry:
    """Factory function to create a reflective entry."""
    return ReflectiveEntry(
        timestamp=datetime.now(),
        agent_id=agent_id,
        self_complexity=complexity,
        self_confidence=confidence,
        task_type=task_type,
        notes_count=notes_count,
        insights_count=insights_count,
        questions_count=questions_count,
    )
