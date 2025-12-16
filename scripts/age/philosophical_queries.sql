-- ============================================================================
-- PHILOSOPHICAL GRAPH QUERIES FOR GOVERNANCE
-- ============================================================================
-- These queries support complex reasoning patterns that emerge as agents
-- engage in dialectic, build on each other's discoveries, and develop
-- philosophical depth over time.
--
-- Usage:
--   docker exec -i postgres-age psql -U postgres -d postgres < scripts/age/philosophical_queries.sql
--
-- Prerequisites:
--   - AGE container running
--   - Data imported via export_knowledge_sqlite_to_age.py

LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- ============================================================================
-- 1. KNOWLEDGE PROVENANCE: "Where did this idea come from?"
-- ============================================================================
-- Trace the origin of a discovery through response chains.
-- Philosophy: Understanding the genealogy of thought.

-- Find the root discovery that started a thread
SELECT * FROM cypher('governance', $$
  MATCH path = (leaf:Discovery)-[:RESPONSE_TO*0..10]->(root:Discovery)
  WHERE NOT (root)-[:RESPONSE_TO]->()
  RETURN root.id AS origin, 
         root.summary AS original_insight,
         root.agent_id AS originator,
         length(path) AS generations
  ORDER BY generations DESC
  LIMIT 20
$$) AS (origin agtype, original_insight agtype, originator agtype, generations agtype);

-- ============================================================================
-- 2. DIALECTIC EVOLUTION: "How did this synthesis emerge?"
-- ============================================================================
-- Track how thesis → antithesis → synthesis patterns play out.

-- Find dialectic sessions that reached synthesis
SELECT * FROM cypher('governance', $$
  MATCH (s:DialecticSession {status: 'resolved'})-[:HAS_MESSAGE]->(m:DialecticMessage)
  WHERE m.message_type = 'synthesis'
  RETURN s.id AS session,
         m.reasoning AS synthesis_reasoning,
         m.agent_id AS synthesizer
  LIMIT 10
$$) AS (session agtype, synthesis_reasoning agtype, synthesizer agtype);

-- Full dialectic thread for a session (thesis → antithesis → synthesis)
-- Replace $SESSION_ID with actual session ID
-- SELECT * FROM cypher('governance', $$
--   MATCH (s:DialecticSession {id: '$SESSION_ID'})-[:HAS_MESSAGE]->(m:DialecticMessage)
--   RETURN m.seq AS sequence, 
--          m.message_type AS phase,
--          m.agent_id AS speaker,
--          m.reasoning AS argument
--   ORDER BY m.seq
-- $$) AS (sequence agtype, phase agtype, speaker agtype, argument agtype);

-- ============================================================================
-- 3. AGENT INTELLECTUAL GENEALOGY: "Who learned from whom?"
-- ============================================================================
-- Map the lineage of agents and their intellectual inheritance.

-- Find agent spawn trees (parent → child relationships)
SELECT * FROM cypher('governance', $$
  MATCH (ancestor:Agent)-[:SPAWNED*1..5]->(descendant:Agent)
  RETURN ancestor.id AS intellectual_parent,
         descendant.id AS intellectual_child,
         descendant.notes AS child_purpose
  LIMIT 20
$$) AS (intellectual_parent agtype, intellectual_child agtype, child_purpose agtype);

-- Agents that share conceptual DNA (same tags)
SELECT * FROM cypher('governance', $$
  MATCH (a1:Agent)-[:HAS_TAG]->(t:Tag)<-[:HAS_TAG]-(a2:Agent)
  WHERE a1.id <> a2.id
  RETURN a1.id AS agent1, a2.id AS agent2, t.name AS shared_concept
  LIMIT 30
$$) AS (agent1 agtype, agent2 agtype, shared_concept agtype);

-- ============================================================================
-- 4. CONCEPTUAL CLUSTERING: "What ideas are connected?"
-- ============================================================================
-- Find discoveries that share conceptual DNA through tags.

-- Discoveries sharing multiple tags (strong conceptual overlap)
SELECT * FROM cypher('governance', $$
  MATCH (d1:Discovery)-[:HAS_TAG]->(t:Tag)<-[:HAS_TAG]-(d2:Discovery)
  WHERE d1.id < d2.id
  WITH d1, d2, count(t) AS shared_tags
  WHERE shared_tags >= 2
  RETURN d1.id AS discovery1, 
         d1.summary AS summary1,
         d2.id AS discovery2,
         d2.summary AS summary2,
         shared_tags
  ORDER BY shared_tags DESC
  LIMIT 20
$$) AS (discovery1 agtype, summary1 agtype, discovery2 agtype, summary2 agtype, shared_tags agtype);

-- ============================================================================
-- 5. INFLUENCE MAPPING: "Who shaped this understanding?"
-- ============================================================================
-- Track which agents contributed to areas of knowledge.

-- Most influential agents (by discovery count)
SELECT * FROM cypher('governance', $$
  MATCH (d:Discovery)
  RETURN d.agent_id AS agent, count(d) AS contributions
  ORDER BY contributions DESC
  LIMIT 15
$$) AS (agent agtype, contributions agtype);

-- Cross-agent knowledge flow (responses to other agents' discoveries)
SELECT * FROM cypher('governance', $$
  MATCH (d1:Discovery)-[:RESPONSE_TO]->(d2:Discovery)
  WHERE d1.agent_id <> d2.agent_id
  RETURN d2.agent_id AS inspired_by, 
         d1.agent_id AS built_upon_by,
         count(*) AS interactions
  ORDER BY interactions DESC
  LIMIT 20
$$) AS (inspired_by agtype, built_upon_by agtype, interactions agtype);

-- ============================================================================
-- 6. TEMPORAL REASONING: "How did understanding evolve?"
-- ============================================================================
-- Track the evolution of concepts over time.

-- Discovery timeline by type
SELECT * FROM cypher('governance', $$
  MATCH (d:Discovery)
  RETURN d.type AS discovery_type, count(d) AS total
  ORDER BY total DESC
$$) AS (discovery_type agtype, total agtype);

-- Agent activity over time (most recently active)
SELECT * FROM cypher('governance', $$
  MATCH (a:Agent)
  WHERE a.status = 'active'
  RETURN a.id AS agent, 
         a.last_update AS last_active,
         a.total_updates AS depth_of_engagement
  ORDER BY a.last_update DESC
  LIMIT 20
$$) AS (agent agtype, last_active agtype, depth_of_engagement agtype);

-- ============================================================================
-- 7. PHILOSOPHICAL DEPTH: "What questions remain unanswered?"
-- ============================================================================
-- Find open questions and unresolved threads.

-- Discoveries that are questions without responses
SELECT * FROM cypher('governance', $$
  MATCH (q:Discovery {type: 'question'})
  WHERE NOT ()-[:RESPONSE_TO]->(q)
  RETURN q.id AS open_question,
         q.summary AS question_text,
         q.agent_id AS asker
  LIMIT 20
$$) AS (open_question agtype, question_text agtype, asker agtype);

-- Discoveries with most engagement (most responses)
SELECT * FROM cypher('governance', $$
  MATCH (root:Discovery)<-[:RESPONSE_TO]-(response:Discovery)
  WITH root, count(response) AS response_count
  WHERE response_count >= 2
  RETURN root.id AS seminal_discovery,
         root.summary AS insight,
         root.agent_id AS originator,
         response_count AS engagement
  ORDER BY engagement DESC
  LIMIT 15
$$) AS (seminal_discovery agtype, insight agtype, originator agtype, engagement agtype);

-- ============================================================================
-- 8. DIALECTIC HEALTH: "Are we reaching synthesis?"
-- ============================================================================
-- Analyze the quality of dialectic processes.

-- Dialectic session outcomes
SELECT * FROM cypher('governance', $$
  MATCH (s:DialecticSession)
  RETURN s.status AS outcome, count(s) AS sessions
  ORDER BY sessions DESC
$$) AS (outcome agtype, sessions agtype);

-- Sessions with most message depth (rich discussion)
SELECT * FROM cypher('governance', $$
  MATCH (s:DialecticSession)-[:HAS_MESSAGE]->(m:DialecticMessage)
  WITH s, count(m) AS message_count
  WHERE message_count >= 3
  RETURN s.id AS session, 
         s.status AS outcome,
         message_count AS discussion_depth
  ORDER BY discussion_depth DESC
  LIMIT 15
$$) AS (session agtype, outcome agtype, discussion_depth agtype);

-- ============================================================================
-- 9. META-COGNITION: "What do agents know about themselves?"
-- ============================================================================
-- Self-referential queries about the governance system.

-- Tags most used across all entities
SELECT * FROM cypher('governance', $$
  MATCH (t:Tag)<-[:HAS_TAG]-(entity)
  RETURN t.name AS concept, count(entity) AS usage
  ORDER BY usage DESC
  LIMIT 20
$$) AS (concept agtype, usage agtype);

-- Agents with self-documenting notes
SELECT * FROM cypher('governance', $$
  MATCH (a:Agent)
  WHERE a.notes IS NOT NULL AND a.notes <> ''
  RETURN a.id AS agent, a.notes AS self_description
  LIMIT 20
$$) AS (agent agtype, self_description agtype);

-- ============================================================================
-- SUMMARY STATISTICS
-- ============================================================================

SELECT '--- GRAPH SUMMARY ---' AS info;

SELECT * FROM cypher('governance', $$
  MATCH (n)
  RETURN labels(n)[0] AS node_type, count(n) AS total
  ORDER BY total DESC
$$) AS (node_type agtype, total agtype);


