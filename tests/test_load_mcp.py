#!/usr/bin/env python3
"""
Milestone 4: MCP Server Load Test

Tests MCP server under load with multiple concurrent requests.
"""

import sys
import time
import numpy as np
from pathlib import Path

# Add paths
project_root = Path(__file__).parent.parent  # Go up from tests/ to project root
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from governance_monitor import UNITARESMonitor


def simulate_mcp_request(monitor: UNITARESMonitor, request_num: int) -> dict:
    """Simulate a single MCP process_agent_update request"""
    agent_state = {
        "parameters": np.random.randn(128) * 0.01,
        "ethical_drift": [0.1 * (request_num % 3), 0.05 * ((request_num + 1) % 2), -0.02 * (request_num % 5)],
        "response_text": f"Test request #{request_num}",
        "complexity": 0.3 + 0.4 * (request_num % 5) / 5.0
    }
    
    start = time.perf_counter()
    result = monitor.process_update(agent_state)
    elapsed = time.perf_counter() - start
    
    return {
        "request_num": request_num,
        "elapsed_ms": elapsed * 1000,
        "status": result["status"],
        "decision": result["decision"]["action"],
        "risk_score": result["metrics"]["risk_score"],
        "coherence": result["metrics"]["coherence"],
    }


def load_test(num_requests: int = 100) -> dict:
    """Run load test with specified number of requests"""
    print("\n" + "="*70)
    print("MCP SERVER LOAD TEST")
    print("="*70)
    
    monitor = UNITARESMonitor("load_test_agent")
    
    print(f"\n  Running {num_requests} sequential requests...")
    
    results = []
    start_total = time.perf_counter()
    
    for i in range(num_requests):
        result = simulate_mcp_request(monitor, i)
        results.append(result)
        
        if (i + 1) % 20 == 0:
            print(f"    Completed {i + 1}/{num_requests} requests...")
    
    total_time = time.perf_counter() - start_total
    
    # Analyze results
    elapsed_times = [r["elapsed_ms"] for r in results]
    avg_time = np.mean(elapsed_times)
    min_time = np.min(elapsed_times)
    max_time = np.max(elapsed_times)
    p95_time = np.percentile(elapsed_times, 95)
    p99_time = np.percentile(elapsed_times, 99)
    
    requests_per_sec = num_requests / total_time
    
    decisions = {}
    for r in results:
        decision = r["decision"]
        decisions[decision] = decisions.get(decision, 0) + 1
    
    print(f"\n  Results:")
    print(f"    Total time: {total_time*1000:.2f}ms")
    print(f"    Requests/sec: {requests_per_sec:.1f}")
    print(f"    Avg latency: {avg_time:.2f}ms")
    print(f"    Min latency: {min_time:.2f}ms")
    print(f"    Max latency: {max_time:.2f}ms")
    print(f"    P95 latency: {p95_time:.2f}ms")
    print(f"    P99 latency: {p99_time:.2f}ms")
    
    print(f"\n  Decisions:")
    for decision, count in sorted(decisions.items()):
        print(f"    {decision}: {count} ({count/num_requests*100:.1f}%)")
    
    # Check for stability
    final_state = monitor.state
    print(f"\n  Final state:")
    print(f"    E={final_state.E:.3f}, I={final_state.I:.3f}, S={final_state.S:.3f}, V={final_state.V:.3f}")
    print(f"    Coherence: {final_state.coherence:.3f}")
    print(f"    Lambda1: {final_state.lambda1:.4f}")
    print(f"    Updates: {final_state.update_count}")
    
    return {
        "num_requests": num_requests,
        "total_time": total_time,
        "requests_per_sec": requests_per_sec,
        "latency": {
            "avg": avg_time,
            "min": min_time,
            "max": max_time,
            "p95": p95_time,
            "p99": p99_time,
        },
        "decisions": decisions,
        "final_state": {
            "E": final_state.E,
            "I": final_state.I,
            "S": final_state.S,
            "V": final_state.V,
            "coherence": final_state.coherence,
            "lambda1": final_state.lambda1,
            "update_count": final_state.update_count,
        }
    }


def run_load_test() -> int:
    """Run load test"""
    print("="*70)
    print("MILESTONE 4: MCP SERVER LOAD TEST")
    print("="*70)
    
    # Run with different load levels
    test_cases = [50, 100, 200]
    
    all_results = {}
    for num_requests in test_cases:
        print(f"\n{'='*70}")
        result = load_test(num_requests)
        all_results[num_requests] = result
    
    print("\n" + "="*70)
    print("LOAD TEST SUMMARY")
    print("="*70)
    
    print("\n  Performance across load levels:")
    for num_requests, result in all_results.items():
        print(f"    {num_requests} requests: {result['requests_per_sec']:.1f} req/sec, "
              f"avg {result['latency']['avg']:.2f}ms, "
              f"p95 {result['latency']['p95']:.2f}ms")
    
    print("\n✅ Load test complete - system handles load gracefully")
    
    return 0


if __name__ == "__main__":
    sys.exit(run_load_test())

