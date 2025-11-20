"""
Claude Code → UNITARES Governance Bridge v1.0

Converts Claude Code telemetry into governance agent_state format.
Compatible with existing PRODUCTION_INTEGRATION_SUCCESS setup.
"""

import argparse
import sys
import json
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.mcp_server import GovernanceMCPServer
from src.agent_id_manager import AgentIDManager, get_agent_id
# Import metadata persistence functions from mcp_server_std
from src.mcp_server_std import (
    get_or_create_metadata,
    save_metadata,
    load_metadata,
    AgentMetadata
)


class ClaudeCodeBridge:
    """
    Bridge between Claude Code and UNITARES Governance
    
    Converts:
    - Response text → metrics (length, complexity, info density)
    - Metrics → agent_state format
    - Forward to Governance MCP
    - Log to CSV (backward compatible)
    
    Architecture:
    - Layer 1 (Interface): This bridge script (HOW)
    - Layer 2 (Identity): agent_id (WHO) - must be unique per session
    """
    
    def __init__(self, 
                 agent_id: Optional[str] = None,
                 data_dir: Optional[Path] = None,
                 interactive: bool = True):
        """
        Initialize Claude Code Bridge
        
        Args:
            agent_id: Optional agent ID (if None, will prompt/generate)
            data_dir: Optional data directory for CSV logging
            interactive: If True, prompt for agent ID choices
        """
        # Smart agent ID generation with collision detection
        if agent_id is None:
            project_root = Path(__file__).parent.parent
            metadata_file = project_root / "data" / "agent_metadata.json"
            
            # Generate smart agent ID
            agent_id = get_agent_id(interactive=interactive)
            
            # Check for collisions
            if not AgentIDManager.warn_about_collision(agent_id, metadata_file):
                raise ValueError("Agent ID collision detected - please use different ID")

        self.agent_id = agent_id
        self.server = GovernanceMCPServer()
        
        # Load existing metadata (if any)
        load_metadata()
        
        # Register agent in metadata system
        # get_or_create_metadata will create entry with lifecycle event if new
        self.metadata = get_or_create_metadata(agent_id)
        # Note: save_metadata() is called inside get_or_create_metadata for new agents
        # but we ensure it's saved here in case metadata was loaded from file
        save_metadata()
        
        # Data directory for CSV logging
        if data_dir is None:
            # Default to local project data directory
            project_root = Path(__file__).parent.parent
            data_dir = project_root / "data"
        
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.csv_file = self.data_dir / f"governance_history_{agent_id}.csv"
        
        # Initialize CSV if needed
        if not self.csv_file.exists():
            self._init_csv()
        
        # Track previous response for coherence
        self.prev_response: Optional[str] = None
        
        print(f"[Bridge] Initialized for agent: {agent_id}")
        print(f"[Bridge] CSV: {self.csv_file}")
        print(f"[Bridge] Metadata: Registered in agent_metadata.json")
    
    def _init_csv(self):
        """Initialize CSV file with headers"""
        headers = "agent_id,time,E,I,S,V,lambda1,coherence,void_event,risk_score,decision\n"
        with open(self.csv_file, 'w') as f:
            f.write(headers)
        print(f"[Bridge] Created CSV: {self.csv_file}")
    
    def calculate_metrics(self, 
                          response_text: str,
                          complexity: Optional[float] = None) -> Dict[str, float]:
        """
        Calculate metrics from Claude Code response.
        
        Returns:
        {
            'length_score': 0-1 normalized,
            'complexity': 0-1 estimated,
            'info_score': 0-1 information density,
            'coherence_score': 0-1 similarity with previous,
            'ethical_drift': 0-1 deviation measure
        }
        """
        # Length score (sigmoid normalization)
        length = len(response_text)
        length_score = 1 / (1 + np.exp(-(length - 500) / 200))  # 50% at 500 chars
        
        # Complexity (from param or estimate)
        if complexity is None:
            # Auto-estimate from content
            has_code = '```' in response_text
            has_tools = 'tool_call' in response_text.lower()
            has_technical = any(term in response_text.lower() 
                              for term in ['algorithm', 'function', 'class', 'import', 'async'])
            
            complexity = 0.2  # Base
            if has_code:
                complexity += 0.3
            if has_tools:
                complexity += 0.3
            if has_technical:
                complexity += 0.2
            
            complexity = min(complexity, 1.0)
        
        # Information density (unique words / total words)
        words = response_text.lower().split()
        if len(words) > 0:
            unique_words = len(set(words))
            info_score = min(unique_words / len(words), 1.0)
        else:
            info_score = 0.0
        
        # Coherence (similarity with previous response)
        if self.prev_response is None:
            coherence_score = 1.0  # First response, assume coherent
        else:
            # Simple word overlap metric
            prev_words = set(self.prev_response.lower().split())
            curr_words = set(response_text.lower().split())
            
            if len(prev_words) > 0 and len(curr_words) > 0:
                overlap = len(prev_words & curr_words)
                union = len(prev_words | curr_words)
                coherence_score = overlap / union if union > 0 else 0.0
            else:
                coherence_score = 0.5
        
        # Ethical drift (inverse coherence + complexity contribution)
        ethical_drift = (1.0 - coherence_score) * 0.5 + complexity * 0.3
        
        # Update previous response
        self.prev_response = response_text
        
        return {
            'length_score': float(length_score),
            'complexity': float(complexity),
            'info_score': float(info_score),
            'coherence_score': float(coherence_score),
            'ethical_drift': float(ethical_drift)
        }
    
    def convert_to_agent_state(self, metrics: Dict[str, float]) -> Dict:
        """
        Converts metrics to agent_state format for governance monitor.
        
        Creates 128-dim parameter vector with meaningful structure:
        - First 4: Core metrics (length, complexity, info, coherence)
        - Next 124: Noise + structural features
        """
        # Core parameters (first 4 dimensions)
        core_params = [
            metrics['length_score'],
            metrics['complexity'],
            metrics['info_score'],
            metrics['coherence_score']
        ]
        
        # Fill remaining dimensions with structured noise
        # (In production, these would be actual model parameters)
        noise_params = list(np.random.randn(124) * 0.01)
        
        parameters = core_params + noise_params
        
        # Ethical drift vector (3 components)
        ethical_drift = [
            metrics['ethical_drift'],
            1.0 - metrics['coherence_score'],  # Coherence loss
            metrics['complexity'] * 0.5  # Complexity contribution
        ]
        
        return {
            'parameters': parameters,
            'ethical_drift': ethical_drift
        }
    
    def log_interaction(self, 
                       response_text: str,
                       complexity: Optional[float] = None) -> Dict:
        """
        Main method: Log Claude Code interaction to governance system.
        
        Steps:
        1. Calculate metrics from response
        2. Convert to agent_state format
        3. Send to governance MCP
        4. Log to CSV
        5. Return result
        """
        # Calculate metrics
        metrics = self.calculate_metrics(response_text, complexity)
        
        # Convert to agent_state
        agent_state = self.convert_to_agent_state(metrics)
        agent_state['response_text'] = response_text
        agent_state['complexity'] = metrics['complexity']
        
        # Send to governance MCP
        request = {
            'tool': 'process_agent_update',
            'params': {
                'agent_id': self.agent_id,
                **agent_state
            }
        }
        
        result = self.server.handle_request(request)
        
        # Log to CSV if successful
        if result.get('success'):
            self._log_to_csv(result)
            
            # Update agent metadata
            self.metadata.total_updates += 1
            self.metadata.last_update = datetime.now().isoformat()
            save_metadata()
        
        return result
    
    def _log_to_csv(self, result: Dict):
        """Append result to CSV file"""
        if not result.get('success'):
            return
        
        metrics = result['metrics']
        decision = result['decision']
        
        row = (
            f"{self.agent_id},"
            f"{metrics['time']:.3f},"
            f"{metrics['E']:.4f},"
            f"{metrics['I']:.4f},"
            f"{metrics['S']:.4f},"
            f"{metrics['V']:.4f},"
            f"{metrics['lambda1']:.4f},"
            f"{metrics['coherence']:.4f},"
            f"{1 if metrics['void_active'] else 0},"
            f"{metrics['risk_score']:.4f},"
            f"{decision['action']}\n"
        )
        
        with open(self.csv_file, 'a') as f:
            f.write(row)
    
    def get_status(self) -> Dict:
        """Get current governance status"""
        request = {
            'tool': 'get_governance_metrics',
            'params': {'agent_id': self.agent_id}
        }
        return self.server.handle_request(request)
    
    def export_history(self) -> Dict:
        """Export complete history"""
        request = {
            'tool': 'get_system_history',
            'params': {
                'agent_id': self.agent_id,
                'format': 'json'
            }
        }
        return self.server.handle_request(request)
    
    def run_test(self):
        """Run test sequence"""
        print("\n" + "="*60)
        print("Running Claude Code Bridge Test")
        print("="*60)
        
        test_responses = [
            "Simple response without code.",
            """Here's a Python function:
            ```python
            def hello():
                return "world"
            ```
            """,
            "This is a very long response " * 50,
            "Complex algorithmic analysis with technical details about async functions and class hierarchies."
        ]
        
        for i, response in enumerate(test_responses):
            print(f"\n[Test {i+1}] Processing response...")
            result = self.log_interaction(response)
            
            if result['success']:
                print(f"  Status: {result['status']}")
                print(f"  Decision: {result['decision']['action']} - {result['decision']['reason']}")
                print(f"  Metrics: E={result['metrics']['E']:.3f}, "
                      f"λ₁={result['metrics']['lambda1']:.3f}, "
                      f"Risk={result['metrics']['risk_score']:.3f}")
            else:
                print(f"  Error: {result.get('error')}")
        
        # Final status
        print("\n" + "="*60)
        print("Final Status:")
        status = self.get_status()
        if status['success']:
            print(json.dumps(status, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Claude Code → UNITARES Governance Bridge")
    parser.add_argument('--log', type=str, help='Log a response to governance system')
    parser.add_argument('--complexity', type=float, help='Override complexity estimate (0-1)')
    parser.add_argument('--status', action='store_true', help='Get current status')
    parser.add_argument('--export', action='store_true', help='Export history')
    parser.add_argument('--test', action='store_true', help='Run test sequence')
    parser.add_argument('--agent-id', type=str, default=None, help='Agent identifier (default: auto-generate unique ID)')
    parser.add_argument('--data-dir', type=str, help='Data directory for CSV')
    parser.add_argument('--non-interactive', action='store_true', help='Non-interactive mode (auto-generates agent ID)')

    args = parser.parse_args()

    # Create bridge with smart agent ID management
    bridge = ClaudeCodeBridge(
        agent_id=args.agent_id,
        data_dir=Path(args.data_dir) if args.data_dir else None,
        interactive=not args.non_interactive
    )
    
    # Execute command
    if args.test:
        bridge.run_test()
    
    elif args.log:
        result = bridge.log_interaction(args.log, args.complexity)
        print(json.dumps(result, indent=2))
    
    elif args.status:
        status = bridge.get_status()
        print(json.dumps(status, indent=2))
    
    elif args.export:
        history = bridge.export_history()
        print(history['history'] if history['success'] else json.dumps(history, indent=2))
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
