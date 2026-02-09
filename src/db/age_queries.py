"""
Apache AGE Cypher Query Builders

Provides helper functions to build common Cypher queries for the knowledge graph.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime


def create_discovery_node(
    discovery_id: str,
    agent_id: str,
    discovery_type: str,
    summary: str,
    details: Optional[str] = None,
    severity: Optional[str] = None,
    status: str = "open",
    timestamp: Optional[datetime] = None,
    resolved_at: Optional[datetime] = None,
    eisv_e: Optional[float] = None,
    eisv_i: Optional[float] = None,
    eisv_s: Optional[float] = None,
    eisv_v: Optional[float] = None,
    regime: Optional[str] = None,
    coherence: Optional[float] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query to create a Discovery node.
    
    Returns:
        (cypher_query, params_dict)
    """
    props = {
        "id": discovery_id,
        "agent_id": agent_id,
        "type": discovery_type,
        "summary": summary,
        "status": status,
    }
    
    if details:
        props["details"] = details
    if severity:
        props["severity"] = severity
    if timestamp:
        props["timestamp"] = timestamp.isoformat()
    if resolved_at:
        props["resolved_at"] = resolved_at.isoformat()
    
    # EISV fields (for self_observation type)
    if eisv_e is not None:
        props["eisv_e"] = eisv_e
    if eisv_i is not None:
        props["eisv_i"] = eisv_i
    if eisv_s is not None:
        props["eisv_s"] = eisv_s
    if eisv_v is not None:
        props["eisv_v"] = eisv_v
    if regime:
        props["regime"] = regime
    if coherence is not None:
        props["coherence"] = coherence
    
    if tags:
        props["tags"] = tags
    if metadata:
        props["metadata"] = metadata
    
    # Build properties string (using ${param} format for substitution)
    props_str = ", ".join(f"{k}: ${{{k}}}" for k in props.keys())
    
    cypher = f"""
        MERGE (d:Discovery {{id: ${{id}}}})
        SET d += {{{props_str}}}
        RETURN d
    """
    
    return cypher, props


def create_agent_node(
    agent_id: str,
    purpose: Optional[str] = None,
    status: str = "active",
    created_at: Optional[datetime] = None,
    updated_at: Optional[datetime] = None,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query to create/update an Agent node.
    
    Returns:
        (cypher_query, params_dict)
    """
    props = {
        "id": agent_id,
        "status": status,
    }
    
    if purpose:
        props["purpose"] = purpose
    if created_at:
        props["created_at"] = created_at.isoformat()
    if updated_at:
        props["updated_at"] = updated_at.isoformat()
    
    props_str = ", ".join(f"{k}: ${{{k}}}" for k in props.keys())
    
    cypher = f"""
        MERGE (a:Agent {{id: ${{id}}}})
        SET a += {{{props_str}}}
        RETURN a
    """
    
    return cypher, props


def create_authored_edge(
    agent_id: str,
    discovery_id: str,
    at: Optional[datetime] = None,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query to create AUTHORED edge.
    
    Returns:
        (cypher_query, params_dict)
    """
    props = {}
    if at:
        props["at"] = at.isoformat()
    
    if props:
        props_str = " {" + ", ".join(f"{k}: ${k}" for k in props.keys()) + "}"
    else:
        props_str = ""
    
    params = {"agent_id": agent_id, "discovery_id": discovery_id, **props}
    
    cypher = f"""
        MATCH (a:Agent {{id: ${{agent_id}}}})
        MATCH (d:Discovery {{id: ${{discovery_id}}}})
        MERGE (a)-[r:AUTHORED{props_str}]->(d)
        RETURN r
    """
    
    return cypher, params


def create_responds_to_edge(
    from_discovery_id: str,
    to_discovery_id: str,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query to create RESPONDS_TO edge.
    
    Returns:
        (cypher_query, params_dict)
    """
    params = {
        "from_id": from_discovery_id,
        "to_id": to_discovery_id,
    }
    
    cypher = """
        MATCH (d1:Discovery {id: ${from_id}})
        MATCH (d2:Discovery {id: ${to_id}})
        MERGE (d1)-[r:RESPONDS_TO]->(d2)
        RETURN r
    """
    
    return cypher, params


def create_related_to_edge(
    from_discovery_id: str,
    to_discovery_id: str,
    strength: Optional[float] = None,
    reason: Optional[str] = None,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query to create RELATED_TO edge.
    
    Returns:
        (cypher_query, params_dict)
    """
    props = {}
    if strength is not None:
        props["strength"] = strength
    if reason:
        props["reason"] = reason
    
    params = {
        "from_id": from_discovery_id,
        "to_id": to_discovery_id,
        **props,
    }
    
    # Build props string with parameter placeholders
    # Note: f-string with double braces {{}} preserves literal ${param_name} for regex replacement
    if props:
        props_items = ", ".join(f"{k}: ${{{k}}}" for k in props.keys())
        props_str = f" {{{props_items}}}"
    else:
        props_str = ""
    
    # Use f-string here because we need to interpolate props_str
    # Double braces {{}} escape to literal braces, preserving ${param_name} placeholders
    # This is equivalent to raw strings but allows dynamic props_str interpolation
    cypher = f"""
        MATCH (d1:Discovery {{id: ${{from_id}}}})
        MATCH (d2:Discovery {{id: ${{to_id}}}})
        MERGE (d1)-[r:RELATED_TO{props_str}]->(d2)
        RETURN r
    """
    
    return cypher, params


def create_tagged_edge(
    discovery_id: str,
    tag_name: str,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query to create TAGGED edge (and Tag node if needed).
    
    Returns:
        (cypher_query, params_dict)
    """
    params = {
        "discovery_id": discovery_id,
        "tag_name": tag_name,
    }
    
    cypher = """
        MATCH (d:Discovery {id: ${discovery_id}})
        MERGE (t:Tag {name: ${tag_name}})
        MERGE (d)-[r:TAGGED]->(t)
        RETURN r
    """
    
    return cypher, params


def create_supersedes_edge(
    new_discovery_id: str,
    old_discovery_id: str,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query to create SUPERSEDES edge.
    new_discovery_id supersedes old_discovery_id.

    Returns:
        (cypher_query, params_dict)
    """
    params = {
        "new_id": new_discovery_id,
        "old_id": old_discovery_id,
    }

    cypher = """
        MATCH (new:Discovery {id: ${new_id}})
        MATCH (old:Discovery {id: ${old_id}})
        MERGE (new)-[r:SUPERSEDES]->(old)
        RETURN r
    """

    return cypher, params


def query_response_chain(
    discovery_id: str,
    max_depth: int = 10,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query to traverse response chain.
    
    Returns:
        (cypher_query, params_dict)
    """
    params = {"discovery_id": discovery_id}
    
    cypher = f"""
        MATCH path = (d:Discovery)-[:RESPONDS_TO*1..{max_depth}]->(root:Discovery)
        WHERE d.id = ${{discovery_id}}
        RETURN path
    """
    
    return cypher, params


def query_cross_agent_knowledge_flow(
    limit: int = 100,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query to find cross-agent knowledge flow.
    
    Returns:
        (cypher_query, params_dict)
    """
    params = {}
    
    cypher = f"""
        MATCH (a1:Agent)-[:AUTHORED]->(d1:Discovery)-[:RELATED_TO]-(d2:Discovery)<-[:AUTHORED]-(a2:Agent)
        WHERE a1.id <> a2.id
        RETURN a1.id AS from_agent, a2.id AS to_agent, count(*) AS shared_insights
        ORDER BY shared_insights DESC
        LIMIT {limit}
    """
    
    return cypher, {}


def query_entropy_work_correlation(
    agent_id: str,
    min_entropy: float = 0.7,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query: What was agent working on when entropy peaked?
    
    Returns:
        (cypher_query, params_dict)
    """
    params = {
        "agent_id": agent_id,
        "min_entropy": min_entropy,
    }
    
    cypher = """
        MATCH (state:Discovery {type: 'self_observation', agent_id: ${agent_id}})
        WHERE state.eisv_s > ${min_entropy}
        MATCH (state)-[:TEMPORALLY_NEAR]->(work:Discovery)
        WHERE work.type <> 'self_observation'
        RETURN state.timestamp, state.eisv_s, work.summary
        ORDER BY state.timestamp DESC
    """
    
    return cypher, params


def query_unresolved_questions_with_entropy(
    min_entropy: float = 0.5,
    limit: int = 50,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query: Find unresolved questions with high-entropy context.
    
    Returns:
        (cypher_query, params_dict)
    """
    params = {
        "min_entropy": min_entropy,
    }
    
    cypher = f"""
        MATCH (q:Discovery {{type: 'question', status: 'open'}})
        OPTIONAL MATCH (q)<-[:RESPONDS_TO]-(state:Discovery {{type: 'self_observation'}})
        WHERE state.eisv_s > ${{min_entropy}}
        RETURN q.summary, q.agent_id, state.eisv_s AS context_entropy
        ORDER BY context_entropy DESC
        LIMIT {limit}
    """
    
    return cypher, params


def query_agent_discoveries(
    agent_id: str,
    discovery_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> tuple[str, Dict[str, Any]]:
    """
    Build Cypher query to get discoveries for an agent.
    
    Returns:
        (cypher_query, params_dict)
    """
    params = {"agent_id": agent_id}
    conditions = ["d.agent_id = $agent_id"]
    
    if discovery_type:
        params["discovery_type"] = discovery_type
        conditions.append("d.type = $discovery_type")
    
    if status:
        params["status"] = status
        conditions.append("d.status = $status")
    
    where_clause = " AND ".join(conditions)
    
    # Add limit to params (required for parameterized query)
    params["limit"] = limit
    
    cypher = f"""
        MATCH (d:Discovery)
        WHERE {where_clause}
        RETURN d
        ORDER BY d.timestamp DESC
        LIMIT ${{limit}}
    """
    
    return cypher, params


def create_indexes(graph_name: str = "governance_graph") -> List[tuple[str, Dict[str, Any]]]:
    """
    Build SQL statements to create indexes on the AGE graph schema.

    Note: AGE stores label names with mixed case in quoted form, so we must
    quote them here (e.g., "Discovery" not Discovery) to match the actual
    relation names like governance_graph."Discovery".

    Returns:
        List of (sql_statement, params_dict) tuples
    """
    indexes = [
        # Discovery indexes (quoted to match AGE's mixed-case labels)
        (f'CREATE INDEX IF NOT EXISTS idx_discovery_agent ON {graph_name}."Discovery"(agent_id)', {}),
        (f'CREATE INDEX IF NOT EXISTS idx_discovery_type ON {graph_name}."Discovery"(type)', {}),
        (f'CREATE INDEX IF NOT EXISTS idx_discovery_timestamp ON {graph_name}."Discovery"(timestamp)', {}),
        (f'CREATE INDEX IF NOT EXISTS idx_discovery_severity ON {graph_name}."Discovery"(severity)', {}),
        (f'CREATE INDEX IF NOT EXISTS idx_discovery_status ON {graph_name}."Discovery"(status)', {}),

        # EISV indexes (for self_observation type)
        (f'CREATE INDEX IF NOT EXISTS idx_eisv_e ON {graph_name}."Discovery"(eisv_e) WHERE type = \'self_observation\'', {}),
        (f'CREATE INDEX IF NOT EXISTS idx_eisv_s ON {graph_name}."Discovery"(eisv_s) WHERE type = \'self_observation\'', {}),
        (f'CREATE INDEX IF NOT EXISTS idx_eisv_v ON {graph_name}."Discovery"(eisv_v) WHERE type = \'self_observation\'', {}),

        # Agent indexes
        (f'CREATE INDEX IF NOT EXISTS idx_agent_id ON {graph_name}."Agent"(id)', {}),
        (f'CREATE INDEX IF NOT EXISTS idx_agent_status ON {graph_name}."Agent"(status)', {}),

        # Tag indexes
        (f'CREATE INDEX IF NOT EXISTS idx_tag_name ON {graph_name}."Tag"(name)', {}),
    ]

    return indexes

