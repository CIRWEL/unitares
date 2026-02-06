#!/usr/bin/env python3
"""
Test what drives EISV metric changes

Goal: Isolate whether metrics change due to:
1. Update count (agent maturation)
2. Complexity parameter
3. Text content/length
4. Time elapsed
5. Something else

Methodology:
- Test 1: Same complexity, multiple updates (isolate count effect)
- Test 2: Varying complexity, same agent (isolate complexity effect)
- Test 3: Different text lengths (isolate content effect)
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.mcp_sse_client import GovernanceMCPClient


async def test_update_count_effect():
    """Test 1: Does update count alone drive changes?"""
    print("\n" + "="*70)
    print("TEST 1: Update Count Effect (constant complexity=0.5)")
    print("="*70)

    async with GovernanceMCPClient() as client:
        agent_id = "test_update_count"
        complexity = 0.5  # Keep constant

        # Run 10 updates with identical parameters
        results = []
        for i in range(1, 11):
            result = await client.process_agent_update(
                agent_id=agent_id,
                response_text=f"Update {i}: Same complexity, same length text",
                complexity=complexity
            )
            metrics = result['metrics']
            results.append({
                'update': i,
                'E': metrics.get('E', 0),
                'I': metrics.get('I', 0),
                'S': metrics.get('S', 0),
                'V': metrics.get('V', 0),
                'coherence': metrics.get('coherence', 0),
                'regime': result.get('regime', 'unknown')
            })

            print(f"Update {i:2d}: E={metrics.get('E', 0):.3f} I={metrics.get('I', 0):.3f} "
                  f"S={metrics.get('S', 0):.3f} V={metrics.get('V', 0):+.3f} "
                  f"coherence={metrics.get('coherence', 0):.3f} regime={result.get('regime', 'unknown')}")

            await asyncio.sleep(0.3)

        # Analyze trend
        E_trend = results[-1]['E'] - results[0]['E']
        I_trend = results[-1]['I'] - results[0]['I']
        S_trend = results[-1]['S'] - results[0]['S']

        print(f"\n📊 Trends over 10 updates (constant complexity=0.5):")
        print(f"   E: {results[0]['E']:.3f} → {results[-1]['E']:.3f} (Δ={E_trend:+.3f})")
        print(f"   I: {results[0]['I']:.3f} → {results[-1]['I']:.3f} (Δ={I_trend:+.3f})")
        print(f"   S: {results[0]['S']:.3f} → {results[-1]['S']:.3f} (Δ={S_trend:+.3f})")

        if E_trend > 0.01 or I_trend > 0.01 or abs(S_trend) > 0.01:
            print("   ✅ CONFIRMED: Metrics evolve with update count alone")
        else:
            print("   ❌ NO EFFECT: Metrics stable despite updates")

        return results


async def test_complexity_effect():
    """Test 2: Does complexity parameter affect metrics?"""
    print("\n" + "="*70)
    print("TEST 2: Complexity Parameter Effect")
    print("="*70)

    async with GovernanceMCPClient() as client:
        agent_id = "test_complexity"

        # Single agent, vary complexity dramatically
        complexities = [0.1, 0.3, 0.5, 0.7, 0.9, 0.9, 0.7, 0.5, 0.3, 0.1]
        results = []

        for i, complexity in enumerate(complexities, 1):
            result = await client.process_agent_update(
                agent_id=agent_id,
                response_text=f"Update {i} with complexity {complexity}",
                complexity=complexity
            )
            metrics = result['metrics']
            results.append({
                'update': i,
                'complexity': complexity,
                'E': metrics.get('E', 0),
                'I': metrics.get('I', 0),
                'S': metrics.get('S', 0),
            })

            print(f"Update {i:2d} (complexity={complexity:.1f}): "
                  f"E={metrics.get('E', 0):.3f} I={metrics.get('I', 0):.3f} S={metrics.get('S', 0):.3f}")

            await asyncio.sleep(0.3)

        # Check if metrics follow complexity changes
        print(f"\n📊 Analysis:")
        print(f"   Complexity pattern: {complexities[0]:.1f} → {complexities[4]:.1f} → {complexities[-1]:.1f}")
        print(f"   E pattern: {results[0]['E']:.3f} → {results[4]['E']:.3f} → {results[-1]['E']:.3f}")
        print(f"   S pattern: {results[0]['S']:.3f} → {results[4]['S']:.3f} → {results[-1]['S']:.3f}")

        # If complexity mattered, S should track complexity
        if abs(results[4]['S'] - results[0]['S']) > 0.1:
            print("   ✅ Complexity affects metrics")
        else:
            print("   ❌ Complexity has minimal effect")

        return results


async def test_text_length_effect():
    """Test 3: Does text length/content affect metrics?"""
    print("\n" + "="*70)
    print("TEST 3: Text Content Effect")
    print("="*70)

    async with GovernanceMCPClient() as client:
        agent_id = "test_text_content"
        complexity = 0.5  # Keep constant

        texts = [
            "Short.",
            "A medium length response with more words to test if length matters.",
            "A very long detailed response with lots of content and information, " * 5,
            "Short again.",
            "VERY COMPLEX TECHNICAL JARGON UNCERTAINTY MAYBE POSSIBLY CONFUSED",
            "Simple clear confident certain definite answer yes.",
        ]

        results = []
        for i, text in enumerate(texts, 1):
            result = await client.process_agent_update(
                agent_id=agent_id,
                response_text=text,
                complexity=complexity
            )
            metrics = result['metrics']
            results.append({
                'update': i,
                'text_len': len(text),
                'E': metrics.get('E', 0),
                'S': metrics.get('S', 0),
            })

            print(f"Update {i} (len={len(text):3d}): E={metrics.get('E', 0):.3f} S={metrics.get('S', 0):.3f}")

            await asyncio.sleep(0.3)

        print(f"\n📊 Analysis:")
        print(f"   Text lengths: {[r['text_len'] for r in results]}")
        e_values = [round(r['E'], 3) for r in results]
        print(f"   E values:     {e_values}")

        # Check if E/S follow text length
        if max(r['E'] for r in results) - min(r['E'] for r in results) < 0.05:
            print("   ❌ Text content has minimal effect")
        else:
            print("   ✅ Text content affects metrics")

        return results


async def test_pure_time_effect():
    """Test 4: Does time elapsed matter?"""
    print("\n" + "="*70)
    print("TEST 4: Time Elapsed Effect")
    print("="*70)

    async with GovernanceMCPClient() as client:
        agent_id = "test_time_effect"

        # Two updates with 5 second gap vs rapid updates
        print("\nRapid updates (0.3s apart):")
        result1 = await client.process_agent_update(
            agent_id=agent_id + "_rapid",
            response_text="Update 1",
            complexity=0.5
        )
        await asyncio.sleep(0.3)
        result2 = await client.process_agent_update(
            agent_id=agent_id + "_rapid",
            response_text="Update 2",
            complexity=0.5
        )
        rapid_change = result2['metrics']['E'] - result1['metrics']['E']
        print(f"   E change: {rapid_change:+.4f}")

        print("\nSlow updates (5s apart):")
        result3 = await client.process_agent_update(
            agent_id=agent_id + "_slow",
            response_text="Update 1",
            complexity=0.5
        )
        await asyncio.sleep(5.0)
        result4 = await client.process_agent_update(
            agent_id=agent_id + "_slow",
            response_text="Update 2",
            complexity=0.5
        )
        slow_change = result4['metrics']['E'] - result3['metrics']['E']
        print(f"   E change: {slow_change:+.4f}")

        print(f"\n📊 Time effect:")
        if abs(slow_change - rapid_change) > 0.01:
            print(f"   ✅ Time elapsed matters (Δ={abs(slow_change - rapid_change):.4f})")
        else:
            print(f"   ❌ Time has minimal effect")


async def main():
    """Run all tests"""
    print("="*70)
    print("EISV DRIVER ISOLATION TESTS")
    print("="*70)
    print("\nGoal: Determine what actually drives EISV metric changes")

    try:
        await test_update_count_effect()
        await asyncio.sleep(1)

        await test_complexity_effect()
        await asyncio.sleep(1)

        await test_text_length_effect()
        await asyncio.sleep(1)

        await test_pure_time_effect()

        print("\n" + "="*70)
        print("CONCLUSION")
        print("="*70)
        print("\nBased on the tests above, we can determine whether EISV metrics")
        print("are driven by update count, complexity, text content, time, or")
        print("a combination of factors.")
        print()

    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
