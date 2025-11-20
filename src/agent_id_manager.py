"""
Agent ID Management - Smart Identity Generation

Implements the two-layer architecture:
- Layer 1: Interface (HOW) - MCP Server, Bridge Script, Python Direct
- Layer 2: Identity (WHO) - Unique session/purpose-based agent IDs

Prevents state corruption from agent ID collisions.
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Set
import json


# Common generic agent IDs that should trigger warnings
COMMON_AGENT_IDS: Set[str] = {
    "claude_code_cli",
    "claude_chat",
    "test",
    "demo",
    "default_agent"
}


class AgentIDManager:
    """Manages agent ID generation with collision detection and session persistence"""
    
    def __init__(self, session_file: Optional[Path] = None):
        """
        Initialize Agent ID Manager
        
        Args:
            session_file: Path to session cache file (default: .governance_session)
        """
        if session_file is None:
            session_file = Path(".governance_session")
        self.session_file = Path(session_file)
    
    def get_agent_id(self, 
                    interactive: bool = True,
                    default_choice: str = "1") -> str:
        """
        Smart agent ID generation with override options
        
        Args:
            interactive: If True, prompt user for choices
            default_choice: Default choice if not interactive ("1", "2", or "3")
        
        Returns:
            Unique agent ID string
        """
        # Check for cached session ID
        if self.session_file.exists():
            cached_id = self.session_file.read_text().strip()
            if cached_id:
                if interactive:
                    use_cached = input(f"Resume session '{cached_id}'? [Y/n]: ").strip()
                    if use_cached.lower() != 'n':
                        return cached_id
                else:
                    # Non-interactive: use cached if available
                    return cached_id
        
        # Generate new agent ID
        if interactive:
            print("\n🎯 Agent ID Options:")
            print("1. Auto-generate session ID (recommended)")
            print("2. Purpose-based ID")
            print("3. Custom ID")
            choice = input(f"Select [1-3, default={default_choice}]: ").strip() or default_choice
        else:
            choice = default_choice
        
        if choice == "1":
            agent_id = self._generate_session_id()
        elif choice == "2":
            if interactive:
                purpose = input("Purpose (e.g., 'debugging', 'analysis'): ").strip()
            else:
                purpose = "exploration"
            if not purpose:
                purpose = "exploration"
            agent_id = self._generate_purpose_id(purpose)
        else:  # choice == "3"
            if interactive:
                agent_id = input("Custom agent_id: ").strip()
            else:
                agent_id = f"custom_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            agent_id = self._validate_custom_id(agent_id, interactive)
        
        # Save session
        self._save_session(agent_id)
        return agent_id
    
    def _generate_session_id(self) -> str:
        """Generate session-based agent ID with context"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        username = os.getenv('USER', os.getenv('USERNAME', 'user'))
        return f"claude_cli_{username}_{timestamp}"
    
    def _generate_purpose_id(self, purpose: str) -> str:
        """Generate purpose-based agent ID"""
        # Sanitize purpose (alphanumeric + underscore)
        purpose_clean = ''.join(c if c.isalnum() or c == '_' else '_' 
                                for c in purpose.lower())
        date = datetime.now().strftime('%Y%m%d')
        return f"claude_cli_{purpose_clean}_{date}"
    
    def _validate_custom_id(self, agent_id: str, interactive: bool) -> str:
        """Validate custom agent ID and warn about problematic patterns"""
        if not agent_id:
            raise ValueError("Agent ID cannot be empty")
        
        # Check if it's a common generic ID
        if agent_id.lower() in COMMON_AGENT_IDS:
            if interactive:
                print(f"⚠️  Warning: '{agent_id}' appears generic and may cause collisions.")
                print("Multiple sessions using this ID will share state (corruption risk).")
                confirm = input("Continue anyway? [y/N]: ").strip()
                if confirm.lower() != 'y':
                    raise ValueError(f"Agent ID '{agent_id}' rejected - too generic")
            else:
                # Non-interactive: append timestamp to make unique
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                agent_id = f"{agent_id}_{timestamp}"
                print(f"⚠️  Auto-appended timestamp to generic ID: {agent_id}")
        
        return agent_id
    
    def _save_session(self, agent_id: str) -> None:
        """Save agent ID to session file"""
        try:
            self.session_file.write_text(agent_id)
        except Exception as e:
            print(f"⚠️  Could not save session: {e}")
    
    def clear_session(self) -> None:
        """Clear cached session"""
        if self.session_file.exists():
            self.session_file.unlink()
    
    @staticmethod
    def check_active_agents(agent_id: str, metadata_file: Path) -> bool:
        """
        Check if agent ID is already active
        
        Args:
            agent_id: Agent ID to check
            metadata_file: Path to agent_metadata.json
        
        Returns:
            True if agent is active, False otherwise
        """
        if not metadata_file.exists():
            return False
        
        try:
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            
            if agent_id in metadata:
                agent_data = metadata[agent_id]
                status = agent_data.get('status', 'active')
                return status == 'active'
        except Exception:
            pass
        
        return False
    
    @staticmethod
    def warn_about_collision(agent_id: str, metadata_file: Path) -> bool:
        """
        Warn about agent ID collision and return True if should proceed
        
        Args:
            agent_id: Agent ID to check
            metadata_file: Path to agent_metadata.json
        
        Returns:
            True if should proceed, False if should abort
        """
        if AgentIDManager.check_active_agents(agent_id, metadata_file):
            print(f"\n🚨 WARNING: '{agent_id}' is already active!")
            print("This will mix states and cause corruption.")
            print("\nOptions:")
            print("1. Resume existing session (recommended)")
            print("2. Create new session with different ID")
            print("3. Force continue (NOT recommended)")
            
            choice = input("Select [1-3]: ").strip()
            if choice == "1":
                print(f"✅ Resuming session '{agent_id}'")
                return True
            elif choice == "2":
                print("Please restart with a different agent ID")
                return False
            else:  # choice == "3"
                print("⚠️  Proceeding with collision risk - state corruption possible!")
                confirm = input("Are you sure? [yes/N]: ").strip()
                return confirm.lower() == 'yes'
        
        return True


def get_agent_id(interactive: bool = True, 
                 default_choice: str = "1",
                 session_file: Optional[Path] = None) -> str:
    """
    Convenience function for getting agent ID
    
    Args:
        interactive: If True, prompt user for choices
        default_choice: Default choice if not interactive
        session_file: Optional custom session file path
    
    Returns:
        Unique agent ID string
    """
    manager = AgentIDManager(session_file=session_file)
    return manager.get_agent_id(interactive=interactive, default_choice=default_choice)

