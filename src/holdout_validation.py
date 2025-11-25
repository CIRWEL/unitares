"""
Hold-out Validation Framework
Reserves some agents as blind test sets (never tune on them).
"""

from typing import Set, Dict, List
from pathlib import Path
import json


class HoldoutValidator:
    """Manages hold-out validation sets"""
    
    def __init__(self, config_file: Path = None):
        if config_file is None:
            project_root = Path(__file__).parent.parent
            config_file = project_root / "data" / "holdout_config.json"
        
        self.config_file = config_file
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_config()
    
    def _load_config(self):
        """Load hold-out configuration"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.holdout_agents = set(data.get('holdout_agents', []))
                    self.enabled = data.get('enabled', False)
            except Exception:
                self.holdout_agents = set()
                self.enabled = False
        else:
            self.holdout_agents = set()
            self.enabled = False
    
    def _save_config(self):
        """Save hold-out configuration"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump({
                    'holdout_agents': list(self.holdout_agents),
                    'enabled': self.enabled
                }, f, indent=2)
        except Exception as e:
            print(f"[HOLDOUT] Warning: Could not save config: {e}", file=sys.stderr)
    
    def is_holdout_agent(self, agent_id: str) -> bool:
        """Check if agent is in hold-out set"""
        return self.enabled and agent_id in self.holdout_agents
    
    def add_holdout_agent(self, agent_id: str):
        """Add agent to hold-out set"""
        self.holdout_agents.add(agent_id)
        self._save_config()
    
    def remove_holdout_agent(self, agent_id: str):
        """Remove agent from hold-out set"""
        self.holdout_agents.discard(agent_id)
        self._save_config()
    
    def enable(self):
        """Enable hold-out validation"""
        self.enabled = True
        self._save_config()
    
    def disable(self):
        """Disable hold-out validation"""
        self.enabled = False
        self._save_config()
    
    def get_holdout_stats(self) -> Dict:
        """Get statistics about hold-out sets"""
        return {
            "enabled": self.enabled,
            "holdout_agents_count": len(self.holdout_agents),
            "holdout_agents": list(self.holdout_agents)
        }


# Global hold-out validator instance
import sys
holdout_validator = HoldoutValidator()

