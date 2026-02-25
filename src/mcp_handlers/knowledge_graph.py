"""
Knowledge Graph MCP Handlers

Fast, indexed, non-blocking knowledge operations using knowledge graph.
Replaces deprecated file-based knowledge layer.

Performance:
- store_knowledge: ~0.01ms (vs 350ms file-based) - 35,000x faster
- search_knowledge: O(indexes) not O(n) - scales logarithmically
- find_similar: Tag-based overlap - no brute force scanning

Claude Desktop compatible: All operations are async and non-blocking.
"""

from typing import Dict, Any, Sequence, Optional
from mcp.types import TextContent
from datetime import datetime
import time
from .utils import success_response, error_response, require_argument, require_agent_id, require_registered_agent
from .decorators import mcp_tool
from .validators import validate_discovery_type, validate_severity, validate_discovery_status, validate_response_type, validate_discovery_id, apply_param_aliases
from .shared import get_mcp_server
from src.knowledge_graph import get_knowledge_graph, DiscoveryNode, ResponseTo
from config.governance_config import config
from src.logging_utils import get_logger
from src.perf_monitor import record_ms
from .llm_delegation import synthesize_results

logger = get_logger(__name__)

import re

def normalize_tag(tag: str) -> str:
    """Normalize a tag to canonical form: lowercase, strip, collapse separators to hyphens.

    Examples:
        "EISV" → "eisv"
        "bug_fix" → "bug-fix"
        "  Bug Fix  " → "bug-fix"
        "eisv-dynamics" → "eisv-dynamics" (unchanged)
        "eisv_dynamics" → "eisv-dynamics"
    """
    t = tag.strip().lower()
    # Replace underscores and spaces with hyphens
    t = re.sub(r'[\s_]+', '-', t)
    # Collapse multiple hyphens
    t = re.sub(r'-{2,}', '-', t)
    # Strip leading/trailing hyphens
    t = t.strip('-')
    return t


def normalize_tags(tags: list) -> list:
    """Normalize and deduplicate a list of tags."""
    seen = set()
    result = []
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            continue
        normalized = normalize_tag(tag)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


async def _discovery_not_found(discovery_id: str, graph) -> TextContent:
    """Build a 'not found' error with prefix-match suggestions.

    LLMs sometimes truncate ISO-timestamp discovery IDs (e.g. '2025-12-20T15:43:51' → '2025').
    When an exact match fails, search for IDs that start with the given prefix and offer
    suggestions so the agent can retry with the correct full ID.
    """
    suggestions = []
    try:
        db = await graph._get_db()
        cypher = f"""
            MATCH (d:Discovery)
            WHERE d.id STARTS WITH ${{prefix}}
            RETURN d.id
            LIMIT 5
        """
        rows = await db.graph_query(cypher, {"prefix": discovery_id})
        for row in rows:
            if isinstance(row, dict) and "d.id" in row:
                suggestions.append(row["d.id"])
            elif isinstance(row, str):
                suggestions.append(row)
    except Exception:
        pass  # Best-effort suggestions

    if suggestions:
        return error_response(
            f"Discovery '{discovery_id}' not found. Did you mean one of these?",
            recovery={
                "matching_ids": suggestions,
                "action": "Retry with the full discovery_id from the list above",
                "hint": "Discovery IDs are ISO timestamps (e.g. '2025-12-20T15:43:51.020454'). "
                        "Pass the complete ID, not just the year.",
            }
        )
    return error_response(f"Discovery '{discovery_id}' not found")


def _check_display_name_required(agent_id: str, arguments: Dict[str, Any]) -> tuple[Optional[TextContent], Optional[str]]:
    """
    Check if agent has a meaningful display_name set for KG attribution.

    UX FIX (Feb 2026): Auto-generate display_name instead of blocking.
    If no meaningful display_name is set, auto-generates one and returns a warning.
    This allows agents to contribute to KG immediately without the name-setting ritual.

    Returns:
        Tuple of (error_if_any, warning_message_if_generated)
        - (None, None) if display_name is set and meaningful
        - (None, "warning message") if display_name was auto-generated
        - Error only returned for critical failures (rare)
    """
    try:
        from .shared import get_mcp_server
        from .context import get_context_agent_id
        import uuid as uuid_module

        mcp_server = get_mcp_server()

        # Get the actual UUID for this agent
        bound_uuid = get_context_agent_id()

        # Check if display_name is set in metadata
        meta = None
        if bound_uuid and bound_uuid in mcp_server.agent_metadata:
            meta = mcp_server.agent_metadata[bound_uuid]
        elif agent_id in mcp_server.agent_metadata:
            meta = mcp_server.agent_metadata[agent_id]

        if meta:
            display_name = getattr(meta, 'display_name', None) or getattr(meta, 'label', None)

            # Check if display_name is meaningful (not just a UUID or auto-generated)
            if display_name:
                # Skip check if it looks like a real name (not UUID pattern)
                is_uuid_pattern = False
                try:
                    uuid_module.UUID(display_name, version=4)
                    is_uuid_pattern = True
                except (ValueError, AttributeError):
                    pass

                # Also check for auto-generated patterns like "auto_20251229_abc123"
                is_auto_pattern = display_name.startswith("auto_") or display_name.startswith("Agent_")

                if not is_uuid_pattern and not is_auto_pattern:
                    return None, None  # Has a real display_name, OK to proceed

        # No meaningful display_name - auto-generate instead of blocking
        # UX FIX (Feb 2026): Don't block first contribution, just warn
        auto_name = f"Agent_{(bound_uuid or agent_id)[:8]}"

        # Try to set the auto-generated name in metadata
        if meta and bound_uuid:
            try:
                meta.label = auto_name
                meta.display_name = auto_name
            except Exception as e:
                logger.debug(f"Could not save auto-generated display_name: {e}")

        warning = (
            f"KG entry attributed to '{auto_name}' (auto-generated). "
            f"Call identity(name='YourName') to set a personalized name."
        )
        return None, warning

    except Exception as e:
        logger.debug(f"Could not check display_name: {e}")
        return None, None  # Don't block on check failures


def _resolve_agent_display(agent_id: str) -> Dict[str, str]:
    """
    Resolve agent_id to display info (v2.5.4).

    Returns dict with agent_id, display_name for human-readable output.
    UUID is never exposed - kept internal for session binding only.

    Args:
        agent_id: Either model+date format (new) or UUID (legacy lookups)
    """
    try:
        mcp_server = get_mcp_server()
        # Try direct lookup (if agent_id is actually a UUID in legacy data)
        if agent_id in mcp_server.agent_metadata:
            meta = mcp_server.agent_metadata[agent_id]
            structured_id = getattr(meta, 'structured_id', None) or agent_id
            display_name = (
                getattr(meta, 'display_name', None) or
                getattr(meta, 'label', None) or
                structured_id
            )
            return {"agent_id": structured_id, "display_name": display_name}

        # Search by structured_id or label
        for uuid_key, meta in mcp_server.agent_metadata.items():
            if getattr(meta, 'structured_id', None) == agent_id or getattr(meta, 'label', None) == agent_id:
                display_name = (
                    getattr(meta, 'display_name', None) or
                    getattr(meta, 'label', None) or
                    agent_id
                )
                return {"agent_id": agent_id, "display_name": display_name}
    except Exception:
        pass
    # Fallback: use agent_id as-is
    return {"agent_id": agent_id, "display_name": agent_id}


@mcp_tool("store_knowledge_graph", timeout=20.0, register=False)
async def handle_store_knowledge_graph(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Store knowledge discovery/discoveries in graph - fast, non-blocking, transparent

    Accepts either:
    - Single discovery: discovery_type, summary, details, tags, etc.
    - Batch discoveries: discoveries array (max 10 per batch)
    """
    # MAGNET PATTERN: Accept fuzzy inputs (discovery, insight, finding → summary)
    arguments = apply_param_aliases("store_knowledge_graph", arguments)

    # REDUCE FRICTION (Dec 2025): Allow unregistered agents to write low/medium notes
    # Only enforce strict registration and display name for high/critical severity (security)
    # UX FIX (Feb 2026): Auto-generate display_name instead of blocking
    raw_severity = str(arguments.get("severity", "low")).lower()
    display_name_warning = None  # Track if we auto-generated a name

    if raw_severity in ["high", "critical"]:
        agent_id, error = require_registered_agent(arguments)
        if not error:
            # Check display_name (auto-generates if missing, returns warning)
            display_name_error, display_name_warning = _check_display_name_required(agent_id, arguments)
            if display_name_error:
                return [display_name_error]
    else:
        agent_id, error = require_agent_id(arguments)

    if error:
        return [error]

    # CIRCUIT BREAKER: Paused agents cannot store knowledge
    from .utils import check_agent_can_operate
    blocked = check_agent_can_operate(agent_id)
    if blocked:
        return [blocked]

    # Check if batch mode (discoveries array provided)
    if "discoveries" in arguments and arguments["discoveries"] is not None:
        # Batch mode - delegate to batch handler logic
        return await _handle_store_knowledge_graph_batch(arguments, agent_id)
    
    # Set tool name in context for better error messages
    arguments["_tool_name"] = "store_knowledge_graph"
    
    # Single discovery mode (original behavior)
    # LITE-FIRST: discovery_type defaults to "note" (simplest form)
    discovery_type = arguments.get("discovery_type", "note")
    
    # Validate discovery_type enum
    discovery_type, error = validate_discovery_type(discovery_type)
    if error:
        return [error]
    
    summary, error = require_argument(arguments, "summary",
                                    "summary is required - what did you discover/learn?")
    if error:
        return [error]
    
    try:
        # SECURITY: Rate limiting is handled by the knowledge graph backend
        # Backend handles rate limiting internally (O(1) per store)
        # No need for inefficient O(n) query here - let graph handle it
        graph = await get_knowledge_graph()
        
        # Truncate fields to prevent context overflow
        # Summary: concise but complete thoughts (1000 chars ≈ 160 words)
        # Details: substantive content, allow more space (5000 chars ≈ 800 words)
        MAX_SUMMARY_LEN = 1000
        MAX_DETAILS_LEN = 5000

        raw_summary = summary
        # Accept both 'details' and 'content' as parameter names
        raw_details = arguments.get("details") or arguments.get("content") or ""

        # Track truncation for visibility (v2.5.0+)
        truncation_info = {}

        if len(raw_summary) > MAX_SUMMARY_LEN:
            truncation_info["summary"] = f"Truncated from {len(raw_summary)} to {MAX_SUMMARY_LEN} chars"
            # Try to cut at sentence boundary, else word boundary
            truncated = raw_summary[:MAX_SUMMARY_LEN]
            # Look for last sentence end in final 100 chars
            for end_char in ['. ', '! ', '? ']:
                last_end = truncated.rfind(end_char, MAX_SUMMARY_LEN - 100)
                if last_end > 0:
                    truncated = truncated[:last_end + 1]
                    break
            else:
                # No sentence boundary, cut at word
                last_space = truncated.rfind(' ')
                if last_space > MAX_SUMMARY_LEN - 50:
                    truncated = truncated[:last_space]
            summary = truncated.rstrip() + "..."

        if len(raw_details) > MAX_DETAILS_LEN:
            truncation_info["details"] = f"Truncated from {len(raw_details)} to {MAX_DETAILS_LEN} chars"
            raw_details = raw_details[:MAX_DETAILS_LEN] + "... [truncated]"
        
        # Create discovery node
        discovery_id = datetime.now().isoformat()
        
        # Parse response_to if provided (typed response to parent discovery)
        response_to = None
        if "response_to" in arguments and arguments["response_to"]:
            resp_data = arguments["response_to"]
            if isinstance(resp_data, dict) and "discovery_id" in resp_data and "response_type" in resp_data:
                # Validate discovery_id format
                parent_id, error = validate_discovery_id(resp_data["discovery_id"])
                if error:
                    return [error]
                
                # Validate response_type enum
                response_type, error = validate_response_type(resp_data["response_type"])
                if error:
                    return [error]
                
                from src.knowledge_graph import ResponseTo
                response_to = ResponseTo(
                    discovery_id=parent_id,
                    response_type=response_type
                )
        
        # Validate severity if provided
        severity = arguments.get("severity")
        if severity is not None:
            severity, error = validate_severity(severity)
            if error:
                return [error]
        
        # ENHANCED PROVENANCE: Capture agent state at creation time
        # Answers: "What was the agent's context when they made this discovery?"
        provenance = None
        provenance_chain = None
        try:
            from .shared import get_mcp_server
            from .identity_shared import _get_lineage  # Import lineage function

            mcp_server = get_mcp_server()
            if agent_id in mcp_server.agent_metadata:
                meta = mcp_server.agent_metadata[agent_id]

                # Get monitor state if available
                monitor_state = {}
                if agent_id in mcp_server.monitors:
                    monitor = mcp_server.monitors[agent_id]
                    state = monitor.state
                    monitor_state = {
                        "regime": state.regime,
                        "coherence": round(state.coherence, 6),
                        "energy": round(state.E, 6),  # E, I, S, V are uppercase
                        "entropy": round(state.S, 6),
                        "void_active": state.void_active,
                    }

                # CAPTURE BASIC PROVENANCE
                provenance = {
                    "agent_state": {
                        "status": meta.status,
                        "health": meta.health_status,
                        "total_updates": meta.total_updates,
                        **monitor_state
                    },
                    "captured_at": datetime.now().isoformat(),
                }

                # CAPTURE PROVENANCE CHAIN: Full lineage context
                try:
                    lineage = _get_lineage(agent_id)  # [oldest_ancestor, ..., parent, self]
                    if len(lineage) > 1:  # Has ancestors
                        provenance_chain = []
                        for ancestor_id in lineage[:-1]:  # Exclude self
                            ancestor_meta = mcp_server.agent_metadata.get(ancestor_id)
                            if ancestor_meta:
                                chain_entry = {
                                    "agent_id": ancestor_id,
                                    "relationship": "ancestor",
                                    "spawn_reason": ancestor_meta.spawn_reason,
                                    "created_at": ancestor_meta.created_at,
                                    "lineage_depth": len(provenance_chain)  # Distance from root
                                }
                                provenance_chain.append(chain_entry)

                        # Add immediate parent context
                        if meta.parent_agent_id:
                            parent_meta = mcp_server.agent_metadata.get(meta.parent_agent_id)
                            if parent_meta:
                                parent_entry = {
                                    "agent_id": meta.parent_agent_id,
                                    "relationship": "direct_parent",
                                    "spawn_reason": meta.spawn_reason,
                                    "created_at": parent_meta.created_at,
                                    "lineage_depth": len(provenance_chain)
                                }
                                provenance_chain.append(parent_entry)
                except Exception as lineage_error:
                    logger.debug(f"Could not capture provenance chain: {lineage_error}")
                    # Non-critical - continue without chain
        except Exception as e:
            logger.debug(f"Could not capture provenance: {e}")  # Non-critical
        
        discovery = DiscoveryNode(
            id=discovery_id,
            agent_id=agent_id,
            type=discovery_type,
            summary=summary,
            details=raw_details,
            tags=normalize_tags(arguments.get("tags", [])),
            severity=severity,
            status=arguments.get("status", "open"),
            response_to=response_to,
            references_files=arguments.get("related_files", []),
            provenance=provenance
        )

        # Find similar discoveries (fast with tag index) - DEFAULT: true for better linking
        similar_discoveries = []
        if arguments.get("auto_link_related", True):  # Default to true - new graph uses indexes (fast)
            similar = await graph.find_similar(discovery, limit=5)
            discovery.related_to = [s.id for s in similar]
            similar_discoveries = [s.to_dict(include_details=False) for s in similar]
        
        # SECURITY: Require session ownership for high-severity discoveries (UUID-based auth, Dec 2025)
        # This prevents unauthorized agents from storing critical security issues
        if discovery.severity in ["high", "critical"]:
            from .utils import verify_agent_ownership
            if not verify_agent_ownership(agent_id, arguments):
                return [error_response(
                    "Authentication required for high-severity discoveries.",
                    error_code="AUTH_REQUIRED",
                    error_category="auth_error",
                    recovery={
                        "action": "Ensure your session is bound to this agent",
                        "related_tools": ["identity"],
                        "workflow": "Identity auto-binds on first tool call. Use identity() to check binding."
                    }
                )]
        
        # HUMAN REVIEW FLAGGING: Flag high-severity discoveries for review
        requires_review = discovery.severity in ["high", "critical"]
        
        # Add to graph (fast, non-blocking)
        await graph.add_discovery(discovery)

        # v2.5.3: Resolve UUID to display name for human-readable output
        agent_display = arguments.get("_agent_display") or _resolve_agent_display(agent_id)
        display_name = agent_display.get("display_name", agent_id)

        response = {
            "message": f"Discovery stored for agent '{display_name}'",
            "discovery_id": discovery_id,
            "agent": agent_display,  # Include full display info
            "discovery": discovery.to_dict(include_details=False)  # Summary only in response
        }

        # KG loop closure: remind agents to resolve when addressed
        response["_resolve_when_done"] = f"When this is addressed, close the loop: knowledge(action='update', discovery_id='{discovery_id}', status='resolved')"

        # UX FIX (Feb 2026): Include warning if display_name was auto-generated
        if display_name_warning:
            response["_name_hint"] = display_name_warning

        # Add truncation warning if content was truncated (v2.5.0+)
        if truncation_info:
            response["_truncated"] = truncation_info
            response["_tip"] = "Content was truncated. For longer content, split into multiple discoveries or use details field (5000 char limit)."

        # Add human review flag if needed
        if requires_review:
            response["human_review_required"] = True
            response["review_message"] = f"High-severity discovery ({discovery.severity}) - please review for accuracy and safety"
        
        if similar_discoveries:
            response["related_discoveries"] = similar_discoveries
        
        return success_response(response, arguments=arguments)
        
    except ValueError as e:
        # Handle rate limiting errors from graph backend (efficient O(1) check)
        error_msg = str(e)
        if "rate limit" in error_msg.lower() or "Rate limit" in error_msg:
            return [error_response(
                error_msg,
                recovery={
                    "action": "Wait before storing more discoveries, or reduce batch size",
                    "related_tools": ["search_knowledge_graph"]
                }
            )]
        # Other ValueError (validation errors, etc.)
        return [error_response(error_msg)]
    except Exception as e:
        return [error_response(f"Failed to store knowledge: {str(e)}")]


@mcp_tool("search_knowledge_graph", timeout=15.0, rate_limit_exempt=True)
async def handle_search_knowledge_graph(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Search knowledge graph (indexed filters; optional FTS query).

    Use include_provenance=True to get provenance and lineage chain for each discovery.
    """
    # MAGNET PATTERN: Accept fuzzy inputs (search, term, find → query)
    arguments = apply_param_aliases("search_knowledge_graph", arguments)

    try:
        graph = await get_knowledge_graph()

        limit = arguments.get("limit", config.KNOWLEDGE_QUERY_DEFAULT_LIMIT)
        include_details = arguments.get("include_details", False)
        include_provenance = arguments.get("include_provenance", False)  # Merged from query_provenance

        # LLM delegation: synthesize results via local model
        # When enabled, uses Ollama to summarize key patterns from multiple discoveries
        synthesize = arguments.get("synthesize", False)

        # Optional full-text query (PostgreSQL FTS or AGE)
        # Accept both "query" and "text" as parameter names for better UX
        query_text = arguments.get("query") or arguments.get("text")
        agent_id = arguments.get("agent_id")
        tags = normalize_tags(arguments.get("tags", [])) or None
        dtype = arguments.get("discovery_type")
        severity = arguments.get("severity")
        status = arguments.get("status")
        # Default: exclude archived entries unless explicitly requested
        include_archived = arguments.get("include_archived", False)

        # Track semantic scores if semantic search is used
        semantic_scores_dict = {}
        
        t0 = time.perf_counter()
        if query_text:
            # UX FIX (Dec 2025): Auto-enable semantic search for conceptual queries
            # - If semantic=True explicitly: always use semantic search
            # - If semantic=False explicitly: never use semantic search
            # - If semantic not specified: auto-detect based on query complexity
            #   (queries with 2+ words are likely conceptual, benefit from semantic)
            has_semantic = hasattr(graph, "semantic_search")
            explicit_semantic = arguments.get("semantic")
            
            if explicit_semantic is not None:
                # User explicitly chose - respect their choice
                use_semantic = explicit_semantic and has_semantic
            else:
                # Auto-detect: use semantic search when available for any text query
                # Single-word queries benefit from semantic search too (substring_scan
                # is limited to 50 recent entries and misses most results)
                use_semantic = has_semantic
            
            if use_semantic:
                # Semantic search using vector embeddings
                # Default 0.3 for precision; auto-fallback to 0.2 catches edge cases
                min_similarity = arguments.get("min_similarity", 0.3)
                semantic_results = await graph.semantic_search(
                    str(query_text),
                    limit=limit * 2,  # Get extra for filtering
                    min_similarity=min_similarity
                )
                candidates = [d for d, _ in semantic_results]
                semantic_scores_dict = {d.id: score for d, score in semantic_results}
                search_mode = "semantic"
            elif hasattr(graph, "full_text_search"):
                # Prefer DB-native FTS when available
                candidate_limit = int(min(max(limit * 5, limit), 500))
                candidates = await graph.full_text_search(str(query_text), limit=candidate_limit)
                search_mode = "fts"
            else:
                # JSON backend fallback: bounded scan of most recent entries (kept small to prevent context bloat).
                # Reduced from 500 to 50 to prevent context bloat
                candidates = await graph.query(limit=50)
                search_mode = "substring_scan"

            # For FTS/semantic: trust the search engine's ranking, only apply metadata filters
            # For substring_scan: also require query term matches (OR-default)
            filtered = []
            q_terms = str(query_text).lower().split() if search_mode == "substring_scan" else None

            for d in candidates:
                # Substring filter only for non-FTS backends (OR-default)
                if q_terms:
                    tags_str = " ".join(d.tags or [])
                    hay = ((d.summary or "") + "\n" + (d.details or "") + "\n" + tags_str).lower()
                    if not any(term in hay for term in q_terms):
                        continue
                # Metadata filters apply to all modes
                if agent_id and d.agent_id != agent_id:
                    continue
                if dtype and d.type != dtype:
                    continue
                if severity and d.severity != severity:
                    continue
                if status and d.status != status:
                    continue
                # Exclude archived entries by default (unless status filter or include_archived)
                if not status and not include_archived and d.status == "archived":
                    continue
                if tags:
                    d_tags = set(d.tags or [])
                    if not any(t in d_tags for t in tags):
                        continue
                filtered.append(d)
                if len(filtered) >= limit:
                    break

            results = filtered
            # search_mode already set above
            # UX FIX: Make operator explicit upfront - FTS defaults to OR for multi-term queries
            query_terms = str(query_text).split() if query_text else []
            if search_mode == "fts" and len(query_terms) > 1:
                operator_used = "OR"  # FTS defaults to OR for multi-term queries
            else:
                operator_used = "AND" if len(query_terms) > 1 else "N/A"
            fields_searched = ["summary", "details", "tags"]
        else:
            # Indexed filter query (fast)
            # Push exclude_archived into the query so LIMIT applies after filtering.
            # Without this, LIMIT grabs N most recent (mostly archived junk), then
            # post-hoc filtering removes them, returning far fewer than N results.
            should_exclude_archived = not status and not include_archived
            results = await graph.query(
                agent_id=agent_id,
                tags=tags,
                type=dtype,
                severity=severity,
                status=status,
                limit=limit,
                exclude_archived=should_exclude_archived,
            )
            search_mode = "indexed_filters"
            operator_used = "N/A"  # No text search, just filters
            fields_searched = []
            if agent_id:
                fields_searched.append("agent_id")
            if tags:
                fields_searched.append("tags")
            if dtype:
                fields_searched.append("type")
            if severity:
                fields_searched.append("severity")
            if status:
                fields_searched.append("status")
        
        # UX FIX: Auto-retry with fallback if 0 results and query provided
        # Make fallback behavior explicit upfront
        fallback_used = False
        fallback_explanation = None
        if len(results) == 0 and query_text and search_mode in ["fts", "semantic"]:
            # Strategy 1: If semantic search returned 0, try FTS (more permissive)
            if search_mode == "semantic" and hasattr(graph, "full_text_search"):
                try:
                    logger.debug(f"Semantic search returned 0 results, falling back to FTS for '{query_text}'")
                    fts_candidates = await graph.full_text_search(str(query_text), limit=limit * 2)
                    # Apply same filters
                    for d in fts_candidates:
                        if agent_id and d.agent_id != agent_id:
                            continue
                        if dtype and d.type != dtype:
                            continue
                        if severity and d.severity != severity:
                            continue
                        if status and d.status != status:
                            continue
                        if not status and not include_archived and d.status == "archived":
                            continue
                        if tags:
                            d_tags = set(d.tags or [])
                            if not all(t in d_tags for t in tags):
                                continue
                        results.append(d)
                        if len(results) >= limit:
                            break
                    if len(results) > 0:
                        fallback_used = True
                        search_mode = "semantic_fallback_fts"
                        operator_used = "OR" if len(str(query_text).split()) > 1 else "N/A"
                        fallback_explanation = (
                            f"Semantic search found no concepts similar to '{query_text}' "
                            f"(similarity threshold: {min_similarity}). "
                            f"Falling back to keyword search (FTS) for exact term matching."
                        )
                except Exception as e:
                    logger.debug(f"Semantic→FTS fallback failed: {e}")
            
            # Strategy 2: If FTS returned 0, try individual terms with OR (more permissive)
            if len(results) == 0 and search_mode == "fts" and hasattr(graph, "full_text_search"):
                try:
                    terms = str(query_text).split()
                    if len(terms) > 1:
                        # Try each term individually (OR across terms)
                        fallback_results = []
                        for term in terms[:3]:  # Limit to first 3 terms
                            term_results = await graph.full_text_search(term, limit=limit)
                            fallback_results.extend(term_results)
                        # Deduplicate and apply filters
                        seen_ids = set()
                        for d in fallback_results:
                            if d.id not in seen_ids:
                                # Apply metadata filters
                                if agent_id and d.agent_id != agent_id:
                                    continue
                                if dtype and d.type != dtype:
                                    continue
                                if severity and d.severity != severity:
                                    continue
                                if status and d.status != status:
                                    continue
                                if not status and not include_archived and d.status == "archived":
                                    continue
                                if tags:
                                    d_tags = set(d.tags or [])
                                    if not all(t in d_tags for t in tags):
                                        continue
                                results.append(d)
                                seen_ids.add(d.id)
                                if len(results) >= limit:
                                    break
                        if len(results) > 0:
                            fallback_used = True
                            search_mode = "fts_fallback"
                            operator_used = "OR (fallback)"  # Explicitly marked as fallback
                            fallback_explanation = (
                                f"No exact phrase matches found for '{query_text}'. "
                                f"Falling back to individual term search (OR operator) for: {', '.join(terms[:3])}"
                            )
                except Exception as e:
                    logger.debug(f"FTS fallback search failed: {e}")
            
            # Strategy 3: If semantic returned 0 and FTS fallback also returned 0, try semantic with lower threshold
            if len(results) == 0 and search_mode in ["semantic", "semantic_fallback_fts"] and hasattr(graph, "semantic_search"):
                try:
                    # Lower similarity threshold for fallback
                    lower_threshold = 0.2  # More permissive
                    logger.debug(f"Trying semantic search with lower threshold ({lower_threshold}) for '{query_text}'")
                    semantic_results = await graph.semantic_search(
                        str(query_text),
                        limit=limit * 2,
                        min_similarity=lower_threshold
                    )
                    # Apply filters
                    for d, score in semantic_results:
                        if agent_id and d.agent_id != agent_id:
                            continue
                        if dtype and d.type != dtype:
                            continue
                        if severity and d.severity != severity:
                            continue
                        if status and d.status != status:
                            continue
                        if tags:
                            d_tags = set(d.tags or [])
                            if not all(t in d_tags for t in tags):
                                continue
                        results.append(d)
                        semantic_scores_dict[d.id] = score
                        if len(results) >= limit:
                            break
                    if len(results) > 0:
                        fallback_used = True
                        search_mode = "semantic_fallback_lower_threshold"
                        operator_used = "N/A"
                        fallback_explanation = (
                            f"No matches found with default similarity threshold ({min_similarity}). "
                            f"Retrying with lower threshold ({lower_threshold}) for more permissive semantic matching."
                        )
                except Exception as e:
                    logger.debug(f"Semantic lower-threshold fallback failed: {e}")
        
        dt_ms = (time.perf_counter() - t0) * 1000.0
        record_ms(f"knowledge.search.{search_mode}", dt_ms)
        
        # Auto-include details when result set is small (saves a round-trip)
        auto_details = not include_details and 0 < len(results) <= 3
        if auto_details:
            include_details = True

        # Build discovery list with optional provenance
        # UX FIX (Dec 2025): Display name FIRST for human readability
        # Format: {"by": "DisplayName", "summary": "...", ...}
        discovery_list = []
        for d in results:
            agent_display = _resolve_agent_display(d.agent_id)
            display_name = agent_display.get("display_name", d.agent_id)

            # Build dict with display_name first for prominence
            d_dict = {
                "by": display_name,  # WHO - first for attribution
                "summary": d.summary,  # WHAT - second for context
            }

            # Add remaining fields from discovery
            full_dict = d.to_dict(include_details=include_details)
            d_dict["id"] = full_dict.get("id")
            d_dict["type"] = full_dict.get("type")
            d_dict["status"] = full_dict.get("status")
            d_dict["tags"] = full_dict.get("tags", [])
            d_dict["created_at"] = full_dict.get("created_at")

            # Include details if requested
            if include_details and full_dict.get("details"):
                d_dict["details"] = full_dict.get("details")

            # Keep agent_id for internal reference (de-emphasized)
            d_dict["_agent_id"] = d.agent_id

            if include_provenance:
                d_dict["provenance"] = d.provenance
                if d.provenance_chain:
                    d_dict["provenance_chain"] = d.provenance_chain
            discovery_list.append(d_dict)
        
        # Include similarity scores for semantic search
        response_data = {
            "search_mode_used": search_mode,
            "operator_used": operator_used,
            "fields_searched": fields_searched,
            "query": query_text,
            "discoveries": discovery_list,
            "count": len(results),
            "message": f"Found {len(results)} discovery(ies)" + (" (details auto-included for small result set)" if auto_details else "" if include_details else " (summaries only)")
        }

        # UX FIX: Make fallback behavior explicit and transparent
        if fallback_used:
            response_data["fallback_used"] = True
            response_data["fallback_message"] = fallback_explanation or "No exact matches found. Retried with individual terms (OR operator)."
            response_data["fallback_terms"] = str(query_text).split()[:3] if query_text else []
        
        # UX FIX: Add contextual helpful hints for empty results
        if len(results) == 0:
            hints = []
            # Count words properly (split on spaces, also handle underscores as word separators)
            if query_text:
                query_str = str(query_text)
                # Replace underscores with spaces for word counting
                query_normalized = query_str.replace("_", " ").replace("-", " ")
                query_words = len([w for w in query_normalized.split() if w.strip()])
            else:
                query_words = 0
            
            if query_text:
                # Contextual suggestions based on query characteristics
                if query_words >= 5:
                    # Long, specific query - suggest semantic search prominently
                    hints.append(f"Long query ({query_words} words) - try semantic search: search_knowledge_graph(query='{query_text}', semantic=true)")
                    hints.append(f"Or broaden to key concepts: search_knowledge_graph(query='{', '.join(str(query_text).split()[:3])}')")
                elif query_words >= 2:
                    # Multi-word query - suggest semantic or broader terms
                    hints.append(f"Multi-word query - try semantic search (semantic=true) for conceptual matching")
                    hints.append(f"Or search individual terms: {', '.join(str(query_text).split()[:3])}")
                else:
                    # Single word - suggest broadening or tags
                    hints.append(f"Single term '{query_text}' - try broader search or use tags")
                    hints.append(f"Try: search_knowledge_graph(tags=['{query_text}']) or broaden query")
                
                # Always suggest tag search as alternative
                hints.append(f"Alternative: Search by tags instead (tags=['tag1', 'tag2'])")
            
            # Filter-specific suggestions
            if agent_id:
                hints.append(f"Filter active: agent_id='{agent_id[:20]}...' - remove to search across all agents")
            if tags:
                hints.append(f"Filter active: {len(tags)} tag(s) - remove or use fewer tags for broader results")
            if dtype:
                hints.append(f"Filter active: type='{dtype}' - remove to search all discovery types")
            if severity:
                hints.append(f"Filter active: severity='{severity}' - remove to search all severities")
            
            if hints:
                response_data["empty_results_hints"] = hints
                # Prioritize most actionable hint first
                primary_hint = hints[0] if hints else "Try adjusting your search parameters"
                response_data["tip"] = f"No results found. {primary_hint}"
                response_data["all_suggestions"] = hints  # Keep all hints available
        
        # UX FIX: Document operator behavior upfront for multi-term queries
        if query_text and len(str(query_text).split()) > 1:
            if search_mode == "fts" and not fallback_used:
                response_data["operator_note"] = "Multi-term queries use OR operator by default (finds discoveries matching any term). If you need AND behavior, use tags or multiple filters."
            elif search_mode == "semantic":
                response_data["operator_note"] = "Semantic search considers all terms together (conceptual similarity, not keyword matching)."

        # Visibility hints about options (v2.5.0+)
        if not include_details:
            response_data["_tip"] = "Add include_details=true to expand all results inline"
        if len(results) == limit:
            response_data["_more_available"] = f"Results may be limited to {limit}. Use limit=N (max 100) to get more."
        
        # Add similarity scores if semantic search was used
        if search_mode in ["semantic", "semantic_fallback_lower_threshold"] and query_text and use_semantic:
            similarity_scores = {
                d.id: round(semantic_scores_dict[d.id], 3)
                for d in results
                if d.id in semantic_scores_dict
            }
            if similarity_scores:
                response_data["similarity_scores"] = similarity_scores
        
        # UX FIX (Dec 2025): Add helpful hint when substring scan returns no results
        if search_mode == "substring_scan" and len(results) == 0 and query_text:
            response_data["search_hint"] = (
                "No results with substring matching. Try: "
                "1) Use specific tags: tags=['identity', 'philosophy'] "
                "2) Search by discovery_type: discovery_type='insight' "
                "3) Use single keywords instead of phrases"
            )

        # LLM DELEGATION: Synthesize results via local model when requested
        # Threshold: Only synthesize when there are enough results to make it worthwhile
        SYNTHESIS_THRESHOLD = 3  # Minimum discoveries to trigger synthesis
        if synthesize and len(discovery_list) >= SYNTHESIS_THRESHOLD:
            try:
                synthesis_result = await synthesize_results(
                    discoveries=discovery_list,
                    query=query_text,
                    max_discoveries=10,  # Cap at 10 for prompt size
                    max_tokens=400
                )
                if synthesis_result:
                    response_data["synthesis"] = synthesis_result
                    logger.debug(f"Knowledge synthesis generated for {len(discovery_list)} discoveries")
            except Exception as e:
                # Non-blocking: If synthesis fails, still return results
                logger.debug(f"Synthesis skipped: {e}")
                response_data["_synthesis_note"] = "Synthesis unavailable (local LLM not responding)"
        elif synthesize and len(discovery_list) < SYNTHESIS_THRESHOLD:
            response_data["_synthesis_note"] = f"Synthesis skipped: fewer than {SYNTHESIS_THRESHOLD} results"

        # Touch last_referenced on results that had details included (fire-and-forget)
        if include_details and results:
            import asyncio

            async def _touch_referenced(ids):
                try:
                    g = await get_knowledge_graph()
                    now_iso = datetime.now().isoformat()
                    for did in ids:
                        await g.update_discovery(did, {"last_referenced": now_iso})
                except Exception:
                    pass  # Best-effort, don't fail the search

            asyncio.create_task(_touch_referenced([d.id for d in results]))

        return success_response(response_data, arguments=arguments)

    except Exception as e:
        return [error_response(f"Failed to search knowledge: {str(e)}")]


@mcp_tool("get_knowledge_graph", timeout=15.0, rate_limit_exempt=True, register=False)
async def handle_get_knowledge_graph(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Get all knowledge for an agent - summaries only (use get_discovery_details for full content)"""
    # SECURITY FIX: Verify agent_id is registered (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    try:
        graph = await get_knowledge_graph()
        
        limit = arguments.get("limit")
        t0 = time.perf_counter()
        discoveries = await graph.get_agent_discoveries(agent_id, limit=limit)
        record_ms("knowledge.get_agent_discoveries", (time.perf_counter() - t0) * 1000.0)
        
        # Return summaries only by default
        include_details = arguments.get("include_details", False)

        # UX FIX (Dec 2025): Display name FIRST for human readability
        agent_display = arguments.get("_agent_display") or _resolve_agent_display(agent_id)
        display_name = agent_display.get("display_name", agent_id)
        discovery_list = []
        for d in discoveries:
            full_dict = d.to_dict(include_details=include_details)
            # Build dict with display_name first for prominence
            d_dict = {
                "by": display_name,  # WHO - first for attribution
                "summary": d.summary,  # WHAT - second for context
                "id": full_dict.get("id"),
                "type": full_dict.get("type"),
                "status": full_dict.get("status"),
                "tags": full_dict.get("tags", []),
                "created_at": full_dict.get("created_at"),
            }
            if include_details and full_dict.get("details"):
                d_dict["details"] = full_dict.get("details")
            d_dict["_agent_id"] = d.agent_id
            discovery_list.append(d_dict)

        response_data = {
            "agent": agent_display,
            "discoveries": discovery_list,
            "count": len(discoveries)
        }

        # Visibility hints (v2.5.0+)
        if not include_details and len(discoveries) > 0:
            response_data["_tip"] = "Add include_details=true to expand all results inline"
        if limit and len(discoveries) == limit:
            response_data["_more_available"] = f"Results limited to {limit}. Use limit=N to get more."

        return success_response(response_data, arguments=arguments)
        
    except Exception as e:
        return [error_response(f"Failed to retrieve knowledge: {str(e)}")]


@mcp_tool("list_knowledge_graph", timeout=10.0, rate_limit_exempt=True, register=False)
async def handle_list_knowledge_graph(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """List knowledge graph statistics - full transparency"""
    try:
        graph = await get_knowledge_graph()
        t0 = time.perf_counter()
        stats = await graph.get_stats()
        record_ms("knowledge.get_stats", (time.perf_counter() - t0) * 1000.0)
        
        return success_response({
            "stats": stats,
            "message": f"Knowledge graph contains {stats['total_discoveries']} discoveries from {stats['total_agents']} agents"
        }, arguments=arguments)
        
    except Exception as e:
        return [error_response(f"Failed to list knowledge: {str(e)}")]


@mcp_tool("update_discovery_status_graph", timeout=10.0, register=False)
async def handle_update_discovery_status_graph(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Update discovery status - fast graph update
    
    SECURITY: Requires authentication for high-severity discoveries.
    Low/medium severity discoveries can be updated by any registered agent (collaborative).
    """
    # SECURITY FIX: Require registered agent_id (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]
    
    discovery_id, error = require_argument(arguments, "discovery_id",
                                         "discovery_id is required")
    if error:
        return [error]
    
    # Validate discovery_id format
    discovery_id, error = validate_discovery_id(discovery_id)
    if error:
        return [error]
    
    status, error = require_argument(arguments, "status",
                                   "status is required (open, resolved, archived, disputed)")
    if error:
        return [error]
    
    # Validate status enum
    status, error = validate_discovery_status(status)
    if error:
        return [error]
    
    try:
        graph = await get_knowledge_graph()
        
        # Get discovery to check severity and ownership
        discovery = await graph.get_discovery(discovery_id)
        if not discovery:
            return [await _discovery_not_found(discovery_id, graph)]
        
        # SECURITY: Require session ownership for high-severity discoveries (UUID-based auth, Dec 2025)
        if discovery.severity in ["high", "critical"]:
            from .utils import verify_agent_ownership
            if not verify_agent_ownership(agent_id, arguments):
                return [error_response(
                    "Authentication required for updating high-severity discoveries.",
                    error_code="AUTH_REQUIRED",
                    error_category="auth_error",
                    recovery={
                        "action": "Ensure your session is bound to this agent",
                        "related_tools": ["identity"],
                        "workflow": "Identity auto-binds on first tool call. Use identity() to check binding."
                    }
                )]
            
            # Ownership check: non-owners can resolve/close, but not reopen or modify
            if discovery.agent_id != agent_id and status not in ("resolved", "closed", "wont_fix"):
                return [error_response(
                    f"Permission denied: Cannot set status '{status}' on high-severity discovery '{discovery_id}'. "
                    f"Non-owners can only resolve/close high-severity discoveries.",
                    recovery={
                        "action": "Use status='resolved' or 'closed' to close another agent's discovery",
                        "related_tools": ["get_discovery_details", "search_knowledge_graph"],
                    }
                )]
        
        updates = {"status": status}
        if status == "resolved":
            updates["resolved_at"] = datetime.now().isoformat()
        
        success = await graph.update_discovery(discovery_id, updates)
        
        if not success:
            return [error_response(f"Discovery '{discovery_id}' not found")]
        
        discovery = await graph.get_discovery(discovery_id)
        
        return success_response({
            "message": f"Discovery '{discovery_id}' status updated to '{status}'",
            "discovery": discovery.to_dict(include_details=False) if discovery else None
        }, arguments=arguments)
        
    except Exception as e:
        return [error_response(f"Failed to update discovery: {str(e)}")]


@mcp_tool("get_discovery_details", timeout=10.0, rate_limit_exempt=True, register=False)
async def handle_get_discovery_details(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Get full details for a specific discovery with optional pagination and response chain.

    Parameters:
    - discovery_id: ID of the discovery to retrieve (required)
    - offset: Character offset for details pagination (default: 0)
    - length: Max characters to return for details (default: 2000)
    - include_response_chain: Include the chain of responses (Q→A→followup) (default: false)
    - max_chain_depth: Max depth for response chain traversal (default: 10)

    Migration Note (Dec 2025): This tool now includes response chain functionality
    previously available via get_response_chain_graph (deprecated).
    """
    discovery_id, error = require_argument(arguments, "discovery_id",
                                         "discovery_id is required")
    if error:
        return [error]

    # Validate discovery_id format
    discovery_id, error = validate_discovery_id(discovery_id)
    if error:
        return [error]

    try:
        graph = await get_knowledge_graph()

        discovery = await graph.get_discovery(discovery_id)
        if not discovery:
            return [await _discovery_not_found(discovery_id, graph)]

        # UX FIX: Pagination support for long details
        offset = arguments.get("offset", 0)
        length = arguments.get("length", 2000)

        details = discovery.details or ""
        total_length = len(details)

        # Apply pagination if details exceed length or offset > 0
        if offset > 0 or total_length > length:
            details_slice = details[offset:offset + length]
            has_more = (offset + length) < total_length

            response = {
                "discovery": discovery.to_dict(include_details=False),
                "details": details_slice,
                "pagination": {
                    "offset": offset,
                    "length": len(details_slice),
                    "total_length": total_length,
                    "has_more": has_more,
                    "next_offset": offset + length if has_more else None
                },
                "message": f"Details for discovery '{discovery_id}' (showing {offset}-{offset + len(details_slice)} of {total_length} chars)"
            }
        else:
            # Full content fits - no pagination needed
            response = {
                "discovery": discovery.to_dict(include_details=True),
                "message": f"Full details for discovery '{discovery_id}'"
            }

        # Response chain traversal (Dec 2025 - restores get_response_chain_graph functionality)
        include_chain = arguments.get("include_response_chain", False)
        if include_chain:
            max_depth = arguments.get("max_chain_depth", 10)

            # Check if backend supports response chain traversal
            if hasattr(graph, 'get_response_chain'):
                try:
                    chain = await graph.get_response_chain(discovery_id, max_depth=max_depth)
                    response["response_chain"] = {
                        "count": len(chain),
                        "max_depth": max_depth,
                        "discoveries": [d.to_dict(include_details=False) for d in chain]
                    }
                    response["message"] += f" (includes {len(chain)} discoveries in response chain)"
                except Exception as chain_err:
                    # Non-fatal: include error but don't fail the request
                    response["response_chain"] = {
                        "error": f"Chain traversal failed: {str(chain_err)}",
                        "note": "Discovery details still returned successfully"
                    }
            else:
                # Backend doesn't support chain traversal
                response["response_chain"] = {
                    "error": "Response chain traversal not supported by current backend",
                    "note": "Use AGE backend (UNITARES_KNOWLEDGE_BACKEND=age) for full graph features"
                }

        # Touch last_referenced (fire-and-forget keep-alive signal)
        import asyncio

        async def _touch(did):
            try:
                await graph.update_discovery(did, {"last_referenced": datetime.now().isoformat()})
            except Exception:
                pass

        asyncio.create_task(_touch(discovery_id))

        return success_response(response, arguments=arguments)

    except Exception as e:
        return [error_response(f"Failed to get discovery details: {str(e)}")]


async def _handle_store_knowledge_graph_batch(arguments: Dict[str, Any], agent_id: str) -> Sequence[TextContent]:
    """Internal batch handler - called by store_knowledge_graph when discoveries array is provided"""
    discoveries = arguments.get("discoveries")
    
    if not isinstance(discoveries, list):
        return [error_response("discoveries must be a list of discovery objects")]
    
    if len(discoveries) == 0:
        return [error_response("discoveries list cannot be empty")]
    
    if len(discoveries) > 10:
        return [error_response("Maximum 10 discoveries per batch (to prevent context overflow)")]
    
    # agent_id already validated by caller
    
    try:
        graph = await get_knowledge_graph()
        
        # SECURITY: Rate limiting is handled by the knowledge graph backend per-discovery
        # Backend handles rate limiting internally (O(1) per store)
        # No need for inefficient O(n) query here - let graph handle it per-discovery
        
        # Process each discovery with graceful error handling
        stored = []
        errors = []
        
        for idx, disc_data in enumerate(discoveries):
            try:
                # Validate required fields
                if not isinstance(disc_data, dict):
                    errors.append(f"Discovery {idx}: must be a dict")
                    continue
                
                discovery_type = disc_data.get("discovery_type")
                if not discovery_type:
                    errors.append(f"Discovery {idx}: discovery_type is required")
                    continue
                
                discovery_type, error = validate_discovery_type(discovery_type)
                if error:
                    errors.append(f"Discovery {idx}: {error.text if hasattr(error, 'text') else str(error)}")
                    continue
                
                summary = disc_data.get("summary", "")
                if not summary:
                    errors.append(f"Discovery {idx}: summary is required")
                    continue
                
                # Truncate fields (match single-discovery limits)
                MAX_SUMMARY_LEN = 1000
                MAX_DETAILS_LEN = 5000

                truncated_fields = []
                if len(summary) > MAX_SUMMARY_LEN:
                    truncated_fields.append(f"summary ({len(summary)} → {MAX_SUMMARY_LEN})")
                    # Try to cut at sentence boundary, else word boundary
                    truncated = summary[:MAX_SUMMARY_LEN]
                    for end_char in ['. ', '! ', '? ']:
                        last_end = truncated.rfind(end_char, MAX_SUMMARY_LEN - 100)
                        if last_end > 0:
                            truncated = truncated[:last_end + 1]
                            break
                    else:
                        last_space = truncated.rfind(' ')
                        if last_space > MAX_SUMMARY_LEN - 50:
                            truncated = truncated[:last_space]
                    summary = truncated.rstrip() + "..."

                # Accept both 'details' and 'content' as parameter names
                details = disc_data.get("details") or disc_data.get("content") or ""
                if len(details) > MAX_DETAILS_LEN:
                    truncated_fields.append(f"details ({len(details)} → {MAX_DETAILS_LEN})")
                    details = details[:MAX_DETAILS_LEN] + "... [truncated]"
                
                # Create discovery node
                discovery_id = datetime.now().isoformat()
                
                # Parse response_to if provided
                response_to = None
                if "response_to" in disc_data and disc_data["response_to"]:
                    resp_data = disc_data["response_to"]
                    if isinstance(resp_data, dict) and "discovery_id" in resp_data and "response_type" in resp_data:
                        # Validate discovery_id format
                        parent_id, error = validate_discovery_id(resp_data["discovery_id"])
                        if error:
                            errors.append(f"Discovery {idx}: Invalid response_to.discovery_id - {error.text if hasattr(error, 'text') else str(error)}")
                            continue
                        
                        response_type, error = validate_response_type(resp_data["response_type"])
                        if not error:
                            response_to = ResponseTo(
                                discovery_id=parent_id,
                                response_type=response_type
                            )
                
                # Validate severity
                severity = disc_data.get("severity")
                if severity is not None:
                    severity, error = validate_severity(severity)
                    if error:
                        severity = None  # Use default if invalid
                
                discovery = DiscoveryNode(
                    id=discovery_id,
                    agent_id=agent_id,
                    type=discovery_type,
                    summary=summary,
                    details=details,
                    tags=disc_data.get("tags", []),
                    severity=severity,
                    response_to=response_to,
                    references_files=disc_data.get("related_files", [])
                )
                
                # Auto-link similar discoveries
                if disc_data.get("auto_link_related", True):
                    similar = await graph.find_similar(discovery, limit=3)
                    discovery.related_to = [s.id for s in similar]
                
                # SECURITY: Require session ownership for high-severity discoveries (UUID-based auth, Dec 2025)
                if discovery.severity in ["high", "critical"]:
                    from .utils import verify_agent_ownership
                    if not verify_agent_ownership(agent_id, arguments):
                        errors.append(f"Discovery {idx}: Authentication required for high-severity discoveries")
                        continue
                
                # Add to graph (rate limiting handled internally)
                await graph.add_discovery(discovery)
                stored_item = {
                    "discovery_id": discovery_id,
                    "summary": summary,
                    "type": discovery_type
                }
                if truncated_fields:
                    stored_item["_truncated"] = truncated_fields
                stored.append(stored_item)
                
            except ValueError as e:
                # Handle rate limiting and validation errors gracefully
                error_msg = str(e)
                if "rate limit" in error_msg.lower() or "Rate limit" in error_msg:
                    errors.append(f"Discovery {idx}: Rate limit exceeded - {error_msg}")
                else:
                    errors.append(f"Discovery {idx}: Validation error - {error_msg}")
            except Exception as e:
                errors.append(f"Discovery {idx}: {str(e)}")
        
        # Return results
        response = {
            "message": f"Stored {len(stored)}/{len(discoveries)} discovery/discoveries",
            "stored": stored,
            "total": len(discoveries),
            "success_count": len(stored),
            "error_count": len(errors)
        }

        if errors:
            response["errors"] = errors

        # Check if any items were truncated (v2.5.0+)
        truncated_count = sum(1 for s in stored if "_truncated" in s)
        if truncated_count > 0:
            response["_tip"] = f"{truncated_count} discovery(ies) had content truncated. Limits: summary=1000, details=5000 chars."

        return success_response(response, arguments=arguments)
        
    except Exception as e:
        return [error_response(f"Failed to store batch knowledge: {str(e)}")]


@mcp_tool("answer_question", timeout=15.0, register=False)
async def handle_answer_question(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Answer a question in the knowledge graph - closes the Q&A loop.

    Searches for matching questions and stores your answer linked to it.
    No need to know the question's discovery_id - just provide the question text and your answer.

    Parameters:
    - question: Text to match against existing questions (fuzzy search)
    - answer: Your answer to the question
    - tags: Optional tags for the answer
    """
    # SECURITY FIX: Verify agent_id is registered
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    question_text, error = require_argument(arguments, "question",
                                           "question is required - what question are you answering?")
    if error:
        return [error]

    answer_text, error = require_argument(arguments, "answer",
                                         "answer is required - your response to the question")
    if error:
        return [error]

    try:
        graph = await get_knowledge_graph()

        # Search for matching questions
        candidates = await graph.query(type="question", limit=20)

        # Find best match using substring matching
        q_lower = question_text.lower()
        matched_question = None
        best_score = 0

        for d in candidates:
            summary_lower = (d.summary or "").lower()
            # Simple scoring: longer common substring = better match
            if q_lower in summary_lower or summary_lower in q_lower:
                score = len(set(q_lower.split()) & set(summary_lower.split()))
                if score > best_score:
                    best_score = score
                    matched_question = d

        if not matched_question:
            # No matching question found - list available questions
            recent_questions = await graph.query(type="question", limit=5)
            question_summaries = [
                {"id": q.id, "summary": q.summary[:100] + "..." if len(q.summary) > 100 else q.summary}
                for q in recent_questions
            ]
            return [error_response(
                f"No matching question found for: '{question_text[:50]}...'",
                details={"recent_questions": question_summaries},
                recovery={
                    "action": "Try a different search term or use store_knowledge_graph with response_to",
                    "related_tools": ["search_knowledge_graph"],
                    "workflow": "1. search_knowledge_graph(discovery_type='question') 2. Use the discovery_id in response_to"
                }
            )]

        # Truncate answer if too long
        MAX_ANSWER_LEN = 2000
        if len(answer_text) > MAX_ANSWER_LEN:
            answer_text = answer_text[:MAX_ANSWER_LEN] + "... [truncated]"

        # Create answer linked to the question
        answer = DiscoveryNode(
            id=datetime.now().isoformat(),
            agent_id=agent_id,
            type="answer",
            summary=f"Answer: {answer_text[:200]}..." if len(answer_text) > 200 else f"Answer: {answer_text}",
            details=answer_text,
            tags=normalize_tags(arguments.get("tags", [])),
            severity="low",
            status="open",
            response_to=ResponseTo(
                discovery_id=matched_question.id,
                response_type="answers"
            )
        )

        # Link answer to question
        answer.related_to = [matched_question.id]

        await graph.add_discovery(answer)

        # Optionally mark question as resolved
        if arguments.get("resolve_question", False):
            await graph.update_discovery(matched_question.id, {
                "status": "resolved",
                "resolved_at": datetime.now().isoformat()
            })

        return success_response({
            "message": "Answer stored and linked to question",
            "answer_id": answer.id,
            "question": {
                "id": matched_question.id,
                "summary": matched_question.summary,
                "status": "resolved" if arguments.get("resolve_question") else matched_question.status
            },
            "answer": answer.to_dict(include_details=False)
        }, arguments=arguments)

    except Exception as e:
        return [error_response(f"Failed to answer question: {str(e)}")]


@mcp_tool("leave_note", timeout=10.0)
async def handle_leave_note(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Leave a quick note in the knowledge graph - minimal friction contribution.

    Just agent_id + summary + optional tags. Auto-sets type='note', severity='low'.
    For when you want to jot something down without the full store_knowledge_graph ceremony.
    """
    # Apply parameter aliases (e.g., "text" → "summary", "note" → "summary")
    arguments = apply_param_aliases("leave_note", arguments)
    
    # Set tool name in context for better error messages
    arguments["_tool_name"] = "leave_note"

    # SECURITY FIX: Verify agent_id is registered (prevents phantom agent_ids)
    agent_id, error = require_registered_agent(arguments)
    if error:
        return [error]

    # CIRCUIT BREAKER: Paused agents cannot leave notes
    from .utils import check_agent_can_operate
    blocked = check_agent_can_operate(agent_id)
    if blocked:
        return [blocked]

    text, error = require_argument(arguments, "summary",
                                  "Note content required. Use 'summary', 'note', 'text', or 'content' parameter.")
    if error:
        return [error]
    
    try:
        graph = await get_knowledge_graph()
        
        # Notes use the same limits as store_knowledge_graph
        MAX_SUMMARY_LEN = 1000
        MAX_DETAILS_LEN = 5000
        MAX_NOTE_TOTAL = MAX_SUMMARY_LEN + MAX_DETAILS_LEN
        if len(text) > MAX_NOTE_TOTAL:
            text = text[:MAX_NOTE_TOTAL] + "... [truncated]"
        
        # Parse response_to if provided (for threading)
        response_to = None
        if "response_to" in arguments and arguments["response_to"]:
            resp_data = arguments["response_to"]
            if isinstance(resp_data, dict) and "discovery_id" in resp_data and "response_type" in resp_data:
                # Validate discovery_id format
                parent_id, error = validate_discovery_id(resp_data["discovery_id"])
                if error:
                    return [error]
                
                # Validate response_type enum
                response_type, error = validate_response_type(resp_data["response_type"])
                if error:
                    return [error]
                
                response_to = ResponseTo(
                    discovery_id=parent_id,
                    response_type=response_type
                )
        
        # Build tags — notes are ephemeral by default (auto-archived after 7 days)
        # unless the caller signals permanence via tags or lasting=True
        tags = normalize_tags(arguments.get("tags", []))
        lasting = arguments.get("lasting", False)
        if isinstance(lasting, str):
            lasting = lasting.lower() in ("true", "1", "yes")
        PERMANENT_SIGNALS = {"permanent", "foundational", "architecture", "decision"}
        if not lasting and not (set(tags) & PERMANENT_SIGNALS):
            if "ephemeral" not in tags:
                tags.append("ephemeral")

        # Split long notes into summary + details
        if len(text) <= MAX_SUMMARY_LEN:
            note_summary = text
            note_details = ""
        else:
            # Try to split at a sentence boundary within summary limit
            truncated = text[:MAX_SUMMARY_LEN]
            split_pos = MAX_SUMMARY_LEN
            for end_char in ['. ', '! ', '? ', '\n']:
                last_end = truncated.rfind(end_char, MAX_SUMMARY_LEN - 200)
                if last_end > 0:
                    split_pos = last_end + len(end_char)
                    break
            else:
                last_space = truncated.rfind(' ')
                if last_space > MAX_SUMMARY_LEN - 100:
                    split_pos = last_space
            note_summary = text[:split_pos].rstrip()
            note_details = text[split_pos:].strip()

        # Create note with minimal ceremony
        note = DiscoveryNode(
            id=datetime.now().isoformat(),
            agent_id=agent_id,
            type="note",
            summary=note_summary,
            details=note_details,
            tags=tags,
            severity="low",
            status="open",
            response_to=response_to
        )
        
        # Auto-link if tags provided (fast with indexes)
        if note.tags:
            similar = await graph.find_similar(note, limit=3)
            note.related_to = [s.id for s in similar]
        
        await graph.add_discovery(note)

        # v2.5.3: Include agent display info
        agent_display = arguments.get("_agent_display") or _resolve_agent_display(agent_id)

        # UX FIX (Feb 2026): Clarify visibility - notes are shared and discoverable
        # KG loop closure: remind agents to resolve when addressed
        return success_response({
            "message": f"Note saved",
            "note_id": note.id,
            "agent": agent_display,
            "note": note.to_dict(include_details=False),
            # Clarify visibility for agent understanding
            "visibility": "shared",
            "discoverable": True,
            "_visibility_note": "Notes are shared and searchable by other agents. Use response_to to reply to discoveries.",
            "_resolve_when_done": f"When this is addressed, close the loop: knowledge(action='update', discovery_id='{note.id}', status='resolved')",
        }, arguments=arguments)

    except Exception as e:
        return [error_response(f"Failed to leave note: {str(e)}")]


@mcp_tool("cleanup_knowledge_graph", timeout=60.0, register=False)
async def handle_cleanup_knowledge_graph(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Run knowledge graph lifecycle cleanup.

    Manages discovery lifecycle based on type-based policies:
    - Permanent: architecture_decision, learning, pattern (never auto-archive)
    - Standard: resolved items archived after 30 days
    - Ephemeral: tagged with ephemeral/temp/scratch, archived after 7 days

    Args:
        dry_run: If true, preview changes without applying them (default: true)

    Returns lifecycle cleanup summary with counts of archived/moved discoveries.

    Philosophy: Never delete. Archive forever.
    """
    dry_run = arguments.get("dry_run", True)

    try:
        from src.knowledge_graph_lifecycle import run_kg_lifecycle_cleanup
        result = await run_kg_lifecycle_cleanup(dry_run=dry_run)

        return success_response({
            "message": f"{'[DRY RUN] ' if dry_run else ''}Lifecycle cleanup complete",
            "cleanup_result": result,
        }, arguments=arguments)

    except Exception as e:
        return [error_response(f"Failed to run lifecycle cleanup: {str(e)}")]


@mcp_tool("get_lifecycle_stats", timeout=30.0, rate_limit_exempt=True, register=False)
async def handle_get_lifecycle_stats(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Get knowledge graph lifecycle statistics.

    Shows discovery counts by status and lifecycle policy, plus candidates
    ready for archival or cold storage.

    Useful for understanding knowledge graph health and what cleanup would do.
    """
    try:
        from src.knowledge_graph_lifecycle import get_kg_lifecycle_stats
        stats = await get_kg_lifecycle_stats()

        return success_response({
            "message": "Lifecycle statistics",
            "stats": stats,
        }, arguments=arguments)

    except Exception as e:
        return [error_response(f"Failed to get lifecycle stats: {str(e)}")]


@mcp_tool("supersede_discovery", timeout=15.0, register=False)
async def handle_supersede_discovery(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Mark a discovery as superseding another.

    Creates a SUPERSEDES edge in the knowledge graph. Superseded entries
    receive a ranking penalty in search results.

    Args:
        discovery_id: The newer discovery (the one that replaces)
        supersedes_id: The older discovery being replaced

    Returns success/failure status.
    """
    new_id = arguments.get("discovery_id")
    old_id = arguments.get("supersedes_id")

    if not new_id or not old_id:
        return [error_response("Both discovery_id and supersedes_id are required")]

    try:
        graph = await get_knowledge_graph()
        if not hasattr(graph, "supersede_discovery"):
            return [error_response("SUPERSEDES edges require AGE graph backend")]

        result = await graph.supersede_discovery(new_id=new_id, old_id=old_id)
        if result.get("success"):
            return success_response(result, arguments=arguments)
        else:
            return [error_response(result.get("error", "Failed to create SUPERSEDES edge"))]
    except Exception as e:
        return [error_response(f"Failed to supersede discovery: {str(e)}")]


