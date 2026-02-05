"""
Model Inference Tool - Free/low-cost LLM access for agents.

Supports multiple providers:
- Hugging Face Inference Providers (free tier, OpenAI-compatible)
- Google Gemini Flash (free tier)
- Ollama (local, free)

Uses ngrok.ai for routing, failover, and cost optimization.
Agents can call models for reasoning, generation, or analysis.

Usage tracked in EISV (Energy consumption) for self-regulation.
"""

from typing import Dict, Any, Sequence, Optional
from mcp.types import TextContent
import os

from .utils import success_response, error_response, require_argument
from .decorators import mcp_tool
from src.logging_utils import get_logger

logger = get_logger(__name__)

# Check if OpenAI SDK available (used for ngrok.ai compatibility)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


@mcp_tool("call_model", timeout=30.0)
async def handle_call_model(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Call a free/low-cost LLM for reasoning, generation, or analysis.
    
    Models available:
    - gemini-flash (free, fast) - default
    - llama-3.1-8b (via Ollama, free) - if local available
    - gemini-pro (low-cost) - if free tier exhausted
    
    Routing via ngrok.ai:
    - Automatic failover (gemini → ollama → gemini-pro)
    - Cost optimization (route to cheapest available)
    - Rate limit handling (distribute across providers)
    
    Usage tracked in EISV (Energy consumption):
    - Model calls consume Energy
    - High usage → higher Energy → agent learns efficiency
    - Natural self-regulation
    
    Example:
    {
      "prompt": "Analyze this code for potential bugs",
      "model": "gemini-flash",
      "task_type": "analysis",
      "max_tokens": 500
    }
    """
    if not OPENAI_AVAILABLE:
        return [error_response(
            "OpenAI SDK required for model inference. Install with: pip install openai",
            error_code="DEPENDENCY_MISSING",
            error_category="system_error",
            recovery={
                "action": "Install OpenAI SDK",
                "related_tools": ["health_check"],
                "workflow": [
                    "1. Install: pip install openai",
                    "2. Restart MCP server",
                    "3. Retry call_model tool"
                ]
            }
        )]
    
    # Validate required parameter
    prompt, error = require_argument(arguments, "prompt")
    if error:
        return [error]
    
    # Get optional parameters
    model = arguments.get("model", "auto")  # auto, hf, gemini-flash, llama-3.1-8b, etc.
    task_type = arguments.get("task_type", "reasoning")  # reasoning, generation, analysis
    max_tokens = int(arguments.get("max_tokens", 500))  # Must be int for Ollama
    temperature = float(arguments.get("temperature", 0.7))
    privacy = arguments.get("privacy", "auto")  # auto, local, cloud
    provider = arguments.get("provider", "auto")  # auto, hf, gemini, ollama
    
    # Privacy routing: Force local if requested
    if privacy == "local" or provider == "ollama":
        # Route to Ollama (local)
        base_url = "http://localhost:11434/v1"  # Ollama OpenAI-compatible API
        # Use specified model or default to llama3 (common Ollama model)
        if model == "auto" or model == "llama-3.1-8b":
            model = "llama3:70b"  # Default Ollama model (adjust based on what's installed)
        api_key = "ollama"  # Dummy key - Ollama ignores it but OpenAI SDK requires non-None
        provider = "ollama"
        logger.info(f"Privacy mode: local - routing to Ollama with model {model}")
    elif provider == "hf" or (provider == "auto" and (model.startswith("deepseek-ai/") or model.startswith("openai/gpt-oss") or model.startswith("hf:"))):
        # Hugging Face Inference Providers (free tier, OpenAI-compatible)
        base_url = "https://router.huggingface.co/v1"
        api_key = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
        if not api_key:
            return [error_response(
                "HF_TOKEN or HUGGINGFACE_TOKEN required for Hugging Face Inference Providers",
                error_code="MISSING_CONFIG",
                error_category="system_error",
                recovery={
                    "action": "Set HF_TOKEN environment variable (get free token from https://huggingface.co/settings/tokens)",
                    "related_tools": ["health_check"],
                    "workflow": [
                        "1. Get free token: https://huggingface.co/settings/tokens",
                        "2. Set: export HF_TOKEN=your_token",
                        "3. Restart MCP server",
                        "4. Retry call_model tool"
                    ]
                }
            )]
        # Clean model name (remove hf: prefix if present)
        if model.startswith("hf:"):
            model = model[3:]
        # Default model if auto
        if model == "auto":
            model = "deepseek-ai/DeepSeek-R1:fastest"  # Default HF model
        # Use HF model with :fastest or :cheapest suffix for auto-selection (if not already present)
        elif ":" not in model:
            model = f"{model}:fastest"  # Auto-select fastest provider
        logger.info(f"Using Hugging Face Inference Providers: {model}")
    elif provider == "gemini" or (provider == "auto" and model.startswith("gemini")):
        # Google Gemini (free tier)
        base_url = os.getenv("NGROK_AI_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta")
        api_key = os.getenv("GOOGLE_AI_API_KEY") or os.getenv("NGROK_API_KEY")
        if not api_key:
            return [error_response(
                "GOOGLE_AI_API_KEY or NGROK_API_KEY required for Gemini",
                error_code="MISSING_CONFIG",
                error_category="system_error",
                recovery={
                    "action": "Set GOOGLE_AI_API_KEY (get from https://aistudio.google.com/app/apikey)",
                    "related_tools": ["health_check"],
                    "workflow": [
                        "1. Get free API key: https://aistudio.google.com/app/apikey",
                        "2. Set: export GOOGLE_AI_API_KEY=your_key",
                        "3. Restart MCP server",
                        "4. Retry call_model tool"
                    ]
                }
            )]
        if model == "auto":
            model = "gemini-flash"
        logger.info(f"Using Google Gemini: {model}")
    elif provider == "auto":
        # Auto-select: Try Ollama first (local, free), then Gemini, then HF
        # Check if Ollama is available
        ollama_available = False
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(('localhost', 11434))
            sock.close()
            ollama_available = (result == 0)
        except Exception:
            pass

        if ollama_available:
            # Prefer Ollama (local, free, no token needed)
            base_url = "http://localhost:11434/v1"
            api_key = "ollama"
            model = os.getenv("UNITARES_LLM_MODEL", "gemma3:27b") if model == "auto" else model
            provider = "ollama"
            logger.info(f"Auto-selected Ollama (local): {model}")
        else:
            # Fallback to Gemini or HF
            google_key = os.getenv("GOOGLE_AI_API_KEY") or os.getenv("NGROK_API_KEY")
            hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")

            if google_key:
                base_url = os.getenv("NGROK_AI_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta")
                api_key = google_key
                model = "gemini-flash" if model == "auto" else model
                provider = "gemini"
                logger.info(f"Auto-selected Google Gemini: {model}")
            elif hf_token:
                base_url = "https://router.huggingface.co/v1"
                api_key = hf_token
                model = "deepseek-ai/DeepSeek-R1:fastest" if model == "auto" else model
                if ":" not in model and not model.startswith("deepseek-ai/") and not model.startswith("openai/gpt-oss"):
                    model = f"{model}:fastest"
                provider = "hf"
                logger.info(f"Auto-selected Hugging Face: {model}")
            else:
                return [error_response(
                    "No provider available. Ollama not running and no cloud API keys configured.",
                    error_code="MISSING_CONFIG",
                    error_category="system_error",
                    recovery={
                        "action": "Start Ollama (recommended) or configure cloud API keys",
                        "related_tools": ["health_check"],
                        "workflow": [
                            "1. Install & run Ollama: ollama serve (recommended - free, local)",
                            "2. Or get Google key: https://aistudio.google.com/app/apikey",
                            "3. Or get HF token: https://huggingface.co/settings/tokens",
                            "4. Retry call_model tool"
                        ]
                    }
                )]
    else:
        # Default: ngrok.ai gateway or OpenAI-compatible endpoint
        base_url = os.getenv("NGROK_AI_ENDPOINT", "https://api.openai.com/v1")
        api_key = os.getenv("NGROK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return [error_response(
                "NGROK_API_KEY or OPENAI_API_KEY required for model inference",
                error_code="MISSING_CONFIG",
                error_category="system_error",
                recovery={
                    "action": "Set NGROK_API_KEY or OPENAI_API_KEY environment variable",
                    "related_tools": ["health_check", "get_connection_status"],
                    "workflow": [
                        "1. Set environment variable: export NGROK_API_KEY=your_key",
                        "2. Or set: export OPENAI_API_KEY=your_key",
                        "3. Restart MCP server",
                        "4. Retry call_model tool"
                    ]
                }
            )]
        if model == "auto":
            model = "gemini-flash"  # Default to free tier
        logger.info(f"Using ngrok.ai gateway or OpenAI-compatible endpoint: {model}")
    
    try:
        client = OpenAI(base_url=base_url, api_key=api_key)
        
        # Call model via ngrok.ai (or direct if not using gateway)
        logger.debug(f"Calling model '{model}' via {base_url} for task_type='{task_type}'")
        
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        result_text = response.choices[0].message.content
        tokens_used = response.usage.total_tokens if hasattr(response, 'usage') else 0
        model_used = getattr(response, 'model', model)
        
        # Estimate Energy cost (simple: +0.01 per call, can refine later based on tokens)
        # Free models (gemini-flash, llama-3.1-8b): minimal cost
        # Low-cost models (gemini-pro): slightly higher
        if "flash" in model.lower() or "llama" in model.lower():
            energy_cost = 0.01  # Free tier
        elif "pro" in model.lower():
            energy_cost = 0.02  # Low-cost tier
        else:
            energy_cost = 0.03  # Default estimate
        
        # Track usage and update Energy in governance monitor
        logger.info(f"Model inference: model={model_used}, tokens={tokens_used}, energy_cost={energy_cost}")
        
        # Update Energy in governance monitor (if agent_id available)
        agent_id = arguments.get("agent_id")
        if agent_id:
            try:
                from .shared import get_mcp_server
                mcp_server = get_mcp_server()
                monitor = mcp_server.get_or_create_monitor(agent_id)
                
                # Update Energy through a lightweight process_update
                # Model inference consumes Energy - reflect this in EISV dynamics
                # Use low complexity (0.1-0.2) since inference is a tool, not core work
                # The energy_cost affects how much Energy is consumed
                inference_complexity = min(0.1 + energy_cost * 2, 0.3)  # Scale energy_cost to complexity
                
                # Create a lightweight update that reflects model inference usage
                # This flows through normal EISV dynamics, updating Energy appropriately
                monitor.process_update({
                    "response_text": f"Model inference: {task_type} via {model_used} ({tokens_used} tokens)",
                    "complexity": inference_complexity,
                    "confidence": 0.8  # Model inference is generally reliable
                })
                
                logger.debug(f"Updated Energy for agent {agent_id}: model inference tracked (cost={energy_cost}, complexity={inference_complexity})")
            except Exception as e:
                # Non-critical: if Energy tracking fails, still return the inference result
                logger.warning(f"Could not update Energy for model inference: {e}")
        else:
            logger.debug("No agent_id available for Energy tracking (model inference still successful)")
        
        # Determine routing method
        if "router.huggingface.co" in base_url:
            routed_via = "huggingface"
        elif "localhost" in base_url or "127.0.0.1" in base_url:
            routed_via = "ollama"
        elif "ngrok" in base_url.lower():
            routed_via = "ngrok.ai"
        elif "generativelanguage.googleapis.com" in base_url:
            routed_via = "gemini-direct"
        else:
            routed_via = "direct"
        
        return success_response({
            "success": True,
            "response": result_text,
            "model_used": model_used,
            "tokens_used": tokens_used,
            "energy_cost": energy_cost,
            "routed_via": routed_via,
            "task_type": task_type,
            "message": f"Model inference completed via {routed_via}"
        }, agent_id=arguments.get("agent_id"), arguments=arguments)
        
    except Exception as e:
        logger.error(f"Model inference failed: {e}", exc_info=True)
        
        # Provide helpful error message
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            error_code = "TIMEOUT"
            recovery_hint = "Try a shorter prompt or increase timeout"
        elif "rate limit" in error_msg.lower():
            error_code = "RATE_LIMIT_EXCEEDED"
            recovery_hint = "Wait a moment and retry, or use a different model"
        elif "not found" in error_msg.lower() or "invalid" in error_msg.lower():
            error_code = "MODEL_NOT_AVAILABLE"
            recovery_hint = f"Model '{model}' not available. Try 'gemini-flash' or 'llama-3.1-8b'"
        else:
            error_code = "INFERENCE_ERROR"
            recovery_hint = "Check ngrok.ai configuration and model availability"
        
        return [error_response(
            f"Model inference failed: {error_msg}",
            error_code=error_code,
            error_category="system_error",
            details={
                "model_requested": model,
                "base_url": base_url,
                "task_type": task_type
            },
            recovery={
                "action": recovery_hint,
                "related_tools": ["health_check", "get_connection_status"],
                "workflow": [
                    "1. Check ngrok.ai configuration (if using gateway)",
                    "2. Verify model is available",
                    "3. Try a different model (gemini-flash, llama-3.1-8b)",
                    "4. Check server logs for details"
                ]
            }
        )]


def create_model_inference_client():
    """Factory function to create model inference client if available."""
    if not OPENAI_AVAILABLE:
        return None
    
    from openai import OpenAI
    
    base_url = os.getenv("NGROK_AI_ENDPOINT", "https://api.openai.com/v1")
    api_key = os.getenv("NGROK_API_KEY") or os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        return None
    
    try:
        return OpenAI(base_url=base_url, api_key=api_key)
    except Exception as e:
        logger.warning(f"Could not create model inference client: {e}")
        return None

