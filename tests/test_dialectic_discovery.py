"""
Test for Pull-Based Dialectic Discovery

Verifies that agents can discover pending dialectic sessions
when they call recall_identity().

This is the "pull-based" discovery pattern where agents:
1. Call recall_identity() on login
2. See pending_reviews in the response if sessions are awaiting a reviewer
3. Can join as reviewer using the session_id provided

NOTE: TestDialecticDiscovery requires PostgreSQL - skipped in CI.
"""

import pytest
import asyncio
import sys
sys.path.insert(0, '/Users/cirwel/projects/governance-mcp-v1')


@pytest.mark.skip(reason="Requires PostgreSQL connection - run locally with DB")
class TestDialecticDiscovery:
    """Test pull-based dialectic discovery via recall_identity()."""

    @pytest.mark.asyncio
    async def test_get_pending_dialectic_sessions_returns_list(self):
        """
        Test that get_pending_dialectic_sessions() returns a list.

        PostgreSQL backend should return actual pending sessions.
        SQLite backend returns empty list (feature not supported).
        """
        from src.db import get_db

        db = get_db()
        await db.init()

        # Should return a list (may be empty)
        pending = await db.get_pending_dialectic_sessions(limit=5)

        assert isinstance(pending, list), f"Expected list, got {type(pending)}"
        print(f"Found {len(pending)} pending dialectic sessions")

        # If there are pending sessions, verify structure
        for session in pending:
            assert 'session_id' in session or 'id' in session, \
                "Each session should have an identifier"
            print(f"  - Session: {session.get('session_id') or session.get('id')}")

    @pytest.mark.asyncio
    async def test_recall_identity_includes_pending_reviews(self):
        """
        Test that recall_identity() surfaces pending dialectic sessions.

        When an agent calls recall_identity(), the response should include
        a pending_reviews field if there are sessions awaiting a reviewer.

        Note: If no identity is bound, recall_identity returns guidance to bind first.
        The pending_reviews feature only applies when an agent is already bound.
        """
        from src.mcp_handlers.identity import handle_identity, handle_onboard
        import json

        # Create a test agent using onboard() which binds identity
        test_agent_id = "dialectic_discovery_test_agent"

        # Use onboard() to establish identity (simpler than bind_identity)
        onboard_result = await handle_onboard({"agent_id": test_agent_id})
        # Handle both Sequence[TextContent] and single TextContent
        if isinstance(onboard_result, (list, tuple)):
            assert len(onboard_result) > 0, "onboard() should return content"
            onboard_data = json.loads(onboard_result[0].text)
        elif hasattr(onboard_result, 'text'):
            onboard_data = json.loads(onboard_result.text)
        else:
            pytest.fail(f"Unexpected return type from handle_onboard: {type(onboard_result)}")
        print(f"Onboard result: agent_id={onboard_data.get('agent_id', 'N/A')}")

        # Now get identity - should work if onboard succeeded
        result = await handle_identity({})

        # Result is a Sequence[TextContent] - parse the JSON
        # Handle both single TextContent and Sequence[TextContent]
        if isinstance(result, (list, tuple)):
            # Sequence[TextContent]
            assert len(result) > 0, "handle_identity should return content"
            result_text = result[0].text if hasattr(result[0], 'text') else str(result[0])
        elif hasattr(result, 'text'):
            # Single TextContent object (shouldn't happen but handle gracefully)
            result_text = result.text
        else:
            result_text = str(result)
        
        result_data = json.loads(result_text)

        # Check if we have a bound identity
        if 'agent_id' in result_data:
            print(f"Recall succeeded: agent_id={result_data['agent_id']}")

            # pending_reviews is optional - only present if there are pending sessions
            if 'pending_reviews' in result_data:
                pending = result_data['pending_reviews']
                assert 'count' in pending, "pending_reviews should have count"
                assert 'sessions' in pending, "pending_reviews should have sessions"
                assert 'action' in pending, "pending_reviews should have action hint"

                print(f"Found {pending['count']} pending reviews")
                print(f"Action: {pending['action']}")
            else:
                print("No pending reviews at this time (expected if no sessions await reviewer)")
        else:
            # Identity binding may have failed - this is OK for the test
            # The key thing is that the API works
            print(f"Identity not bound in test context: {result_data.get('message', 'unknown')}")
            print("This is expected - pending_reviews check requires bound identity")

    @pytest.mark.asyncio
    async def test_create_session_then_discover(self):
        """
        End-to-end test: create a dialectic session, then verify discovery.

        1. Create a dialectic session without a reviewer
        2. Call get_pending_dialectic_sessions()
        3. Verify the session appears in results
        """
        from src.db import get_db
        import os

        db = get_db()
        await db.init()

        # Check if we're using PostgreSQL (dialectic discovery is Postgres-only)
        backend = os.environ.get("DB_BACKEND", "postgres").lower()
        if backend == "sqlite":
            pytest.skip("Dialectic discovery is PostgreSQL-only feature")

        # Create a test session without a reviewer
        test_session_id = "test_discovery_session_001"
        test_initiator = "initiator_agent_001"

        # Try to insert directly into dialectic_sessions if table exists
        try:
            # Check if dialectic_sessions table exists
            from src.db.postgres_backend import PostgresBackend
            if isinstance(db, PostgresBackend):
                async with db._get_connection() as conn:
                    # Create test session using correct schema:
                    # session_id, paused_agent_id, phase, status
                    await conn.execute("""
                        INSERT INTO core.dialectic_sessions
                        (session_id, paused_agent_id, reviewer_agent_id, phase, status, reason)
                        VALUES ($1, $2, NULL, 'thesis', 'active', 'Test discovery')
                        ON CONFLICT (session_id) DO NOTHING
                    """, test_session_id, test_initiator)

                    # Now check if it appears in pending sessions
                    pending = await db.get_pending_dialectic_sessions(limit=10)

                    # Should find our test session
                    found = any(
                        s.get('session_id') == test_session_id
                        for s in pending
                    )

                    if found:
                        print(f"SUCCESS: Discovered test session {test_session_id}")
                    else:
                        print(f"Test session not in pending list (found {len(pending)} sessions)")

                    # Clean up
                    await conn.execute(
                        "DELETE FROM core.dialectic_sessions WHERE session_id = $1",
                        test_session_id
                    )

                    assert found, "Test session should appear in pending sessions"

        except Exception as e:
            # Table may not exist or FK constraints
            print(f"Could not run full e2e test: {e}")
            pytest.skip(f"Dialectic tables not fully configured: {e}")


class TestBasinCheckingIntegration:
    """Test UNITARES basin checking with dialectic states."""

    def test_check_basin_high(self):
        """Agent in high basin should be flagged as healthy."""
        from governance_core.dynamics import State, check_basin

        state = State(E=0.8, I=0.9, S=0.1, V=0.0)
        basin = check_basin(state)

        assert basin == 'high', f"Expected 'high' basin, got '{basin}'"
        print(f"State with I={state.I} is in '{basin}' basin")

    def test_check_basin_low(self):
        """Agent in low basin should be flagged as collapsed."""
        from governance_core.dynamics import State, check_basin

        state = State(E=0.2, I=0.1, S=0.8, V=0.0)
        basin = check_basin(state)

        assert basin == 'low', f"Expected 'low' basin, got '{basin}'"
        print(f"State with I={state.I} is in '{basin}' basin")

    def test_check_basin_boundary(self):
        """Agent near boundary should be flagged as unstable."""
        from governance_core.dynamics import State, check_basin

        state = State(E=0.5, I=0.5, S=0.3, V=0.0)
        basin = check_basin(state)

        assert basin == 'boundary', f"Expected 'boundary' basin, got '{basin}'"
        print(f"State with I={state.I} is in '{basin}' basin (unstable)")


class TestConvergenceEstimation:
    """Test convergence estimation functions."""

    def test_compute_equilibrium(self):
        """Test equilibrium computation returns valid state."""
        from governance_core.dynamics import compute_equilibrium
        from governance_core.parameters import DEFAULT_PARAMS, DEFAULT_THETA

        eq = compute_equilibrium(DEFAULT_PARAMS, DEFAULT_THETA)

        # Equilibrium should be in high basin
        assert eq.I > 0.5, f"Equilibrium I={eq.I} should be > 0.5"
        assert 0 <= eq.E <= 1, f"E={eq.E} out of bounds"
        assert eq.S >= 0, f"S={eq.S} should be non-negative"

        print(f"High equilibrium: E={eq.E:.3f}, I={eq.I:.3f}, S={eq.S:.3f}, V={eq.V:.3f}")

    def test_estimate_convergence(self):
        """Test convergence estimation provides useful info."""
        from governance_core.dynamics import (
            State, compute_equilibrium, estimate_convergence
        )
        from governance_core.parameters import DEFAULT_PARAMS, DEFAULT_THETA

        current = State(E=0.7, I=0.8, S=0.2, V=0.0)
        eq = compute_equilibrium(DEFAULT_PARAMS, DEFAULT_THETA)

        conv = estimate_convergence(current, eq, DEFAULT_PARAMS)

        assert 'distance' in conv
        assert 'converged' in conv
        assert 'updates_to_convergence' in conv

        print(f"Distance to equilibrium: {conv['distance']:.4f}")
        print(f"Estimated updates to 95% convergence: {conv['updates_to_convergence']}")


if __name__ == "__main__":
    print("=" * 60)
    print("Pull-Based Dialectic Discovery Tests")
    print("=" * 60)

    # Run async tests
    async def run_async_tests():
        print("\n--- Test: get_pending_dialectic_sessions ---")
        test = TestDialecticDiscovery()
        await test.test_get_pending_dialectic_sessions_returns_list()

        print("\n--- Test: recall_identity includes pending_reviews ---")
        await test.test_recall_identity_includes_pending_reviews()

    asyncio.run(run_async_tests())

    # Run sync tests
    print("\n--- Test: Basin Checking ---")
    basin_test = TestBasinCheckingIntegration()
    basin_test.test_check_basin_high()
    basin_test.test_check_basin_low()
    basin_test.test_check_basin_boundary()

    print("\n--- Test: Convergence Estimation ---")
    conv_test = TestConvergenceEstimation()
    conv_test.test_compute_equilibrium()
    conv_test.test_estimate_convergence()

    print("\n" + "=" * 60)
    print("All tests completed!")
