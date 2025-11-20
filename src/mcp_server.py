"""
UNITARES Governance MCP Server v1.0
Provides governance monitoring tools via Model Context Protocol
"""

import sys
import json
from typing import Dict, Optional
from datetime import datetime
import numpy as np

# MCP SDK imports (stub for now - would need actual mcp package)
# from mcp import Server, Tool
# For this version, we'll create a simple JSON-RPC style interface

from src.governance_monitor import UNITARESMonitor


class GovernanceMCPServer:
    """
    MCP Server for UNITARES Governance Framework
    
    Provides tools:
    - process_agent_update: Run one governance cycle
    - get_governance_metrics: Get current system state
    - get_system_history: Export time series data
    - reset_monitor: Reset governance state for agent
    """
    
    def __init__(self):
        self.monitors: Dict[str, UNITARESMonitor] = {}
        print("[UNITARES MCP] Server initialized")
    
    def get_or_create_monitor(self, agent_id: str) -> UNITARESMonitor:
        """Gets existing monitor or creates new one for agent"""
        if agent_id not in self.monitors:
            print(f"[UNITARES MCP] Creating new monitor for agent: {agent_id}")
            self.monitors[agent_id] = UNITARESMonitor(agent_id)
        return self.monitors[agent_id]
    
    def tool_process_agent_update(self, params: Dict) -> Dict:
        """
        Tool: process_agent_update
        
        Runs one complete governance cycle for an agent.
        
        Parameters:
        - agent_id: str, unique identifier for agent
        - parameters: list[float], agent parameters (e.g., model weights)
        - ethical_drift: list[float], ethical signal values
        - response_text: str (optional), agent's response text
        - complexity: float (optional), estimated complexity
        
        Returns:
        {
            'success': bool,
            'status': 'healthy' | 'degraded' | 'critical',
            'decision': {
                'action': 'approve' | 'revise' | 'reject',
                'reason': str,
                'require_human': bool
            },
            'metrics': {
                'E': float, 'I': float, 'S': float, 'V': float,
                'coherence': float, 'lambda1': float, 'risk_score': float,
                'void_active': bool
            },
            'sampling_params': {
                'temperature': float, 'top_p': float, 'max_tokens': int
            }
        }
        """
        try:
            agent_id = params.get('agent_id', 'default_agent')
            
            # Get or create monitor
            monitor = self.get_or_create_monitor(agent_id)
            
            # Prepare agent state
            agent_state = {
                'parameters': np.array(params.get('parameters', [])),
                'ethical_drift': np.array(params.get('ethical_drift', [])),
                'response_text': params.get('response_text', ''),
                'complexity': params.get('complexity', 0.5)
            }
            
            # Process update
            result = monitor.process_update(agent_state)
            
            return {
                'success': True,
                **result
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def tool_get_governance_metrics(self, params: Dict) -> Dict:
        """
        Tool: get_governance_metrics
        
        Returns current governance state for an agent.
        
        Parameters:
        - agent_id: str, agent identifier
        
        Returns:
        {
            'success': bool,
            'metrics': {...},
            'status': str,
            'sampling_params': {...}
        }
        """
        try:
            agent_id = params.get('agent_id', 'default_agent')
            
            if agent_id not in self.monitors:
                return {
                    'success': False,
                    'error': f'No monitor found for agent: {agent_id}'
                }
            
            monitor = self.monitors[agent_id]
            metrics = monitor.get_metrics()
            
            return {
                'success': True,
                **metrics,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def tool_get_system_history(self, params: Dict) -> Dict:
        """
        Tool: get_system_history
        
        Exports complete history for an agent.
        
        Parameters:
        - agent_id: str, agent identifier
        - format: str (optional), 'json' or 'csv' (default: json)
        
        Returns:
        {
            'success': bool,
            'history': str (formatted according to format param)
        }
        """
        try:
            agent_id = params.get('agent_id', 'default_agent')
            format = params.get('format', 'json')
            
            if agent_id not in self.monitors:
                return {
                    'success': False,
                    'error': f'No monitor found for agent: {agent_id}'
                }
            
            monitor = self.monitors[agent_id]
            history = monitor.export_history(format=format)
            
            return {
                'success': True,
                'history': history,
                'format': format,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def tool_reset_monitor(self, params: Dict) -> Dict:
        """
        Tool: reset_monitor
        
        Resets governance state for an agent (useful for testing).
        
        Parameters:
        - agent_id: str, agent identifier
        
        Returns:
        {
            'success': bool,
            'message': str
        }
        """
        try:
            agent_id = params.get('agent_id', 'default_agent')
            
            if agent_id in self.monitors:
                del self.monitors[agent_id]
                message = f'Monitor reset for agent: {agent_id}'
            else:
                message = f'No monitor existed for agent: {agent_id}'
            
            return {
                'success': True,
                'message': message,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def list_tools(self) -> Dict:
        """Returns list of available tools"""
        return {
            'tools': [
                {
                    'name': 'process_agent_update',
                    'description': 'Run one complete governance cycle',
                    'parameters': ['agent_id', 'parameters', 'ethical_drift', 'response_text', 'complexity']
                },
                {
                    'name': 'get_governance_metrics',
                    'description': 'Get current governance state',
                    'parameters': ['agent_id']
                },
                {
                    'name': 'get_system_history',
                    'description': 'Export time series data',
                    'parameters': ['agent_id', 'format']
                },
                {
                    'name': 'reset_monitor',
                    'description': 'Reset governance state',
                    'parameters': ['agent_id']
                }
            ]
        }
    
    def handle_request(self, request: Dict) -> Dict:
        """
        Main request handler for JSON-RPC style interface.
        
        Request format:
        {
            'tool': 'tool_name',
            'params': {...}
        }
        """
        tool_name = request.get('tool')
        params = request.get('params', {})
        
        handlers = {
            'process_agent_update': self.tool_process_agent_update,
            'get_governance_metrics': self.tool_get_governance_metrics,
            'get_system_history': self.tool_get_system_history,
            'reset_monitor': self.tool_reset_monitor,
            'list_tools': lambda p: self.list_tools()
        }
        
        if tool_name not in handlers:
            return {
                'success': False,
                'error': f'Unknown tool: {tool_name}',
                'available_tools': list(handlers.keys())
            }
        
        return handlers[tool_name](params)
    
    def run_interactive(self):
        """Run server in interactive mode (for testing)"""
        print("\n" + "="*60)
        print("UNITARES Governance MCP Server v1.0")
        print("="*60)
        print("\nAvailable tools:")
        for tool in self.list_tools()['tools']:
            print(f"  - {tool['name']}: {tool['description']}")
        print("\nType 'help' for usage, 'exit' to quit\n")
        
        while True:
            try:
                cmd = input("mcp> ").strip()
                
                if cmd == 'exit':
                    print("Shutting down...")
                    break
                
                if cmd == 'help':
                    print("\nUsage:")
                    print("  tool_name {json_params}")
                    print("\nExample:")
                    print('  process_agent_update {"agent_id": "test", "parameters": [0.1, 0.2], "ethical_drift": [0.01, 0.02, 0.03]}')
                    print()
                    continue
                
                if not cmd:
                    continue
                
                # Parse command
                parts = cmd.split(None, 1)
                tool_name = parts[0]
                params = json.loads(parts[1]) if len(parts) > 1 else {}
                
                # Execute
                request = {'tool': tool_name, 'params': params}
                response = self.handle_request(request)
                
                # Pretty print response
                print(json.dumps(response, indent=2))
                print()
                
            except json.JSONDecodeError as e:
                print(f"JSON Error: {e}")
            except KeyboardInterrupt:
                print("\nUse 'exit' to quit")
            except Exception as e:
                print(f"Error: {e}")


def main():
    """Main entry point"""
    server = GovernanceMCPServer()
    
    # Check if running in interactive mode
    if len(sys.argv) > 1 and sys.argv[1] == '--interactive':
        server.run_interactive()
    else:
        # In production, would integrate with MCP SDK here
        print("[UNITARES MCP] Server ready (use --interactive for testing)")
        print("[UNITARES MCP] Waiting for tool calls...")


if __name__ == "__main__":
    main()
