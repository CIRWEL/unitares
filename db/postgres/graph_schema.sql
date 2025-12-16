-- Apache AGE Graph Schema for Governance MCP
-- Creates the graph and initial node/edge labels for knowledge graph queries
--
-- Run after schema.sql and partitions.sql:
--   docker exec -i postgres-age psql -U postgres -d governance < db/postgres/graph_schema.sql

-- Load AGE extension
LOAD 'age';
SET search_path = ag_catalog, core, audit, public;

-- Create the graph (idempotent)
SELECT create_graph('governance_graph');

-- =============================================================================
-- VERTEX LABELS (Node Types)
-- =============================================================================

-- Agent: Core identity node
SELECT create_vlabel('governance_graph', 'Agent');

-- Discovery: Knowledge/insight discovered by agents
SELECT create_vlabel('governance_graph', 'Discovery');

-- Tag: Categorization labels
SELECT create_vlabel('governance_graph', 'Tag');

-- DialecticSession: Multi-agent dialectic conversation
SELECT create_vlabel('governance_graph', 'DialecticSession');

-- DialecticMessage: Individual message in a dialectic
SELECT create_vlabel('governance_graph', 'DialecticMessage');

-- Concept: Abstract concept or topic
SELECT create_vlabel('governance_graph', 'Concept');

-- =============================================================================
-- EDGE LABELS (Relationship Types)
-- =============================================================================

-- Agent relationships
SELECT create_elabel('governance_graph', 'SPAWNED');          -- Agent -[:SPAWNED]-> Agent
SELECT create_elabel('governance_graph', 'COLLABORATED');     -- Agent -[:COLLABORATED]-> Agent

-- Discovery relationships
SELECT create_elabel('governance_graph', 'DISCOVERED');       -- Agent -[:DISCOVERED]-> Discovery
SELECT create_elabel('governance_graph', 'REFERENCES');       -- Discovery -[:REFERENCES]-> Discovery
SELECT create_elabel('governance_graph', 'TAGGED');           -- Discovery -[:TAGGED]-> Tag
SELECT create_elabel('governance_graph', 'ABOUT');            -- Discovery -[:ABOUT]-> Concept

-- Dialectic relationships
SELECT create_elabel('governance_graph', 'PARTICIPATED');     -- Agent -[:PARTICIPATED]-> DialecticSession
SELECT create_elabel('governance_graph', 'AUTHORED');         -- Agent -[:AUTHORED]-> DialecticMessage
SELECT create_elabel('governance_graph', 'IN_SESSION');       -- DialecticMessage -[:IN_SESSION]-> DialecticSession
SELECT create_elabel('governance_graph', 'REPLIED_TO');       -- DialecticMessage -[:REPLIED_TO]-> DialecticMessage

-- Concept relationships
SELECT create_elabel('governance_graph', 'RELATES_TO');       -- Concept -[:RELATES_TO]-> Concept
SELECT create_elabel('governance_graph', 'INTERESTED_IN');    -- Agent -[:INTERESTED_IN]-> Concept

-- =============================================================================
-- HELPER FUNCTIONS FOR GRAPH QUERIES
-- =============================================================================

-- Function to sync an agent from core.identities to the graph
CREATE OR REPLACE FUNCTION core.sync_agent_to_graph(p_agent_id TEXT)
RETURNS VOID AS $$
DECLARE
    v_exists BOOLEAN;
BEGIN
    -- Check if agent vertex exists
    EXECUTE format(
        $q$SELECT EXISTS(
            SELECT 1 FROM cypher('governance_graph', $$
                MATCH (a:Agent {agent_id: '%s'}) RETURN a
            $$) as (a agtype)
        )$q$, p_agent_id
    ) INTO v_exists;

    IF NOT v_exists THEN
        -- Create agent vertex
        EXECUTE format(
            $q$SELECT * FROM cypher('governance_graph', $$
                CREATE (a:Agent {
                    agent_id: '%s',
                    created_at: datetime()
                })
            $$) as (a agtype)$q$, p_agent_id
        );
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to record a SPAWNED relationship
CREATE OR REPLACE FUNCTION core.record_spawn(p_parent_id TEXT, p_child_id TEXT, p_reason TEXT DEFAULT NULL)
RETURNS VOID AS $$
BEGIN
    -- Ensure both agents exist
    PERFORM core.sync_agent_to_graph(p_parent_id);
    PERFORM core.sync_agent_to_graph(p_child_id);

    -- Create edge
    EXECUTE format(
        $q$SELECT * FROM cypher('governance_graph', $$
            MATCH (parent:Agent {agent_id: '%s'}), (child:Agent {agent_id: '%s'})
            CREATE (parent)-[:SPAWNED {reason: '%s', ts: datetime()}]->(child)
        $$) as (e agtype)$q$,
        p_parent_id, p_child_id, COALESCE(p_reason, 'unknown')
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION core.sync_agent_to_graph IS 'Sync agent identity to AGE graph';
COMMENT ON FUNCTION core.record_spawn IS 'Record agent spawn relationship in graph';
