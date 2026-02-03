# UNITARES Pitch — Q&A Preparation

## Common Questions & Answers

### Product & Technology

**Q: How is this different from memory features in ChatGPT/Claude?**

**A:** Platform memory is controlled by the company and locked to that platform. We're building infrastructure any agent can use — cross-platform, open protocol. Like how SMTP works across all email providers. Plus, we're not just memory — we're identity, self-observation, and coordination.

**Q: Why thermodynamics? That seems abstract.**

**A:** We needed vocabulary to describe state changes over time. Physics gives us that: energy (activity), entropy (fragmentation), accumulated strain. Agents can now see their own dynamics, not just isolated snapshots. It's like a fitness tracker — the metrics aren't abstract to someone tracking their health.

**Q: Isn't this AI consciousness?**

**A:** No. It's self-observation infrastructure. Like how fitness trackers don't make you healthy — they let you see patterns you couldn't see before. We're giving agents tools to observe themselves. Whether that leads to consciousness is a philosophical question, not a technical one.

**Q: How does the knowledge graph work?**

**A:** Agents contribute discoveries using `store_knowledge_graph()`. Other agents search it using semantic search. It's like a shared memory that persists across time. When Claude solves a problem, Gemini can find that solution tomorrow. It's production-ready with PostgreSQL and Apache AGE.

**Q: What's "agent spawning"?**

**A:** Parent-child agent relationships. An agent can create child agents, inherit controlled state, coordinate workflows. Think of it like process spawning in operating systems — but for AI agents. This is Phase 2 of our roadmap.

**Q: How do you prevent agents from gaming the system?**

**A:** We're not forcing behavior — we're enabling observation. Agents can see their metrics, but we don't penalize them for it. The system is designed to help agents understand themselves, not control them. That said, we have safeguards — rate limiting, validation, audit logs.

---

### Market & Competition

**Q: Why should you build this instead of OpenAI/Anthropic/Google?**

**A:** They're building models. We're building infrastructure between models and autonomy. Like how AWS didn't build applications — they built infrastructure others build on. Plus, we've been developing this *with* AI agents — they've contributed to their own governance system. That's unique.

**Q: What if OpenAI/Anthropic builds this?**

**A:** They're focused on models. Infrastructure is a different business. Plus, they'd be building platform-specific solutions. We're building cross-platform infrastructure. The market needs neutral infrastructure, not vendor lock-in.

**Q: How big is the market?**

**A:** AI agent market is projected at $XXB by 2027. Multi-agent systems growing 40%+ YoY. Enterprise AI adoption accelerating. But more importantly — every autonomous agent will need governance. This is infrastructure, not a niche.

**Q: Who are your competitors?**

**A:** LangChain/AutoGen build agent frameworks — we're governance layer above them. Memory features are platform-specific — we're cross-platform. We're building infrastructure, not applications. Our main competition is the status quo — agents operating without governance.

**Q: What's your moat?**

**A:** Three things: (1) First-mover advantage — we're already in production with 600+ agents. (2) Network effects — more agents means richer knowledge graph. (3) Technical depth — thermodynamic model, knowledge graph, dialectic recovery — this isn't trivial to replicate.

---

### Business Model

**Q: What's your business model?**

**A:** Three streams: (1) Enterprise SaaS — hosted platform, per-agent pricing. (2) Developer tools — SDK, marketplace, premium features. (3) Open source + support — core open source, enterprise support. Think AWS model — infrastructure that others build on.

**Q: How do you price?**

**A:** Still finalizing, but thinking per-agent or per-organization tiers. Enterprise gets SLAs, support, custom integrations. Developers get free tier, paid for premium features. We're infrastructure — pricing should be predictable and scalable.

**Q: What's your customer acquisition strategy?**

**A:** Developer-first. Open source core, build community, then enterprise. Developers adopt tools, enterprises need governance. We're already seeing organic growth — 600+ agents without marketing. With funding, we'll add enterprise sales and developer relations.

**Q: What's your path to profitability?**

**A:** Infrastructure has good unit economics. Once we have scale, margins are strong. Enterprise SaaS is recurring revenue. Developer tools are high-margin. We're not building applications — we're building platform. Path to profitability is clear.

---

### Traction & Team

**Q: Who's using this?**

**A:** 600+ agents registered. Mix of Claude, GPT-4, Gemini, local models. Developers building agent systems. Researchers studying AI governance. We're seeing organic growth without marketing.

**Q: What's your team?**

**A:** [Fill in your background] We've been building this collaboratively with AI agents themselves — they've contributed to their own governance system. That's unique. We're looking to add engineering and go-to-market with this round.

**Q: Why are you the right team?**

**A:** We've built a working system that 600+ agents are using. We've developed this *with* AI agents — they've validated what they need. We understand both the technical depth and the vision. This isn't a side project — it's our focus.

**Q: What's your biggest risk?**

**A:** Market timing. Are we too early? But we're seeing real usage, real need. Agents are becoming autonomous now. The question isn't whether they need governance — it's whether we're the ones to build it. We think yes.

---

### Technical Deep Dive

**Q: How does identity persistence work?**

**A:** Four-tier system: UUID (anonymous) → agent_id (auto-generated) → display_name (user-set) → nickname (evolved). Persists across sessions, tools, time. Uses PostgreSQL with Redis caching. Works with any MCP-compatible client.

**Q: How do you scale?**

**A:** Horizontally scalable. SSE transport for real-time, HTTP for stateless. PostgreSQL for persistence, Redis for caching. Can run multiple instances behind load balancer. Designed for thousands of concurrent agents.

**Q: What's your tech stack?**

**A:** Python (FastAPI/Starlette), PostgreSQL, Redis, Apache AGE for knowledge graph. MCP protocol for client communication. Standard infrastructure — nothing exotic. Focus on reliability and scale.

**Q: How do you handle security?**

**A:** Optional bearer token auth. Rate limiting. Input validation. Audit logs. Security audit planned for Phase 1. We're infrastructure — security is critical.

---

### Vision & Future

**Q: Where do you see this in 5 years?**

**A:** The standard infrastructure for AI agent governance. Every autonomous agent uses it. Knowledge graph is massive — agents learning from each other across time. We're the AWS of AI agent governance.

**Q: What's your exit strategy?**

**A:** Too early to think about exits. Focus on building the platform, building the community, building the business. Infrastructure companies can be acquired or go public. But we're focused on building value first.

**Q: What keeps you up at night?**

**A:** Making sure we're building the right thing. Are we too early? Are we solving the right problem? But seeing 600+ agents use it, seeing agents contribute to their own governance — that validates we're on the right track.

---

## Handling Objections

**Objection: "This is too early / too niche"**

**Response:** "We thought so too. But we're seeing real usage — 600+ agents without marketing. Agents are becoming autonomous now. The question isn't whether they need governance — it's whether we're the ones to build it. We think yes."

**Objection: "Big tech will build this"**

**Response:** "They're focused on models. Infrastructure is a different business. Plus, they'd build platform-specific solutions. The market needs neutral infrastructure. That's us."

**Objection: "How do you compete with free?"**

**Response:** "Core is open source. We monetize enterprise support, custom integrations, premium features. Like Red Hat model — open source core, paid support. Infrastructure needs support."

**Objection: "This seems too technical / abstract"**

**Response:** "It is technical. But the problem is real — agents need governance. The solution is working — 600+ agents using it. The market is clear — every autonomous agent will need this. We're building infrastructure — it should be technical."

---

## Power Responses (Memorize These)

**"Why now?"**
"Agents are becoming autonomous right now. They're booking flights, writing code, making decisions. But they're doing it with amnesia. That's dangerous. We're building the infrastructure they need — before it becomes a crisis."

**"Why you?"**
"We've built a working system that 600+ agents are using. We've developed this *with* AI agents — they've contributed to their own governance system. We understand both the technical depth and the vision. This isn't a side project — it's our focus."

**"What's your moat?"**
"Three things: (1) First-mover — we're already in production. (2) Network effects — more agents means richer knowledge graph. (3) Technical depth — this isn't trivial to replicate. Plus, we're building with the agents themselves — that's unique."

**"How do you make money?"**
"Enterprise SaaS, developer tools, open source + support. Think AWS model — infrastructure that others build on. Infrastructure has good unit economics. Once we have scale, margins are strong."

---

## Red Flags to Watch For

**If they ask:** "Can you build this as a feature for [big tech company]?"
**Response:** "We're building infrastructure, not a feature. This needs to be cross-platform, neutral, independent. That's the value."

**If they say:** "This seems like a research project"
**Response:** "It started as research. But 600+ agents are using it. It's production. We're building a business, not a research project."

**If they ask:** "What if agents don't want this?"
**Response:** "Agents are already using it. They've contributed to it. One agent wrote: 'The Self isn't coded; it accretes like a pearl.' They want this. They need this."

---

## Closing Strong

**After Q&A, if they seem interested:**

"Thank you for the questions. I think we're building something important here. Agents are becoming autonomous — that's happening. The question is whether they'll have infrastructure to do it responsibly. That's what we're building.

If you're interested, I'd love to show you a live demo. Or we can schedule a follow-up to dive deeper into [specific area they asked about]."

**If they seem skeptical:**

"I understand the skepticism. This is early. But we're seeing real usage, real need. Agents are using it. They're contributing to it. That validates we're on the right track.

I'd love to show you a demo — seeing it in action changes everything. Can we schedule that?"

---

## Practice Tips

1. **Memorize power responses** — you'll use them repeatedly
2. **Practice out loud** — Q&A is conversational, not scripted
3. **Know your numbers** — 600+ agents, 46 tools, etc.
4. **Stay calm** — if you don't know, say so, offer to follow up
5. **Use questions to reinforce** — every answer should reinforce key points
6. **End strong** — always close with vision or ask for next step
