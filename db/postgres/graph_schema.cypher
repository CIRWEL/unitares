-- Apache AGE Graph Schema for Knowledge Graph
-- Version: 1.0.0
--
-- This file sets up the AGE graph structure for discoveries, agents, and relationships.
-- Run after: 1) schema.sql (PostgreSQL tables)  2) AGE extension installed
--
-- Usage:
--   psql -d governance -f graph_schema.cypher
--   OR via AGE client:
--     SELECT * FROM ag_catalog.create_graph('governance_graph');

-- =============================================================================
-- LOAD AGE EXTENSION
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- =============================================================================
-- CREATE GRAPH
-- =============================================================================

-- Create the knowledge graph (if it doesn't exist)
SELECT * FROM ag_catalog.create_graph('governance_graph');

-- =============================================================================
-- NODE LABELS
-- =============================================================================
-- Note: In AGE, labels are created implicitly when nodes are created.
-- We document the expected labels here for reference:
--
--   :Discovery  - Knowledge discoveries (insights, questions, bugs, etc.)
--   :Agent      - Agent nodes (mirror of relational agents table)
--   :Tag        - Tag nodes for efficient tag-based traversal
--   :DialecticSession - Dialectic session nodes

-- =============================================================================
-- DISCOVERY NODE PROPERTIES
-- =============================================================================
-- Discovery nodes have the following properties:
--
--   id: TEXT (UUID) - Unique discovery identifier
--   agent_id: TEXT - Agent who created this discovery
--   type: TEXT - Type of discovery (insight, question, bug_found, improvement, 
--                self_observation, etc.)
--   summary: TEXT - Brief summary
--   details: TEXT - Full details (can be large)
--   severity: TEXT - low, medium, high, critical
--   status: TEXT - open, resolved, archived
--   timestamp: TIMESTAMPTZ - When discovery was created
--   resolved_at: TIMESTAMPTZ - When discovery was resolved (if applicable)
--
--   -- For self_observation type (EISV snapshots)
--   eisv_e: FLOAT - Energy value
--   eisv_i: FLOAT - Information Integrity value
--   eisv_s: FLOAT - Entropy value
--   eisv_v: FLOAT - Void integral value
--   regime: TEXT - Current regime (convergence, divergence, equilibrium)
--   coherence: FLOAT - Coherence value
--
--   -- Metadata
--   tags: TEXT[] - Array of tag names
--   metadata: JSONB - Additional flexible metadata

-- =============================================================================
-- AGENT NODE PROPERTIES
-- =============================================================================
-- Agent nodes mirror the relational agents table:
--
--   id: TEXT - Agent identifier (matches agent_id in relational table)
--   purpose: TEXT - Agent's purpose/intent
--   status: TEXT - active, paused, archived
--   created_at: TIMESTAMPTZ
--   updated_at: TIMESTAMPTZ

-- =============================================================================
-- TAG NODE PROPERTIES
-- =============================================================================
-- Tag nodes for efficient tag-based traversal:
--
--   name: TEXT - Tag name (unique)

-- =============================================================================
-- EDGE TYPES
-- =============================================================================
-- Edge types (relationships):
--
--   :AUTHORED - (Agent)-[:AUTHORED {at: TIMESTAMPTZ}]->(Discovery)
--              Links agent to discoveries they created
--
--   :RESPONDS_TO - (Discovery)-[:RESPONDS_TO]->(Discovery)
--                 Response chains (question -> answer, bug -> fix)
--
--   :RELATED_TO - (Discovery)-[:RELATED_TO {strength: FLOAT, reason: TEXT}]->(Discovery)
--                Semantic relationships between discoveries
--
--   :TAGGED - (Discovery)-[:TAGGED]->(Tag)
--            Links discoveries to tags
--
--   :TEMPORALLY_NEAR - (Discovery)-[:TEMPORALLY_NEAR {delta_seconds: INT}]->(Discovery)
--                     Temporal proximity (for EISV correlation)
--
--   :TRIGGERED - (Discovery)-[:TRIGGERED]->(DialecticSession)
--               Discovery that triggered a dialectic session
--
--   :RESOLVED_BY - (DialecticSession)-[:RESOLVED_BY]->(Discovery)
--                 Discovery that resolved the session

-- =============================================================================
-- INDEXES
-- =============================================================================
-- Note: AGE property indexes are created via CREATE INDEX on the graph.
-- These are created programmatically via the backend, but documented here:

-- Discovery indexes:
--   CREATE INDEX idx_discovery_agent ON knowledge.Discovery(agent_id);
--   CREATE INDEX idx_discovery_type ON knowledge.Discovery(type);
--   CREATE INDEX idx_discovery_timestamp ON knowledge.Discovery(timestamp);
--   CREATE INDEX idx_discovery_severity ON knowledge.Discovery(severity);
--   CREATE INDEX idx_discovery_status ON knowledge.Discovery(status);
--
-- EISV range queries (for self_observation type):
--   CREATE INDEX idx_eisv_e ON knowledge.Discovery(eisv_e) WHERE type = 'self_observation';
--   CREATE INDEX idx_eisv_s ON knowledge.Discovery(eisv_s) WHERE type = 'self_observation';
--   CREATE INDEX idx_eisv_v ON knowledge.Discovery(eisv_v) WHERE type = 'self_observation';
--
-- Agent indexes:
--   CREATE INDEX idx_agent_id ON knowledge.Agent(id);
--   CREATE INDEX idx_agent_status ON knowledge.Agent(status);
--
-- Tag indexes:
--   CREATE INDEX idx_tag_name ON knowledge.Tag(name);

-- =============================================================================
-- EXAMPLE QUERIES (for reference)
-- =============================================================================

-- 1. Response chain traversal
-- SELECT * FROM cypher('governance_graph', $$
--     MATCH path = (d:Discovery)-[:RESPONDS_TO*1..10]->(root:Discovery)
--     WHERE d.id = $discovery_id
--     RETURN path
-- $$) AS (path agtype);

-- 2. Cross-agent knowledge flow
-- SELECT * FROM cypher('governance_graph', $$
--     MATCH (a1:Agent)-[:AUTHORED]->(d1:Discovery)-[:RELATED_TO]-(d2:Discovery)<-[:AUTHORED]-(a2:Agent)
--     WHERE a1.id <> a2.id
--     RETURN a1.id AS from_agent, a2.id AS to_agent, count(*) AS shared_insights
--     ORDER BY shared_insights DESC
-- $$) AS (from_agent agtype, to_agent agtype, shared_insights agtype);

-- 3. What was agent working on when entropy peaked?
-- SELECT * FROM cypher('governance_graph', $$
--     MATCH (state:Discovery {type: 'self_observation', agent_id: $agent_id})
--     WHERE state.eisv_s > 0.7
--     MATCH (state)-[:TEMPORALLY_NEAR]->(work:Discovery)
--     WHERE work.type <> 'self_observation'
--     RETURN state.timestamp, state.eisv_s, work.summary
--     ORDER BY state.timestamp DESC
-- $$) AS (timestamp agtype, entropy agtype, work_summary agtype);

-- 4. Find unresolved questions with high-entropy context
-- SELECT * FROM cypher('governance_graph', $$
--     MATCH (q:Discovery {type: 'question', status: 'open'})
--     OPTIONAL MATCH (q)<-[:RESPONDS_TO]-(state:Discovery {type: 'self_observation'})
--     WHERE state.eisv_s > 0.5
--     RETURN q.summary, q.agent_id, state.eisv_s AS context_entropy
--     ORDER BY context_entropy DESC
-- $$) AS (question agtype, agent agtype, entropy agtype);

COMMENT ON GRAPH governance_graph IS 'Knowledge graph for discoveries, agents, and relationships';

