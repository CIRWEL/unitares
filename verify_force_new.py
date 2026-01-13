
import asyncio
import sys
import json
import httpx
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession

# Configuration
URL = "http://localhost:8765/mcp/"
USER_AGENT = "ForceNewTester/1.0"

async def main():
    headers = {"User-Agent": USER_AGENT}
    print(f"Connecting to {URL} with User-Agent: {USER_AGENT}...")
    
    async with httpx.AsyncClient(http2=True, headers=headers) as http_client:
        async with streamable_http_client(URL, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # 1. Establish Identity
                print("\n=== 1. Initial Onboard ===")
                res1 = await session.call_tool("onboard", {{}})
                data1 = None
                for content in res1.content:
                    print(content.text)
                    data1 = json.loads(content.text)
                
                uuid1 = data1.get("uuid")
                print(f"UUID 1: {uuid1}")

                # 2. Force New Identity
                print("\n=== 2. Force New Onboard ===")
                res2 = await session.call_tool("onboard", {{"force_new": True}})
                data2 = None
                for content in res2.content:
                    print(content.text)
                    data2 = json.loads(content.text)
                
                uuid2 = data2.get("uuid")
                print(f"UUID 2: {uuid2}")

                # 3. Verification
                if uuid1 != uuid2 and data2.get("is_new"):
                    print("\n✅ SUCCESS: force_new=true generated a fresh UUID.")
                else:
                    print("\n❌ FAILURE: UUID did not change or is_new is false.")
                    print(f"UUID1: {uuid1}")
                    print(f"UUID2: {uuid2}")

if __name__ == "__main__":
    asyncio.run(main())
