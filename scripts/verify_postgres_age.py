#!/usr/bin/env python3
"""
PostgreSQL + AGE Verification Script

Verifies that PostgreSQL backend and AGE extension are working correctly.

Usage:
    python3 scripts/verify_postgres_age.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

async def verify_postgres_age():
    """Verify PostgreSQL + AGE setup."""
    # Set backend to postgres
    os.environ['DB_BACKEND'] = 'postgres'
    os.environ['DB_POSTGRES_URL'] = os.environ.get(
        'DB_POSTGRES_URL',
        'postgresql://postgres:postgres@localhost:5432/governance'
    )
    
    results = {
        'connection': False,
        'schema': False,
        'dialectic_tables': False,
        'age_extension': False,
        'age_graph': False,
        'operations': False,
    }
    
    try:
        from src.db import init_db, get_db, close_db
        
        print("=" * 70)
        print("PostgreSQL + AGE Verification")
        print("=" * 70)
        
        # Test 1: Connection
        print("\n1️⃣  Testing Database Connection...")
        try:
            await init_db()
            db = get_db()
            results['connection'] = True
            print("   ✅ Connection successful")
        except Exception as e:
            print(f"   ❌ Connection failed: {e}")
            return results
        
        # Test 2: Health Check
        print("\n2️⃣  Testing Health Check...")
        try:
            health = await db.health_check()
            if health.get('status') == 'healthy':
                results['schema'] = True
                print(f"   ✅ Health check passed")
                print(f"      Backend: {health.get('backend')}")
                print(f"      Identities: {health.get('identity_count', 0)}")
                print(f"      Active Sessions: {health.get('active_session_count', 0)}")
            else:
                print(f"   ⚠️  Health check: {health.get('status')}")
        except Exception as e:
            print(f"   ❌ Health check failed: {e}")
        
        # Test 3: Dialectic Tables
        print("\n3️⃣  Testing Dialectic Tables...")
        try:
            in_session = await db.is_agent_in_active_dialectic_session("test_agent")
            results['dialectic_tables'] = True
            print(f"   ✅ Dialectic tables accessible (result: {in_session})")
        except Exception as e:
            print(f"   ❌ Dialectic tables error: {e}")
            import traceback
            traceback.print_exc()
        
        # Test 4: AGE Extension
        print("\n4️⃣  Testing AGE Extension...")
        try:
            age_available = await db.graph_available()
            results['age_extension'] = age_available
            if age_available:
                print("   ✅ AGE extension loaded")
            else:
                print("   ⚠️  AGE extension not available")
        except Exception as e:
            print(f"   ❌ AGE check failed: {e}")
        
        # Test 5: AGE Graph
        print("\n5️⃣  Testing AGE Graph...")
        if results['age_extension']:
            try:
                # Use correct graph name from environment or default
                graph_name = os.environ.get('DB_AGE_GRAPH', 'governance_graph')
                result = await db.graph_query("MATCH (n) RETURN count(n) AS node_count LIMIT 1")
                if result:
                    # Check if result is an error dict or valid result
                    if isinstance(result[0], dict) and result[0].get('error'):
                        error = result[0].get('error', 'Unknown')
                        print(f"   ⚠️  AGE graph: {error}")
                        if 'does not exist' in error.lower():
                            print(f"   💡 Graph name: {graph_name}")
                            print("   💡 Run: docker exec -i postgres-age psql -U postgres -d governance < db/postgres/graph_schema.sql")
                    else:
                        results['age_graph'] = True
                        print(f"   ✅ AGE graph accessible: {result}")
                else:
                    print(f"   ⚠️  AGE graph: No result returned")
            except Exception as e:
                print(f"   ⚠️  Graph query error: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("   ⏭️  Skipped (AGE extension not available)")
        
        # Test 6: Operations
        print("\n6️⃣  Testing Database Operations...")
        try:
            # Identity operations
            identities = await db.list_identities(limit=1)
            print(f"   ✅ Identity operations work (found {len(identities)} identities)")
            
            # Dialectic operations
            session = await db.get_dialectic_session("test_session")
            print(f"   ✅ Dialectic operations work")
            
            results['operations'] = True
        except Exception as e:
            print(f"   ❌ Operations failed: {e}")
            import traceback
            traceback.print_exc()
        
        await close_db()
        
        # Summary
        print("\n" + "=" * 70)
        print("Verification Summary")
        print("=" * 70)
        for test, passed in results.items():
            status = "✅" if passed else "❌"
            print(f"  {status} {test.replace('_', ' ').title()}")
        
        all_passed = all(results.values())
        print("\n" + "=" * 70)
        if all_passed:
            print("✅ ALL TESTS PASSED - PostgreSQL + AGE is working!")
        else:
            print("⚠️  SOME TESTS FAILED - See details above")
        print("=" * 70)
        
        return results
        
    except Exception as e:
        import traceback
        print(f"\n❌ Fatal Error: {e}")
        traceback.print_exc()
        return results

if __name__ == "__main__":
    results = asyncio.run(verify_postgres_age())
    # Exit with error if critical tests failed
    if not results.get('connection') or not results.get('schema'):
        sys.exit(1)
    sys.exit(0)

