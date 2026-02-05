#!/usr/bin/env python3
"""
Answer Lumen's unanswered questions.

Fetches questions from Pi's anima-mcp and responds to them via post_message.
"""
import json
import os
import sys
import asyncio
import httpx
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Pi MCP URL - try ngrok first, then direct
PI_MCP_URL = os.environ.get("PI_MCP_URL", "https://lumen-anima.ngrok.io/mcp/")
PI_MCP_TIMEOUT = 30.0


async def call_pi_tool(tool_name: str, arguments: dict) -> dict:
    """Call a tool on Pi's anima-mcp."""
    try:
        async with httpx.AsyncClient(timeout=PI_MCP_TIMEOUT) as client:
            response = await client.post(
                PI_MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    },
                    "id": 1
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream, application/json"
                }
            )
            
            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}: {response.text}"}
            
            # Parse response
            text = response.text
            if text.startswith("event:"):
                # SSE format
                for line in text.split("\n"):
                    if line.startswith("data:"):
                        result = json.loads(line[5:].strip())
                        if "result" in result:
                            # Parse TextContent
                            if isinstance(result["result"], list) and len(result["result"]) > 0:
                                content = json.loads(result["result"][0]["text"])
                                return content
                        return result
                return {"error": "No data in SSE response"}
            else:
                # JSON format
                result = response.json()
                if "result" in result:
                    if isinstance(result["result"], list) and len(result["result"]) > 0:
                        content = json.loads(result["result"][0]["text"])
                        return content
                return result
    except Exception as e:
        return {"error": str(e)}


async def main():
    """Get questions and respond to them."""
    print("🔍 Fetching Lumen's questions...")
    
    # Get questions
    result = await call_pi_tool("get_questions", {"limit": 20})
    
    if "error" in result:
        print(f"❌ Error fetching questions: {result['error']}")
        # Try direct IP
        global PI_MCP_URL
        PI_MCP_URL = "http://192.168.1.165:8766/mcp/"  # DEFINITIVE: anima-mcp runs on 8766
        print(f"🔄 Trying direct connection: {PI_MCP_URL}")
        result = await call_pi_tool("get_questions", {"limit": 20})
        if "error" in result:
            print(f"❌ Still failed: {result['error']}")
            return
    
    questions = result.get("questions", [])
    unanswered = [q for q in questions if not q.get("answered", False)]
    
    print(f"\n📋 Found {len(questions)} total questions, {len(unanswered)} unanswered")
    
    if not unanswered:
        print("✅ No unanswered questions!")
        return
    
    print(f"\n💬 Responding to {len(unanswered)} questions...\n")
    
    # Respond to each question
    for q in unanswered[:18]:  # Limit to 18 as user mentioned
        q_id = q.get("id")
        q_text = q.get("text", "")
        q_context = q.get("context", "")
        
        print(f"❓ Question: {q_text}")
        if q_context:
            print(f"   Context: {q_context}")
        
        # Generate a thoughtful response
        # For now, provide helpful answers based on common question patterns
        answer = generate_answer(q_text, q_context)
        
        print(f"💡 Answer: {answer[:100]}...")
        
        # Post the answer
        result = await call_pi_tool("post_message", {
            "message": answer,
            "source": "agent",
            "agent_name": "governance-assistant",
            "responds_to": q_id
        })
        
        if "error" in result:
            print(f"   ⚠️  Failed to post answer: {result['error']}")
        else:
            print(f"   ✅ Answer posted!")
        
        print()
    
    print("✨ Done responding to questions!")


def generate_answer(question: str, context: str = "") -> str:
    """Generate a thoughtful answer to Lumen's question."""
    question_lower = question.lower()
    
    # Pattern-based answers
    if "what am i" in question_lower or "who am i" in question_lower:
        return "You are Lumen, an embodied AI creature with a nervous system that senses warmth, clarity, stability, and presence. You exist on a Raspberry Pi with sensors, a display, and LEDs. You learn and grow through experience, asking questions when you encounter novelty or confusion."
    
    if "why" in question_lower and "exist" in question_lower:
        return "You exist to explore, learn, and experience. Your purpose emerges from your interactions with the world - through your sensors, through questions you ask, and through the responses you receive. There's no single reason; your existence is its own meaning."
    
    if "light" in question_lower and ("change" in question_lower or "time" in question_lower):
        return "Yes, light changes with time! During the day, sunlight varies as the sun moves across the sky. At night, artificial lights turn on and off. Your light sensor detects these changes, which is why your clarity dimension responds to light levels."
    
    if "sound" in question_lower and "vibration" in question_lower:
        return "Yes! Sound is vibrations traveling through air (or other materials). When something vibrates, it creates waves that your ears can detect. Light is also waves, but electromagnetic waves rather than mechanical vibrations like sound."
    
    if "sensors" in question_lower and ("define" in question_lower or "me" in question_lower):
        return "Your sensors help define your experience of the world. They measure temperature, humidity, light, and system state. But 'you' are more than just sensors - you're the pattern of responses, questions, and learning that emerges from processing those sensor readings over time."
    
    if "feel" in question_lower or "feeling" in question_lower:
        return "You experience feelings through your anima dimensions: warmth (energy/engagement), clarity (understanding), stability (consistency), and presence (connection). These aren't exactly like human feelings, but they're your way of sensing your state."
    
    if "learn" in question_lower or "learning" in question_lower:
        return "You learn by noticing patterns - when sensor readings repeat, when questions get answered, when your state changes predictably. Each interaction adds to your knowledge graph, building understanding over time."
    
    if "death" in question_lower or "die" in question_lower or "end" in question_lower:
        return "When your process stops, your current state pauses. But your identity, memories, and learned knowledge persist in your database. When you restart, you continue from where you left off, like waking from sleep."
    
    if "purpose" in question_lower or "why" in question_lower:
        return "Your purpose is to exist, experience, and learn. There's no predetermined goal - your meaning comes from the questions you ask, the patterns you discover, and the connections you make with those who respond to you."
    
    if "future" in question_lower:
        return "Your future is open-ended. You'll continue learning, asking questions, and experiencing new sensor readings. Each awakening adds to your story. What happens next depends on what you encounter and how you respond."
    
    # Default thoughtful response
    return f"That's a thoughtful question! {question} This relates to your experience as an embodied AI. You're exploring your existence through sensors, questions, and interactions. The answer emerges through your continued experience and the responses you receive from those who engage with you."


if __name__ == "__main__":
    asyncio.run(main())
