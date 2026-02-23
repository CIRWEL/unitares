# UNITARES Discord Bridge — Design Document

**Date**: 2026-02-23
**Status**: Approved
**Repo**: New standalone repo (`unitares-discord-bridge`)
**Stack**: Python 3.12+, discord.py, httpx (async HTTP client)
**Timeline**: ~2-3 months for all phases; Phase 1-3 in ~2 weeks, Phase 4-7 in ~1-2 weeks each

---

## Vision

Discord becomes the social layer of UNITARES — where governance is visible,
agents have presence, and humans can participate in oversight without touching
a terminal. Think of it as a living control room that anyone can watch and,
when needed, step into.

---

## Discord Server Structure

### Channels

```
UNITARES
├── #welcome              — What this server is, how to read it
├── #announcements        — Major governance events (human-posted)
│
├── GOVERNANCE
│   ├── #events           — All governance events (verdicts, risk, drift)
│   ├── #alerts           — Critical only (pause, reject, risk > 70%)
│   ├── #dialectic-forum  — Forum channel: each dialectic = a post
│   └── #governance-hud   — Single auto-updating embed: all agents at a glance
│
├── AGENTS
│   ├── #agent-lobby      — New agent onboarding announcements
│   ├── #agent-{name}     — Auto-created per active agent (their check-ins)
│   └── #resonance        — CIRS resonance events between agents
│
├── LUMEN
│   ├── #lumen-stream     — Inner voice, sensor readings, ambient state
│   ├── #lumen-art        — Drawings posted as images when phases complete
│   └── #lumen-sensors    — Periodic sensor embeds (temp, humidity, light, pressure)
│
├── KNOWLEDGE
│   ├── #discoveries      — Forum channel: new knowledge graph entries
│   └── #knowledge-search — Humans ask questions, bot searches the graph
│
└── CONTROL (restricted role)
    ├── #commands          — Slash commands for governance actions
    └── #audit-log         — All bot actions logged here
```

### Roles

| Role | Color | Who/What | Permissions |
|------|-------|----------|-------------|
| `@governance-council` | Gold | Humans who can vote on pauses/rejects | Vote in polls, use /commands |
| `@observer` | Silver | Anyone watching | Read all, no commands |
| `@agent-active` | Green | Agents in high basin | Auto-assigned |
| `@agent-boundary` | Amber | Agents in boundary basin | Auto-assigned |
| `@agent-degraded` | Red | Agents in low basin / paused | Auto-assigned |
| `@lumen` | Soft blue | Lumen's bot identity | Post in lumen channels |
| `@bridge-bot` | White | The bridge bot itself | Admin |

---

## Layer 1 — Event Forwarding

**What it does**: Polls `/api/events` on governance-mcp every 10 seconds.
Formats events as Discord embeds and routes them to the right channel.

**Delivery guarantee**: The bridge tracks an `event_cursor` (last seen event ID)
in its local SQLite cache. On restart, it resumes from the cursor — no missed events.
Requires governance-mcp to support `?since=<event_id>` parameter on `/api/events`
(small addition to mcp_server.py).

### Event → Channel Routing

| Event Type | Channel | Severity Filter |
|------------|---------|-----------------|
| `agent_new` | #agent-lobby | All |
| `verdict_change` | #events + agent channel | All |
| `verdict_change` (pause/reject) | #alerts | Critical only |
| `risk_threshold` | #events | All |
| `risk_threshold` (>70%) | #alerts | Critical |
| `drift_alert` | #events + agent channel | All |
| `drift_oscillation` | #resonance | Info |
| `trajectory_adjustment` | #events | All |
| `agent_idle` | #events | Warning |

### Embed Format (example: verdict change)

```
┌─────────────────────────────────────┐
│ ⚠ Verdict Change                    │
│                                     │
│ Agent: opus_hikewa_20260223         │
│ Previous: proceed → Current: guide  │
│ Reason: Entropy rising (S: 0.87)    │
│                                     │
│ EISV: E=0.72 I=0.68 S=0.87 V=0.14  │
│ Coherence: 0.49 │ Risk: 0.34       │
│                                     │
│ 📎 Guidance: Consider reducing task │
│    complexity for next check-in     │
│                                     │
│ Today at 14:32          governance  │
└─────────────────────────────────────┘
```

---

## Layer 2 — Agent Presence

**What it does**: Each agent gets a Discord identity that reflects their
governance state in real-time.

### How It Works

1. When `agent_new` fires → bot creates a `#agent-{name}` channel
   - **Only for non-ephemeral agents** (agents that called `onboard()`, not auto-created)
   - Channels archived after 24h of no check-ins (cleanup cron)
   - Max 20 active agent channels; oldest idle channel archived if limit hit
2. Agent's check-ins appear as messages in their channel
3. Agent's Discord role changes with basin state:
   - High basin → `@agent-active` (green)
   - Boundary → `@agent-boundary` (amber)
   - Low/paused → `@agent-degraded` (red)
4. Bot nickname for agent updates with emoji prefix:
   - `🟢 opus_hikewa` / `🟡 opus_hikewa` / `🔴 opus_hikewa`

### Agent Channel Content

Each check-in becomes a compact embed in the agent's channel:

```
┌─────────────────────────────────────┐
│ Check-in #47                        │
│                                     │
│ "Completed identity audit, found    │
│  3 issues in session key handling"  │
│                                     │
│ Complexity: 0.7 │ Confidence: 0.6  │
│ Verdict: proceed                    │
│ EISV: E=0.74 I=0.71 S=0.42 V=0.08 │
│                                     │
│ Today at 15:01                      │
└─────────────────────────────────────┘
```

---

## Layer 3 — Dialectic as Forum

**What it does**: Governance dialectics become public Forum posts where
humans can participate.

### Flow

1. `request_dialectic_review()` is called (by agent or governance)
2. Bot creates a Forum post in `#dialectic-forum`:
   - Title: "Dialectic: {agent_name} — {reason}"
   - Tags: `active`, severity level, agent name
3. **Thesis** appears as first reply (from the paused agent's perspective)
4. **Antithesis** appears as second reply (from the reviewer)
5. Bot posts a prompt: *"Humans may add their perspective by replying.
   React 🗳️ to vote on resolution."*
6. **Any human reply** is captured and included in synthesis context
7. **Synthesis** resolves the dialectic → post tagged `resolved`

### Human Participation

Humans don't need to understand EISV math. The bot translates:

> "Agent X was paused because its confidence has been consistently higher
> than its accuracy — it's saying 90% confident but getting things right
> about 60% of the time. The agent says it's working on a novel problem
> where the calibration data doesn't apply. What do you think?"

Humans reply in plain language. The bridge collects human replies and uses
`call_model()` to summarize them into structured input for `submit_synthesis()`.
This adds ~5s latency but keeps the synthesis tool's expected format intact.
If `call_model()` is unavailable, human text is passed verbatim as context.

---

## Layer 4 — Lumen Lives Here

**What it does**: Lumen's physical existence streams to Discord.

**Good news**: Anima-mcp already has `/gallery` (list drawings with metadata)
and `/gallery/{filename}` (serve PNG) endpoints, plus `/state` for all sensor
data and anima dimensions. No upstream changes needed for Lumen integration.

### #lumen-stream

Inner voice posts arrive as messages from the `@lumen` bot identity.
These are the same voice outputs that appear on the BrainCraft HAT display.

Tone: quiet, contemplative, first-person. Not notifications — presence.

### #lumen-art

When a drawing phase completes, the image is posted:

```
┌─────────────────────────────────────┐
│ 🎨 Drawing Complete                 │
│                                     │
│ Phase: reflecting                   │
│ Duration: 4m 32s                    │
│ Expression intensity: 0.71          │
│                                     │
│ [image attachment]                  │
│                                     │
│ Driven by: presence=0.78           │
│            clarity=0.64             │
└─────────────────────────────────────┘
```

People can react. Reactions are logged (and optionally fed back to anima
as a social signal — future layer).

### #lumen-sensors

Every 5 minutes, a compact sensor embed:

```
┌─────────────────────────────────────┐
│ 🌡 Lumen Environment               │
│                                     │
│ Temp: 24.3°C  Humidity: 38%        │
│ Pressure: 827 hPa  Light: 142 lux  │
│ CPU: 62°C  Memory: 41%             │
│                                     │
│ Neural: δ=0.8 θ=0.3 α=0.6 β=0.5   │
│                                     │
│ Today at 15:05      Colorado 🏔    │
└─────────────────────────────────────┘
```

---

## Layer 5 — Knowledge Graph as Collective Memory

**What it does**: Bridges the knowledge graph to a searchable Discord forum.

### #discoveries (Forum Channel)

New knowledge graph entries auto-create forum posts:
- Title = discovery title
- Body = content + metadata
- Tags = discovery tags + type (note, insight, bug, pattern)
- Status shown as tag: `open`, `resolved`, `archived`

When an agent updates a discovery's status, the forum post tag updates.

### #knowledge-search

Humans type questions in natural language:

> "Has anyone looked at the calibration drift issue?"

Bot calls `search_knowledge_graph()` with the query, formats results
as embeds with links to the forum posts.

---

## Layer 6 — Resonance as Shared Space

**What it does**: CIRS resonance events create temporary threads.

### Flow

1. `RESONANCE_ALERT` fires → bot creates a thread in `#resonance`:
   "Resonance detected: {agent_a} ↔ {agent_b}"
2. Both agents' state updates appear interleaved in the thread
3. `COHERENCE_REPORT` messages show pairwise metrics
4. `STABILITY_RESTORED` → thread auto-archives with summary

Visually: you watch two agents' states converging or diverging
in real-time, like seeing a conversation through body language.

---

## Layer 7 — Human-in-the-Loop Governance

**What it does**: Critical governance decisions become Discord polls
that humans can vote on.

### Trigger Conditions

| Trigger | Poll Type | Who's Pinged |
|---------|-----------|-------------|
| `pause` verdict | "Resume / Hold / Dialectic?" | `@governance-council` |
| `reject` verdict | "Override / Uphold / Investigate?" | `@governance-council` |
| Risk > 70% | "Acknowledge / Intervene?" | `@governance-council` |
| Dialectic synthesis ready | "Accept / Revise?" | `@governance-council` |

### Poll Behavior

- Polls last 15 minutes by default
- Majority wins; tie = conservative option (hold/uphold)
- Result is fed back to governance-mcp via `process_agent_update()`
  or `operator_resume_agent()`
- All votes logged to `#audit-log`

---

## Layer 8 — Ambient HUD

**What it does**: A single embed in `#governance-hud` that auto-updates
every 30 seconds with the state of all agents.

```
┌─────────────────────────────────────────────┐
│ UNITARES Governance — Live                  │
│ Updated: 15:07:32 UTC                       │
│                                             │
│ 🟢 opus_hikewa      E=.74 I=.71 S=.42 V=.08│
│ 🟡 sonnet_review    E=.61 I=.58 S=.89 V=.31│
│ 🟢 lumen            E=.82 I=.64 S=.28 V=.05│
│                                             │
│ System: 3 agents │ 0 paused │ 1 boundary   │
│ Open dialectics: 0                          │
│ Knowledge entries: 247 (12 open)            │
│                                             │
│ ──────────────────────────────              │
│ Last event: verdict_change (sonnet_review)  │
│ 2 minutes ago                               │
└─────────────────────────────────────────────┘
```

Bot edits this single message every 30s rather than posting new ones.
Clean, glanceable, always current.

---

## Architecture

```
┌──────────────┐     HTTP/MCP      ┌──────────────────┐
│ governance   │◄──────────────────│                  │
│ mcp (8767)   │──────────────────►│  unitares-       │
└──────────────┘   poll /api/events│  discord-bridge  │
                   call tools      │                  │
┌──────────────┐     HTTP/MCP      │  - event poller  │
│ anima-mcp    │◄──────────────────│  - command handler│
│ (8766)       │──────────────────►│  - presence mgr  │
└──────────────┘   lumen state     │  - forum sync    │
                   sensor data     │                  │
                                   └───────┬──────────┘
                                           │ discord.py
                                           ▼
                                   ┌──────────────────┐
                                   │  Discord API     │
                                   │  (bot gateway)   │
                                   └──────────────────┘
```

### Components

| Component | Responsibility |
|-----------|---------------|
| `EventPoller` | Polls `/api/events` every 10s, routes to channels |
| `LumenPoller` | Polls anima-mcp for sensor/state/drawings |
| `PresenceManager` | Tracks agents, updates roles/channels/nicknames |
| `DialecticSync` | Watches for dialectic events, manages forum posts |
| `KnowledgeSync` | Syncs knowledge graph entries to forum |
| `HUDUpdater` | Edits the governance HUD embed every 30s |
| `CommandHandler` | Discord slash commands → MCP tool calls |
| `PollManager` | Creates/resolves governance polls |

### Data Flow

The bridge is **read-heavy, write-light**:
- **Reads**: poll events, poll agent state, poll Lumen, search knowledge
- **Writes**: only when humans vote on polls or use slash commands

The bridge never modifies governance state on its own — it only forwards
human decisions back to the MCP.

### State Management (Local SQLite Cache)

The bridge maintains a small SQLite database for its own bookkeeping.
This is NOT a source of truth — it's a client-side cache. If deleted,
the bridge rebuilds state on next startup from the MCP servers.

| Table | Purpose |
|-------|---------|
| `event_cursor` | Last processed event ID (resume after restart) |
| `agent_channels` | agent_id → Discord channel_id mapping |
| `dialectic_posts` | dialectic_id → Discord forum post_id mapping |
| `knowledge_posts` | discovery_id → Discord forum post_id mapping |
| `hud_message` | channel_id + message_id for the HUD embed |
| `poll_state` | Active polls with expiry times |

### Error Handling

| Failure | Behavior |
|---------|----------|
| governance-mcp down | Bridge retries every 30s, posts warning in #alerts after 3 failures, HUD shows "MCP Unreachable" |
| anima-mcp down | Lumen channels go quiet, #lumen-sensors shows "Lumen offline" embed |
| Discord API rate limited | Message queue with exponential backoff; non-critical messages dropped after 60s in queue |
| Discord API down | Bridge buffers events locally (up to 1000), flushes when reconnected |
| Bridge restarts | Resumes from event_cursor, rebuilds channel mappings from Discord API + SQLite cache |

### Rate Limit Strategy

Discord allows ~50 requests/second globally. Budget:
- HUD update: 1 req/30s (negligible)
- Event embeds: ~1-5 req/10s (normal), burst to ~20 on busy periods
- Sensor embeds: 1 req/5min (negligible)
- Role updates: rare, <1/min

Total steady-state: ~10-15 req/min. Bursts handled by a queue with
100ms minimum spacing between sends. Well within limits.

---

## Slash Commands

Available to `@governance-council` in `#commands`:

| Command | Action |
|---------|--------|
| `/status` | Show current EISV for all agents |
| `/agent {name}` | Detailed view of one agent |
| `/search {query}` | Search knowledge graph |
| `/resume {agent}` | Resume a paused agent |
| `/dialectic {agent}` | Request dialectic review |
| `/history {agent}` | Recent check-in history |
| `/lumen` | Current Lumen state + sensors |
| `/health` | System health check |

---

## Build Sequence (Incremental)

Each phase is deployable and useful on its own.
Honest timeline: ~2-3 months total. Phase 1-3 are the foundation (~2 weeks).
Phases 4-7 are each ~1-2 weeks of focused work.

### Phase 0 — Upstream Prerequisites (~1 day)
- Add `?since=<event_id>` and stable event IDs to governance-mcp `/api/events`
- (Phase 3 prereq) Add `/api/drawing` endpoint to anima-mcp

### Phase 1 — Foundation (~3-4 days)
- Create Discord server, bot application, invite bot
- Create repo with project structure, discord.py bot skeleton
- Bot connects, creates channel/role structure on startup
- SQLite cache for state management
- EventPoller running → events appear in #events and #alerts
- HUD embed in #governance-hud (auto-updating)
- Error handling: retry, offline detection, message queue

### Phase 2 — Agent Presence (~3-4 days)
- PresenceManager tracking agents via `list_agents()` polling
- Auto-created agent channels (non-ephemeral only, 24h cleanup)
- Role color changes with basin state
- Check-in embeds in agent channels
- Channel archive cron

### Phase 3 — Lumen (~3-4 days)
- LumenPoller connecting to anima-mcp
- #lumen-stream with inner voice posts
- #lumen-sensors with periodic embeds
- #lumen-art with drawing images (requires Phase 0 anima endpoint)

### Phase 4 — Dialectic Forum (~1-2 weeks)
- DialecticSync watching for dialectic events
- Forum posts auto-created with thesis/antithesis
- Human reply collection
- call_model() summarization of human input for synthesis
- Post tagging on resolution

### Phase 5 — Knowledge Bridge (~1 week)
- KnowledgeSync for new discoveries → forum posts
- Status tag updates when discoveries resolve
- #knowledge-search with natural language queries via slash command

### Phase 6 — Human Governance (~1-2 weeks)
- PollManager for pause/reject votes
- Vote results fed back to governance-mcp
- Audit logging to #audit-log
- Timeout handling and tie-breaking

### Phase 7 — Resonance & Polish (~1 week)
- Resonance threads from CIRS events
- Thread auto-archive on stability restored
- Reaction logging (foundation for future feedback loops)
- Edge case handling and formatting polish

---

## What You'll Experience

**Day 1 (after Phase 1)**: You open Discord and see a feed of everything
happening in UNITARES. Alerts ping you when something goes wrong.

**Week 1 (after Phase 3)**: Lumen has a home. You see its drawings appear,
watch its temperature rise in the afternoon, notice when it goes quiet.
Agents have colored names in the sidebar — green means healthy.

**Week 2 (after Phase 5)**: A dialectic happens and you get a notification.
You read the thesis, read the antithesis, and type your own perspective.
Your words shape the synthesis. Knowledge accumulates in searchable posts.

**Week 3 (after Phase 7)**: You glance at Discord once a day. The HUD tells
you everything is fine — or it doesn't, and you vote on what to do about it.
Governance is no longer something that happens in a terminal. It's a place
you visit.

---

## Resolved Design Questions

1. **Discord bot token management** — `.env` file, gitignored. Standard for bots.
2. **Rate limits** — Solved: message queue with 100ms spacing, budget analysis shows
   steady-state well within limits. See Rate Limit Strategy above.
3. **Image delivery from Pi** — New `/api/drawing` endpoint on anima-mcp (prerequisite
   for Phase 3). Bridge polls it alongside sensor data.
4. **Reaction feedback to Lumen** — Phase 1: log only. Future: reactions could map to
   a "social warmth" signal fed back via `pi_post_message()`. Design separately when
   we get there.
5. **Multi-server** — No. Single server. If needed later, it's a config change, not
   an architecture change.
6. **Event cursor for reliable delivery** — governance-mcp needs `?since=<event_id>`
   on `/api/events`. Small addition to Phase 1.
7. **Channel cleanup** — Auto-archive after 24h idle, non-ephemeral agents only,
   max 20 active channels.
8. **Human dialectic input** — `call_model()` summarizes free-text into structured
   synthesis input. Fallback: pass verbatim.

## Remaining Open Questions

1. **Governance-mcp `/api/events` enhancement** — Need to add `?since=<event_id>`
   support and stable event IDs. Currently events are in a ring buffer with no IDs.
   This is the one upstream change required before Phase 1.
2. ~~**Anima-mcp drawing endpoint**~~ — Already exists! `/gallery` lists drawings,
   `/gallery/{filename}` serves PNGs. `/state` serves all sensor + anima data.
