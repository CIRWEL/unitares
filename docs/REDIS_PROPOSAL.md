# Redis Integration Proposal

## Current Architecture Analysis

### Current State Management

1. **In-Memory Caches** (Process-Local)
   - `_session_identities`: Session → agent_id bindings
   - `agent_metadata`: Agent metadata dict
   - `_uuid_prefix_index`: UUID prefix lookups
   - **Problem**: Lost on server restart, not shared across processes/servers

2. **File-Based Locking** (`state_locking.py`)
   - Uses `fcntl.flock()` for process coordination
   - **Problem**: Doesn't work across servers/machines
   - **Problem**: Stale lock detection requires PID checking

3. **Rate Limiting** (`knowledge_graph_age.py`)
   - Uses PostgreSQL `audit.rate_limits` table
   - **Problem**: Database overhead for high-frequency checks
   - **Problem**: Requires cleanup queries

4. **Session Storage**
   - PostgreSQL `core.sessions` table
   - **Problem**: No automatic TTL/expiration
   - **Problem**: Requires manual cleanup queries

## Redis Use Cases

### 1. **Distributed Session Cache** ⭐ HIGH VALUE

**Current**: In-memory `_session_identities` dict, lost on restart

**Redis Solution**:
```python
# Session → agent_id bindings with TTL
redis.setex(f"session:{session_key}", ttl=3600, value=agent_id)
```

**Benefits**:
- ✅ Survives server restarts
- ✅ Shared across multiple MCP server instances
- ✅ Automatic expiration (TTL)
- ✅ Fast lookups (< 1ms vs PostgreSQL ~5-10ms)
- ✅ Critical for SSE multi-client scenarios

**Impact**: 
- **SSE reconnection**: Sessions persist across server restarts
- **Multi-server**: Load-balanced MCP servers share session state
- **Performance**: 10x faster than PostgreSQL for session lookups

---

### 2. **Distributed Locking** ⭐ HIGH VALUE

**Current**: File-based `fcntl.flock()` - single-server only

**Redis Solution**:
```python
# Distributed locks with automatic expiration
lock = redis.lock("agent_state:lock:{agent_id}", timeout=30, sleep=0.1)
with lock:
    # Modify agent state
```

**Benefits**:
- ✅ Works across multiple servers
- ✅ Automatic expiration (prevents deadlocks)
- ✅ Non-blocking with retry logic
- ✅ No stale lock cleanup needed

**Impact**:
- **Multi-server deployments**: Enable horizontal scaling
- **State consistency**: Prevent race conditions across servers
- **Reliability**: Automatic lock release on failure

---

### 3. **Rate Limiting** ⭐ MEDIUM VALUE

**Current**: PostgreSQL queries for every rate limit check

**Redis Solution**:
```python
# Sliding window rate limiting
key = f"rate_limit:kg_store:{agent_id}"
count = redis.incr(key)
if count == 1:
    redis.expire(key, 3600)  # 1 hour window
if count > 20:
    raise RateLimitExceeded()
```

**Benefits**:
- ✅ 100x faster than PostgreSQL (in-memory)
- ✅ Atomic operations (no race conditions)
- ✅ Automatic expiration (no cleanup needed)
- ✅ Built-in sliding window support

**Impact**:
- **Performance**: Reduce database load for high-frequency checks
- **Scalability**: Handle thousands of rate limit checks/second
- **Cost**: Lower PostgreSQL connection pool usage

---

### 4. **Agent Metadata Cache** ⭐ MEDIUM VALUE

**Current**: In-memory `agent_metadata` dict, reloaded from PostgreSQL

**Redis Solution**:
```python
# Cache agent metadata with invalidation
metadata = redis.get(f"agent_meta:{agent_id}")
if not metadata:
    metadata = load_from_postgres(agent_id)
    redis.setex(f"agent_meta:{agent_id}", ttl=300, value=json.dumps(metadata))
```

**Benefits**:
- ✅ Shared cache across servers
- ✅ Reduces PostgreSQL load
- ✅ TTL-based invalidation
- ✅ Fast lookups for `list_agents()`, `get_agent_metadata()`

**Impact**:
- **Performance**: Faster agent metadata queries
- **Database load**: Reduce PostgreSQL queries by 80-90%
- **Consistency**: Cache invalidation on updates

---

### 5. **Pub/Sub for Real-Time Updates** ⭐ LOW-MEDIUM VALUE

**Use Case**: Multi-agent coordination, real-time notifications

**Redis Solution**:
```python
# Publish agent state changes
redis.publish("agent:updates", json.dumps({
    "agent_id": agent_id,
    "event": "state_changed",
    "metrics": {...}
}))

# Subscribe in other processes/servers
pubsub = redis.pubsub()
pubsub.subscribe("agent:updates")
```

**Benefits**:
- ✅ Real-time event propagation
- ✅ Decoupled architecture
- ✅ Multi-agent coordination

**Impact**:
- **Future feature**: Real-time agent monitoring dashboard
- **Coordination**: Agents can react to other agents' state changes
- **Scalability**: Event-driven architecture

---

## Implementation Strategy

### Phase 1: Session Cache + Distributed Locking (Critical)

**Priority**: HIGH - Enables multi-server deployments

**Files to Modify**:
- `src/mcp_handlers/identity.py` - Replace `_session_identities` with Redis
- `src/state_locking.py` - Replace file locks with Redis locks
- `src/db/redis_backend.py` - New Redis backend module

**Estimated Effort**: 2-3 days

---

### Phase 2: Rate Limiting (Performance)

**Priority**: MEDIUM - Improves performance, reduces DB load

**Files to Modify**:
- `src/storage/knowledge_graph_age.py` - Replace PostgreSQL rate limiting
- `src/rate_limiter.py` - New Redis-based rate limiter

**Estimated Effort**: 1 day

---

### Phase 3: Agent Metadata Cache (Optimization)

**Priority**: MEDIUM - Reduces database load

**Files to Modify**:
- `src/mcp_server_std.py` - Cache agent metadata in Redis
- `src/mcp_handlers/lifecycle.py` - Invalidate cache on updates

**Estimated Effort**: 1-2 days

---

### Phase 4: Pub/Sub (Future Enhancement)

**Priority**: LOW - Nice to have, not critical

**Estimated Effort**: 2-3 days

---

## Redis Backend Design

### Abstraction Layer

```python
# src/db/redis_backend.py
class RedisBackend:
    """Redis backend for caching, locking, and rate limiting"""
    
    async def get_session(self, session_key: str) -> Optional[str]:
        """Get agent_id for session"""
        
    async def set_session(self, session_key: str, agent_id: str, ttl: int = 3600):
        """Set session binding with TTL"""
        
    async def acquire_lock(self, key: str, timeout: int = 30) -> Lock:
        """Acquire distributed lock"""
        
    async def check_rate_limit(self, key: str, limit: int, window: int) -> bool:
        """Check sliding window rate limit"""
        
    async def cache_get(self, key: str) -> Optional[Any]:
        """Get cached value"""
        
    async def cache_set(self, key: str, value: Any, ttl: int = 300):
        """Set cached value with TTL"""
```

### Configuration

```python
# Environment variables
REDIS_URL=redis://localhost:6379/0
REDIS_SESSION_TTL=3600  # 1 hour
REDIS_METADATA_TTL=300  # 5 minutes
REDIS_LOCK_TIMEOUT=30   # 30 seconds
REDIS_RATE_LIMIT_WINDOW=3600  # 1 hour
```

---

## Migration Path

### Backward Compatibility

1. **Hybrid Mode**: Use Redis if available, fallback to current implementation
2. **Gradual Migration**: Feature flags for Redis vs PostgreSQL
3. **Data Sync**: Keep PostgreSQL as source of truth, Redis as cache

### Example Implementation

```python
# Hybrid session lookup
async def get_session_binding(session_key: str):
    # Try Redis first
    if redis_available:
        agent_id = await redis_backend.get_session(session_key)
        if agent_id:
            return agent_id
    
    # Fallback to PostgreSQL
    return await postgres_backend.get_session(session_key)
```

---

## Performance Impact

### Current (PostgreSQL Only)
- Session lookup: ~5-10ms
- Rate limit check: ~3-5ms
- Lock acquisition: ~1-2ms (file-based, single-server)

### With Redis
- Session lookup: ~0.5-1ms (10x faster)
- Rate limit check: ~0.1-0.5ms (10-50x faster)
- Lock acquisition: ~1-2ms (works across servers)

### Database Load Reduction
- Session queries: **-90%** (moved to Redis)
- Rate limit queries: **-95%** (moved to Redis)
- Metadata queries: **-80%** (cached in Redis)

---

## Operational Considerations

### Redis Deployment Options

1. **Docker Compose** (Development)
   ```yaml
   redis:
     image: redis:7-alpine
     ports:
       - "6379:6379"
   ```

2. **Managed Redis** (Production)
   - AWS ElastiCache
   - Redis Cloud
   - Azure Cache for Redis

3. **High Availability**
   - Redis Sentinel (automatic failover)
   - Redis Cluster (sharding)

### Monitoring

- **Metrics**: Hit rate, miss rate, memory usage
- **Alerts**: Redis down, high memory usage, connection errors
- **Health Checks**: `PING` command, connection pool status

---

## Cost-Benefit Analysis

### Benefits
- ✅ **Multi-server support**: Enable horizontal scaling
- ✅ **Performance**: 10-50x faster for cached operations
- ✅ **Reliability**: Survives server restarts
- ✅ **Scalability**: Handle higher load with same hardware

### Costs
- ⚠️ **Additional infrastructure**: Redis server/cluster
- ⚠️ **Complexity**: Another system to manage
- ⚠️ **Memory**: Redis memory usage (typically 100MB-1GB)

### ROI
- **High** for multi-server deployments
- **Medium** for single-server (performance gains)
- **Low** for small deployments (< 100 agents)

---

## Recommendation

**Start with Phase 1 (Session Cache + Distributed Locking)**:
- Critical for multi-server deployments
- High impact, low risk
- Enables horizontal scaling

**Defer Phase 2-4** until:
- Multi-server deployment is needed
- Performance becomes a bottleneck
- Real-time features are required

---

## Next Steps

1. **Create Redis backend module** (`src/db/redis_backend.py`)
2. **Implement session cache** (replace `_session_identities`)
3. **Implement distributed locking** (replace file locks)
4. **Add Redis to docker-compose** (development)
5. **Add feature flags** (gradual rollout)
6. **Add monitoring** (health checks, metrics)

