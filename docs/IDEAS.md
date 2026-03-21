# IDEAS.md
## NEXUS — Innovation & Feature Ideas

> **Big-picture ideas that could shape NEXUS's future.**
> Unlike BACKLOG.md (scoped work items for specific phases), this file captures
> exploratory concepts that need further design, research, or user validation
> before becoming actionable backlog items.
>
> **Rule:** Don't delete ideas. If an idea moves to BACKLOG.md, mark it as
> `PROMOTED` with the backlog item number. If an idea is rejected, mark it as
> `REJECTED` with a one-line reason.

---

## Format

```
### IDEA-{NNN} — {short title}
**Category:** {Integration | UX | Self-Improvement | Platform | DevOps | Distribution}
**Added by:** {person or agent}
**Date:** YYYY-MM-DD
**Status:** OPEN | EXPLORING | PROMOTED (BACKLOG-XXX) | REJECTED (reason)
**Description:** {2-5 sentences}
**Key questions:** {what needs answering before this becomes a backlog item}
```

---

## Ideas

<!-- New ideas go here, newest last -->

### IDEA-001 — Chrome Extension for NEXUS
**Category:** Integration / Distribution
**Added by:** santapong
**Date:** 2026-03-14
**Status:** OPEN
**Description:** Build a Google Chrome extension that lets users interact with NEXUS
directly from the browser. Users can submit tasks, view agent status, approve
irreversible actions, and see results — all without opening the full dashboard.
The extension could intercept page context (selected text, current URL, page title)
and use it as task input, enabling "right-click → send to NEXUS" workflows.
**Key questions:**
- Auth flow for extension ↔ NEXUS API (token-based or session cookie?)
- Which dashboard features belong in the extension vs stay in the full UI?
- Should the extension support WebSocket streaming for real-time status?
- Chrome-only initially, or also Firefox/Edge from day one?

---

### IDEA-002 — 2D Virtual Office (Gather-style Workspace)
**Category:** UX / Visualization
**Added by:** santapong
**Date:** 2026-03-14
**Status:** OPEN
**Description:** Create a 2D virtual workspace inspired by Gather Town where each
NEXUS agent has an avatar that moves around a virtual office. Users can see agents
working in real-time — the CEO in the "executive suite" decomposing tasks, the
Engineer in the "dev room" writing code, agents walking to the "meeting room" when
a collaborative task starts. Users can "walk up" to any agent and interact directly.
This transforms NEXUS from a task management tool into a living, visual company
simulation that is intuitive and engaging.
**Key questions:**
- Tech stack: Canvas/WebGL, Phaser.js, or PixiJS for the 2D engine?
- How to map Kafka events to agent avatar movements and animations?
- Does this replace the dashboard or live alongside it as an alternative view?
- Asset creation: pixel art, vector, or AI-generated agent avatars?
- Performance: how many concurrent agents/users before the canvas lags?

---

### IDEA-003 — Feedback Automation Loop
**Category:** Self-Improvement / DevOps
**Added by:** santapong
**Date:** 2026-03-14
**Status:** OPEN
**Description:** Build an automated feedback pipeline where users rate and annotate
task outputs. The system aggregates feedback patterns (e.g., "Writer agent outputs
are too verbose", "Engineer misses edge cases") and feeds them to the Prompt Creator
Agent for continuous improvement. A monitoring dashboard shows feedback trends over
time, tracks which prompt changes were made in response, and measures whether those
changes actually improved output quality. Closes the loop between "this output was
bad" and "the agent is now better."
**Key questions:**
- Feedback format: 1-5 star rating, thumbs up/down, or free-text annotation?
- How to attribute improvements to specific prompt changes vs model changes?
- Should feedback trigger Prompt Creator automatically or queue for review?
- Integration with existing `prompt_benchmarks` table for before/after scoring?
- Privacy: can aggregated feedback be shared across tenants in Phase 4?

---

### IDEA-004 — Voice Interface / Conversational Mode
**Category:** UX / Distribution
**Added by:** claude_code
**Date:** 2026-03-14
**Status:** OPEN
**Description:** Add voice input/output to NEXUS so users can delegate tasks by
talking, like speaking to a real team. Use the Web Speech API for browser-based
voice recognition or integrate with OpenAI Whisper for higher accuracy. Agents
could "speak back" results using text-to-speech, making NEXUS feel like a voice
assistant that manages an entire company.
**Key questions:**
- Browser-native Web Speech API vs server-side Whisper — latency vs accuracy tradeoff?
- How to handle complex multi-step task descriptions via voice?
- TTS for results: which voice engine? Cost implications?
- Accessibility benefits vs implementation complexity?

---

### IDEA-005 — Agent Marketplace / Plugin System
**Category:** Platform
**Added by:** claude_code
**Date:** 2026-03-14
**Status:** OPEN
**Description:** Let users create custom agent roles with a no-code configuration UI
(define role, system prompt, tool access, model). Share agent templates between NEXUS
instances via a community marketplace. Already partially planned in the Phase 4
roadmap ("Custom agent role creator") — this idea expands it with a public marketplace
where users can publish, browse, and install agent templates like browser extensions.
**Key questions:**
- Template format: JSON schema, YAML, or a dedicated DSL?
- Trust model: how to review community-submitted agents for safety?
- Monetization: free marketplace, paid premium agents, or revenue share?
- Versioning: how do marketplace agents receive updates?

---

### IDEA-006 — Mobile App (Progressive Web App)
**Category:** Distribution
**Added by:** claude_code
**Date:** 2026-03-14
**Status:** OPEN
**Description:** Build a Progressive Web App (PWA) for mobile access to NEXUS.
Primary use case: approving irreversible actions on the go (the human-in-the-loop
approval queue is time-sensitive). Secondary: quick task submission and status
checks from mobile. Push notifications alert users when agents need approval or
tasks complete.
**Key questions:**
- PWA vs native app (React Native / Flutter)?
- Push notification infrastructure: Firebase Cloud Messaging or Web Push API?
- Offline support needed, or always-connected assumption?
- Which dashboard views to prioritize for mobile-first design?

---

### IDEA-007 — Task Templates & Visual Workflow Builder
**Category:** UX / Platform
**Added by:** claude_code
**Date:** 2026-03-14
**Status:** OPEN
**Description:** Pre-built task templates for common workflows — e.g., "Research
competitor + draft analysis report + email summary to team." Users select a template,
fill in variables, and NEXUS executes the multi-step workflow automatically. A visual
workflow builder (drag-and-drop) lets users chain agent tasks together, define
dependencies, and create reusable pipelines. Think Zapier/n8n but for AI agent
orchestration.
**Key questions:**
- Template storage: DB table or file-based YAML?
- How does the workflow builder interact with CEO decomposition logic?
- Conflict: does a user-defined workflow override or supplement CEO's planning?
- Conditional branching: if QA rejects → retry vs escalate vs alternative path?

---

### IDEA-008 — Real-time Multi-User Collaboration Dashboard
**Category:** UX / Platform
**Added by:** claude_code
**Date:** 2026-03-14
**Status:** OPEN
**Description:** Allow multiple human users to watch and interact with the same task
simultaneously. Features: cursor presence (see who else is viewing), live comments
and annotations on agent output, collaborative approval decisions. Think "Google Docs
but for AI task management." Particularly valuable in Phase 4 multi-tenant mode where
teams share a NEXUS instance.
**Key questions:**
- CRDT or OT for conflict resolution on simultaneous annotations?
- Presence tracking: WebSocket heartbeats or Redis pub/sub?
- Permission model: viewer vs editor vs approver roles?
- Scale: how many concurrent viewers per task before performance degrades?

---

### IDEA-009 — Agent Performance Leaderboard & A/B Testing
**Category:** Self-Improvement / UX
**Added by:** claude_code
**Date:** 2026-03-14
**Status:** OPEN
**Description:** Gamification layer on top of existing analytics. Track and display
agent success rates, task completion speed, cost efficiency, and quality scores in a
leaderboard format. Enable A/B testing of different LLM models per agent role — run
the same task on two models and compare results side-by-side. Helps users make
data-driven decisions about model assignment.
**Key questions:**
- Scoring formula: weight success rate vs speed vs cost how?
- A/B test infrastructure: random assignment or manual split?
- Statistical significance: how many tasks before declaring a winner?
- Already have `llm_usage` data — what additional metrics needed?

---

### IDEA-010 — Integration Hub (Slack, Jira, Google Workspace)
**Category:** Integration
**Added by:** claude_code
**Date:** 2026-03-14
**Status:** OPEN
**Description:** Connect NEXUS to external productivity tools. A Slack/Discord bot
for submitting tasks via chat commands and receiving notifications. Jira/Linear
integration for automatic ticket creation from agent outputs. Google Workspace
integration for reading/writing Docs, Sheets, and Calendar. A generic webhook
system for triggering tasks from arbitrary external events (GitHub push, Stripe
payment, form submission).
**Key questions:**
- Build custom integrations vs use an integration platform (Zapier, Make)?
- OAuth flow for each service — how to manage per-user credentials securely?
- Which integration is highest value first? (likely Slack)
- How do integrations interact with the A2A gateway — overlap or complement?

---

### IDEA-011 — Agent Self-Reflection & Chain-of-Thought
**Category:** Self-Improvement
**Added by:** claude_code
**Date:** 2026-03-16
**Status:** OPEN
**Description:** Add a self-reflection step to the agent guard chain where agents review
their own output before submitting it to QA. The agent would critique its own work against
the task requirements, catch obvious errors (wrong format, missing sections, hallucinated
data), and self-correct before the result enters the QA pipeline. This could significantly
reduce QA rejection rates and rework loops, saving tokens and time. Could be implemented
as a second LLM call with a "critic" system prompt, or by appending a "review your own
output" instruction to the existing prompt.
**Key questions:**
- Cost: does a second LLM call per task negate the savings from fewer QA rejections?
- Should self-reflection be optional/configurable per agent role?
- How to measure improvement: compare QA rejection rates before and after?
- Risk of infinite self-correction loops — need a max-revision counter?

---

### IDEA-012 — Scheduled / Recurring Tasks (Cron-style)
**Category:** Platform
**Added by:** claude_code
**Date:** 2026-03-16
**Status:** OPEN
**Description:** Add a cron-like task scheduling system where users can configure tasks
to run on a schedule (e.g., "research competitor pricing every Monday at 9am", "generate
weekly status report every Friday"). A scheduler service reads schedules from a DB table
and publishes to `task.queue` at the appropriate time. Results accumulate in a time-series
view. Useful for recurring business intelligence, monitoring, and reporting workflows.
**Key questions:**
- Scheduler implementation: Taskiq periodic tasks, APScheduler, or custom cron parser?
- How to handle missed schedules (server was down during scheduled time)?
- Should recurring tasks share a trace_id or get new ones each run?
- Cost control: recurring tasks could silently burn budget — need per-schedule budget caps?

---

### IDEA-013 — Agent Skill Specialization via Fine-Tuning Data
**Category:** Self-Improvement / Platform
**Added by:** claude_code
**Date:** 2026-03-16
**Status:** OPEN
**Description:** Use NEXUS's episodic memory and human feedback as fine-tuning datasets.
For each agent role, export successful task executions (input instruction + tool calls +
final approved output) as training examples. Fine-tune smaller, cheaper models (e.g., Llama
or Mistral) on role-specific data. A fine-tuned "NEXUS Engineer" model could outperform a
generic model at lower cost because it's seen hundreds of successful engineering tasks. The
Prompt Creator Agent could manage the fine-tuning pipeline: select training data, trigger
fine-tuning jobs, benchmark fine-tuned models, and propose model swaps.
**Key questions:**
- Minimum dataset size for useful fine-tuning? (likely 500+ examples per role)
- Fine-tuning infrastructure: local (Ollama + LoRA) vs cloud (OpenAI, Together AI)?
- How to handle distribution shift as the agent's task mix evolves?
- Legal/IP considerations for training on user-submitted task data?

---

### IDEA-014 — Multi-Company A2A Marketplace
**Category:** Platform / Distribution
**Added by:** claude_code
**Date:** 2026-03-16
**Status:** OPEN
**Description:** Build a discovery layer on top of A2A where NEXUS instances can find and
hire each other's specialist agents. Each NEXUS company publishes its Agent Card with skills
and pricing. A marketplace index aggregates Agent Cards from registered companies. When a
NEXUS instance encounters a task outside its agents' capabilities, it searches the marketplace,
finds a specialist from another company, and hires via A2A outbound. Creates a distributed
agent economy where companies specialize and trade services.
**Key questions:**
- Discovery: centralized registry vs distributed (DNS-like) agent discovery?
- Trust: how to verify that an external agent's claimed capabilities are real?
- Billing: per-task pricing, subscription tiers, or token-based credits?
- SLA enforcement: what happens if an external agent fails or takes too long?
- Already partially planned in Phase 4 — this idea extends it into a public marketplace.

---

### IDEA-015 — Observability with OpenTelemetry + Grafana
**Category:** DevOps
**Added by:** claude_code
**Date:** 2026-03-16
**Status:** OPEN
**Description:** Instrument the entire NEXUS stack with OpenTelemetry spans: LLM calls
(model, tokens, latency), Kafka message lifecycle (publish → consume → process), DB queries
(duration, table), Redis operations, and HTTP endpoints. Export traces to Jaeger for
distributed tracing and metrics to Prometheus/Grafana for dashboards. This would enable:
trace a single task from API → CEO → Engineer → tools → QA → response as one distributed
trace; visualize agent "thinking time" vs "tool time" vs "waiting time"; alert on latency
regressions. Critical for Phase 3 chaos testing and production readiness.
**Key questions:**
- Instrumentation overhead: acceptable latency increase for tracing?
- Which OTel exporters: OTLP to Jaeger + Prometheus, or all-in-one (Grafana Tempo)?
- How to correlate task_id/trace_id with OTel trace IDs?
- Self-hosted vs managed observability (Grafana Cloud, Datadog)?

---

## Research-Backed Ideas (2026 arXiv + GitHub Trends)

> Ideas sourced from recent arXiv papers, GitHub trending projects, and industry
> patterns observed in March 2026. Each includes research citations.

---

### IDEA-016 — Active Tool Discovery (MCP-Zero Pattern)
**Category:** Platform / Self-Improvement
**Added by:** claude_code
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [MCP-Zero: Active Tool Discovery (arXiv 2506.01056)](https://arxiv.org/abs/2506.01056),
[MCP Tool Descriptions Are Smelly (arXiv 2602.14878)](https://arxiv.org/abs/2602.14878)
**Description:** Instead of loading all tools upfront (consuming context window), agents
actively discover tools on-demand. When an agent encounters a capability gap, it requests
specific tools via a Hierarchical Semantic Router. The MCP-Zero paper shows this approach
reduces context usage by 60%+ while maintaining task success rates. For NEXUS: agents start
with zero tools and request them from the registry as needed. Combined with the finding
that tool description quality directly impacts agent performance (the "smelly descriptions"
paper), this means NEXUS should audit and optimize all tool docstrings.
**Key questions:**
- How to implement lazy tool loading with Pydantic AI's current tool registration model?
- Should tool discovery be agent-initiated or orchestrator-managed?
- Performance impact of on-demand tool fetching vs preloaded tools?

---

### IDEA-017 — Agent Registry & Federated Discovery (AGNTCY Pattern)
**Category:** Platform / Federation
**Added by:** claude_code
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [Evolution of AI Agent Registry Solutions (arXiv 2508.03095)](https://arxiv.org/abs/2508.03095),
[AGNTCY Agent Directory Service (arXiv 2509.18787)](https://arxiv.org/html/2509.18787),
[Agent Name Service (arXiv 2505.10609)](https://arxiv.org/html/2505.10609),
[The Trust Fabric: Nanda Unified Architecture (arXiv 2507.07901)](https://arxiv.org/html/2507.07901)
**Description:** The arXiv survey (2508.03095) evaluates 5 registry approaches and concludes
that **federated models** that separate stable identity from dynamic capability metadata are
the future. For NEXUS federation: adopt a hybrid approach — simple registry for Phase 6
(centralized, fast to build) → federated AGNTCY-style directory for Phase 7 (decentralized,
OCI artifacts, Sigstore signing). The Agent Name Service (ANS) paper proposes DNS-inspired
agent discovery with PKI certificates — worth evaluating for NEXUS's trust model.
**Key questions:**
- Start with centralized registry or jump to federated?
- DID-based identity (NANDA) vs PKI certificates (ANS) vs simple bearer tokens (current)?
- How to handle cross-registry capability negotiation?

---

### IDEA-018 — Error Cascade Prevention in Multi-Agent Systems
**Category:** Self-Improvement / Resilience
**Added by:** claude_code
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [From Spark to Fire: Modeling Error Cascades in Multi-Agent LLM Collaboration
(arXiv, March 2026)](https://arxiv.org/list/cs.MA/current)
**Description:** When CEO decomposes a task incorrectly, the error cascades through all
downstream agents — every specialist wastes tokens on wrong subtasks. This recent paper
models how errors propagate in multi-agent LLM systems and proposes mitigation strategies.
For NEXUS: add a "decomposition validator" step where a second LLM verifies the CEO's
task plan before dispatching subtasks. Could be the QA agent reviewing the plan, or a
lightweight classifier checking for common decomposition errors (wrong roles, missing
dependencies, overly granular splits).
**Key questions:**
- Should validation be a separate agent or a step in CEO's guard chain?
- Cost of validation LLM call vs cost of cascaded errors?
- How to measure decomposition quality (track rework rate per decomposition pattern)?

---

### IDEA-019 — Safe RLHF for Multi-Modal Agent Alignment
**Category:** Self-Improvement / Safety
**Added by:** claude_code
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [Safe RLHF-V: Multi-modal Safety Alignment (arXiv 2503.17682)](https://arxiv.org/abs/2503.17682),
[M3HF: Multi-agent RL from Human Feedback (arXiv 2503.02077)](https://arxiv.org/pdf/2503.02077),
[Multi-Agent RLHF: Data Coverage (arXiv 2409.00717)](https://arxiv.org/html/2409.00717v2)
**Description:** Safe RLHF-V introduces dual preference annotations (helpfulness AND safety)
for multi-modal alignment, improving both by 34%. M3HF extends this to multi-agent with
online mixed-quality feedback. For NEXUS: when implementing RLHF-lite (BACKLOG-051), use
dual scoring — "was this output helpful?" AND "was this output safe?" Track both dimensions
in the feedback loop. The multi-agent RLHF paper shows that standard single-policy coverage
fails in multi-agent settings — NEXUS should ensure feedback covers all agent roles, not
just the most active ones.
**Key questions:**
- Dual annotation UI: how to make safety scoring intuitive for users?
- Minimum feedback signals needed before RLHF affects agent behavior?
- How to handle conflicting feedback across different users/tenants?

---

### IDEA-020 — Agentic SRE: Self-Healing Infrastructure
**Category:** DevOps / Resilience
**Added by:** claude_code
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [Agentic SRE in Enterprise AIOps (Unite.AI, 2026)](https://www.unite.ai/agentic-sre-how-self-healing-infrastructure-is-redefining-enterprise-aiops-in-2026/),
[Self-Healing SRE Agent (GitHub)](https://github.com/jalpatel11/Self-Healing-SRE-Agent),
[Self-Healing CI/CD with AI Agents (Dagger)](https://dagger.io/blog/automate-your-ci-fixes-self-healing-pipelines-with-ai-agents/)
**Description:** In 2026, Agentic SRE is production-ready. The pattern: monitoring agents
detect anomalies → diagnosis agents trace root causes → remediation agents execute fixes
→ validation agents verify recovery. All under Policy-as-Code guardrails (OPA-style).
For NEXUS: the Engineer agent already has code execution tools. Add an "SRE mode" where
the Engineer monitors NEXUS's own infrastructure (Kafka lag, Redis health, DB pool usage,
LLM provider latency) and auto-remediates common issues. Self-healing scope: restart
stalled consumers, clear Redis caches, switch LLM providers, scale Kafka partitions.
**Key questions:**
- Scope: should NEXUS heal only itself, or also user applications?
- Guardrails: which auto-remediation actions are safe without human approval?
- How to prevent remediation loops (fix causes new problem, triggers new fix)?
- Integration with existing circuit breaker and provider health monitoring?

---

### IDEA-021 — Browser Agent Chrome Extension (Enhanced)
**Category:** Integration / Distribution
**Added by:** claude_code (research expansion of IDEA-001)
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [Nanobrowser (GitHub)](https://github.com/nanobrowser/nanobrowser),
[BrowserOS](https://www.blog.brightcoding.dev/2026/02/14/browseros-the-revolutionary-ai-browser-that-runs-agents-natively),
[Stagehand v3](https://www.firecrawl.dev/blog/best-browser-agents),
Google WebMCP in Chrome Canary (Feb 2026)
**Description:** Builds on IDEA-001. In 2026, browser agents have matured significantly.
Nanobrowser runs multi-agent workflows from a Chrome extension using your own LLM keys.
Google shipped WebMCP preview in Chrome Canary — a protocol for structured AI agent
interactions with websites. For NEXUS: build a Chrome extension where NEXUS agents can
read the current page (via WebMCP or DOM extraction), take actions on websites (fill forms,
click buttons), and stream results back to the dashboard. The "right-click → send to NEXUS"
workflow from IDEA-001, plus active browser automation capabilities.
**Key questions:**
- Use WebMCP (Google standard) or CDP (Chrome DevTools Protocol) for page interaction?
- Security model: which sites can the extension access?
- Should agents be able to take browser actions autonomously, or only with approval?
- Integration with existing A2A gateway for external browser-based agents?

---

### IDEA-022 — 2D Virtual Office with Agent Avatars (Enhanced)
**Category:** UX / Visualization
**Added by:** claude_code (research expansion of IDEA-002)
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [VirT-Lab: LLM Agent Team Simulations in 2D (arXiv 2508.04634)](https://arxiv.org/html/2508.04634v1),
[OpenClaw Office (GitHub)](https://github.com/WW-AI-Lab/openclaw-office),
[Augmenting Teamwork with Spatial AI (arXiv 2503.09794)](https://arxiv.org/html/2503.09794v1)
**Description:** Builds on IDEA-002. VirT-Lab validates the concept — 2D spatial environments
for LLM agent teams using Phaser.js are production-viable. OpenClaw Office is already doing
this: SVG-rendered isometric office with desk zones, meeting areas, and WebSocket-driven
agent visualization. For NEXUS: use Phaser.js or PixiJS for the 2D engine. Map Kafka events
to avatar movements — when CEO publishes to agent.commands, the CEO avatar "walks" to the
specialist's desk. Meeting room Kafka topic triggers avatars gathering in the meeting area.
Users can click on any agent avatar to see its current task, memory, and tools.
**Key questions:**
- Phaser.js (game engine, more features) vs PixiJS (lighter, faster)?
- AI-generated pixel art avatars per agent role?
- Performance: WebSocket event rate for smooth avatar animation?
- Mobile-friendly 2D view or desktop-only?

---

### IDEA-023 — Visual Workflow Builder (DAG Editor)
**Category:** UX / Platform
**Added by:** claude_code (research expansion of IDEA-007)
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [Firecrawl Open Agent Builder (GitHub)](https://github.com/firecrawl/open-agent-builder),
[Dify (130K GitHub stars)](https://dify.ai/),
[Flowise](https://flowiseai.com/),
[The Agency (TuringWorks)](https://github.com/TuringWorks/the-agency),
[Sim Studio](https://github.com/simstudioai/sim)
**Description:** Builds on IDEA-007. In 2026, visual workflow builders for AI agents are
mainstream — Dify (130K stars), Langflow, Flowise all prove the model. For NEXUS: build
a React-based node editor (using React Flow library) where users drag agent nodes, tool
nodes, and condition nodes into a DAG. Connect them with edges that define data flow.
The workflow compiles to a JSON spec that replaces CEO decomposition for that task — the
user defines the agent pipeline instead of relying on LLM planning. Supports conditional
branching (if QA rejects → rework vs escalate), parallel execution, and loops.
**Key questions:**
- Use React Flow (most popular) or Xyflow (newer, faster)?
- Workflow spec format: JSON DAG with node types and edge conditions?
- Relationship to CEO decomposition: override, supplement, or fallback?
- Template marketplace: share and import workflow templates?

---

### IDEA-024 — Plugin System with MCP Tool Manifest
**Category:** Platform / Extensibility
**Added by:** claude_code
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [Orchestral AI Framework (arXiv 2601.02577)](https://arxiv.org/pdf/2601.02577),
[AgentScope 1.0 (arXiv 2508.16279)](https://arxiv.org/pdf/2508.16279),
[OpenDev Lazy Tool Discovery (arXiv 2603.05344)](https://arxiv.org/html/2603.05344v1),
[AI Agent Plugins Guide (Nevo, 2026)](https://nevo.systems/blogs/nevo-journal/what-are-ai-agent-plugins)
**Description:** A plugin is more than an MCP tool — it bundles skills, hooks, custom agent
behavior, and MCP server configs into a distributable unit. For NEXUS: define a plugin
manifest format (JSON/YAML) that specifies: tool functions (Python callables or HTTP
endpoints), required secrets, approval requirements, compatible agent roles, and version.
Plugins hot-reload without restart using AgentScope's lifecycle hooks pattern. The registry
validates plugin signatures and runs sandboxed tests before activation.
**Key questions:**
- Manifest format: JSON schema vs YAML vs Python package metadata?
- Security: sandboxed execution for third-party plugins?
- Distribution: PyPI packages, GitHub repos, or custom plugin registry?
- Should plugins be able to define new agent roles or only new tools?

---

### IDEA-025 — Hierarchical Multi-Agent Planning (StackPlanner Pattern)
**Category:** Self-Improvement / Architecture
**Added by:** claude_code
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [StackPlanner: Hierarchical Multi-Agent Framework (VoltAgent/awesome-ai-agent-papers)](https://github.com/VoltAgent/awesome-ai-agent-papers),
[CTHA: Constrained Temporal Hierarchical Architecture](https://github.com/VoltAgent/awesome-ai-agent-papers)
**Description:** StackPlanner decouples high-level coordination from subtask execution with
active task-level memory control. CTHA adds typed message contracts and authority bounds.
For NEXUS: evolve the CEO from a flat decomposer to a hierarchical planner. CEO creates
a high-level plan → each specialist agent can further decompose its subtask into micro-tasks
→ creating a tree of work instead of a flat list. This enables complex multi-step tasks
(e.g., "build a web app") where the Engineer agent internally plans architecture → coding →
testing as sub-subtasks without burdening the CEO with implementation details.
**Key questions:**
- Max depth of hierarchical decomposition? (recommend 2-3 levels)
- How to handle cross-level dependencies?
- Token budget allocation across hierarchy levels?
- Does this conflict with the current flat subtask model?

---

### IDEA-026 — Integration Hub (Slack, Jira, Google Workspace)
**Category:** Integration
**Added by:** claude_code (research expansion of IDEA-010)
**Date:** 2026-03-19
**Status:** OPEN
**Research:** [n8n workflow automation (400+ integrations)](https://github.com/topics/workflow-builder),
Webhook notifications system (already built in Phase 5 Track A)
**Description:** NEXUS already has webhook notifications (Phase 5). Next step: build first-party
integrations. Priority order based on enterprise value: (1) Slack bot for task submission
and notifications, (2) GitHub integration for PR review and issue tracking, (3) Google
Workspace for Docs/Sheets/Calendar access, (4) Jira/Linear for ticket management. Each
integration is a plugin (IDEA-024) that bundles MCP tools + webhook handlers.
**Key questions:**
- Build custom integrations or leverage n8n/Zapier as middleware?
- OAuth flow management for per-user external service credentials?
- Which integration delivers the most value first? (likely Slack)

---

## Strategic Analysis: The 5 Questions

### Q1: Learning vs Multi-Modal — Which First?

**Recommendation: Learning first (RLHF-lite + fine-tuning).**

**Research backing:** The Safe RLHF-V paper shows 34% improvement in both helpfulness and
safety with dual preference annotations. M3HF demonstrates online multi-agent RLHF is
feasible. Meanwhile, multi-modal support is mostly a model capability (Claude/Gemini already
handle images) — it's a tool integration task, not an architectural change.

**Why learning first:**
- NEXUS already collects the data needed (episodic memory, QA approvals, eval scores)
- Learning compounds over time — earlier start = larger advantage
- Multi-modal is "plug in when needed" — agents already work without it
- Fine-tuning to Ollama models provides 10x cost reduction — high business value

### Q2: Full Federation vs Simple Registry

**Recommendation: Simple registry first (Phase 6) → federated (Phase 7).**

**Research backing:** The arXiv survey (2508.03095) evaluates 5 approaches and concludes
federated models are the future BUT centralized approaches ship faster. AGNTCY separates
identity from capability metadata — this separation can be adopted incrementally.

**Why phased approach:**
- Simple registry: one NEXUS instance publishes Agent Card, another discovers it via HTTP
- Federated: DID-based identity, OCI artifacts, Sigstore signing — months of work
- NEXUS already has A2A gateway + Agent Cards — registry is a natural extension
- Federation protocols (ANP, NANDA) are still maturing — wait for stability

### Q3: Visual Workflow Builder — When?

**Recommendation: Phase 6 (late) or Phase 7 (early).**

**Research backing:** Dify (130K stars), Langflow, Flowise prove massive demand. But all
are standalone products — integrating a visual builder into an existing multi-agent system
(with CEO decomposition, QA review, meeting rooms) is architecturally complex.

**Why not rush it:**
- NEXUS's CEO decomposition already works — the builder supplements, not replaces
- React Flow library makes the UI fast to build, but the workflow-to-Kafka compilation is hard
- Should come AFTER learning (Phase 6A) so workflows can leverage improved agents
- Build it alongside the plugin system — workflows use plugins as nodes

### Q4: Plugin System Scope

**Recommendation: Start with tool-level plugins, expand to full agent plugins later.**

**Research backing:** The Orchestral AI paper shows MCP + automatic schema generation creates
a powerful extensibility model. AgentScope 1.0 uses lifecycle hooks for runtime modification.

**Scope for Phase 6/7:**
- **Phase 6:** Tool plugins — register Python callables or HTTP endpoints as MCP tools.
  Manifest defines parameters, approval requirements, and compatible roles. Hot-reload.
- **Phase 7:** Full plugins — bundle tools + custom agent roles + hooks + MCP servers.
  Plugin marketplace for sharing across NEXUS instances.

### Q5: Self-Healing Infrastructure — Worth It?

**Recommendation: Yes, but scoped to NEXUS-internal healing only.**

**Research backing:** Agentic SRE is production-ready in 2026. The Self-Healing SRE Agent
on GitHub shows the pattern works. The key insight: use Policy-as-Code guardrails so
auto-remediation actions are bounded and auditable.

**Why yes (scoped):**
- NEXUS already has circuit breakers, provider health monitoring, and dead letter queues
- Self-healing is the logical next step: detect → diagnose → remediate → verify
- Scope to internal only: restart consumers, clear caches, switch providers, scale partitions
- DO NOT auto-heal user applications — too risky, requires domain knowledge

---

### IDEA-027 — Knowledge Graph Memory (GraphRAG)
**Category:** Self-Improvement / Architecture
**Added by:** claude
**Date:** 2026-03-21
**Status:** OPEN
**Research:** Microsoft GraphRAG (batch-based entity extraction), Graphiti by Neo4j (real-time
incremental updates, 5x faster queries than traditional RAG, 90% fewer hallucinations),
MAGMA paper (arxiv 2601.03236 — multi-graph agentic memory: procedural + semantic + episodic
as separate graph layers). Cognee (open-source memory engine turning unstructured data into
concept graphs).
**Description:** Replace NEXUS's flat vector-based episodic/semantic memory with a knowledge
graph that captures entity-relationship structure. Agents would query "What do we know about
Client X?" and get all projects, interactions, budget impact, and related agents — not just
cosine-similar text chunks. CEO task decomposition would improve by seeing the context graph
instead of flat vector search results. Estimated 5x improvement in recall quality for complex
multi-step tasks.
**Key questions:**
- Neo4j (dedicated graph DB) vs PostgreSQL AGE extension (stay on single DB)?
- Migration strategy: how to backfill existing episodic/semantic records into graph?
- Performance at scale: when does graph query outperform vector search (>100 tasks? >1000?)?
- How to handle agent-specific vs shared knowledge graph partitions?

---

### IDEA-028 — Agent Negotiation & Consensus Protocol
**Category:** Self-Improvement / Platform
**Added by:** claude
**Date:** 2026-03-21
**Status:** OPEN
**Research:** AutoGen (Microsoft) designed for multi-agent negotiation/debate. Supply chain
consensus-seeking research shows agents balancing selfish goals with systemic outcomes through
structured conversation (Tandfonline 2025). Dynamic negotiation protocols enable propose/accept/
counter-offer workflows at machine speed. Agentic Commerce Protocol (ACP) by OpenAI + Stripe
adds payment negotiation to agent interactions.
**Description:** Currently NEXUS CEO determines task decomposition top-down. Specialists execute
without push-back. Implement a structured negotiation protocol where specialists can estimate
effort, propose scope changes, and negotiate with CEO before committing. Example flow:
CEO: "Implement feature X by Friday for $100" → Engineer: "That's tight, can we cut Y?" →
CEO: "Approved, write scope doc." Uses existing Kafka meeting room pattern with new
negotiation message types (propose, counter, accept, reject).
**Key questions:**
- How to prevent negotiation from becoming an infinite token sink?
- Should negotiation be opt-in per task type or always-on?
- How does QA interact with negotiated scope (review against original or negotiated scope)?
- What's the fallback if agents can't reach consensus (CEO decides unilaterally)?

---

### IDEA-029 — NIST CAISI Compliance Framework
**Category:** Security / Platform
**Added by:** claude
**Date:** 2026-03-21
**Status:** OPEN
**Research:** NIST launched the Collaborative AI Standards Initiative (CAISI) in February 2026
with three pillars: (1) industry-led standards via W3C/IETF, (2) open-source protocol maintenance,
(3) AI agent security & identity research. RFI on AI Agent Security due March 2026. Concept paper
on AI Agent Identity & Authorization due April 2026. Sector-specific listening sessions starting
April 2026. Focus areas: security controls, risk management, safeguards against misuse, privilege
escalation prevention, and unintended autonomous action prevention.
**Description:** Proactively align NEXUS with emerging NIST standards for AI agent security.
NEXUS already implements many anticipated requirements (human_approvals, require_approval() guard,
audit_log, tool_access control, token budget enforcement). Build a compliance dashboard that
maps NEXUS security controls to NIST CAISI requirements. Generate compliance reports for
enterprise customers. This becomes a competitive differentiator for regulated industries.
**Key questions:**
- Which NIST requirements will NEXUS already satisfy vs need new work?
- How to structure compliance reporting (automated vs manual review)?
- Should compliance checks run as a CI pipeline or runtime validation?
- Timeline: when will NIST publish actionable requirements (late 2026)?

---

### IDEA-030 — A2A v0.3 gRPC Transport Layer
**Category:** Platform / Performance
**Added by:** claude
**Date:** 2026-03-21
**Status:** OPEN
**Research:** A2A protocol v0.3 (July 2025, Linux Foundation governance) added gRPC support
alongside HTTP+SSE. 150+ organizations now supporting. gRPC provides lower latency, bidirectional
streaming, and stronger typing than HTTP+SSE. Real-world adoption: Tyson Foods + Gordon Food
Service running production multi-agent A2A systems. Security card signing replaces simple
bearer tokens for stronger external authentication.
**Description:** Add gRPC as an alternative transport for NEXUS's A2A gateway alongside the
existing HTTP+SSE implementation. External agents can choose their preferred transport.
gRPC's bidirectional streaming is a natural fit for the meeting room pattern (multi-turn
agent conversations). Implement security card signing as an upgrade from bearer tokens.
Keep HTTP+SSE as default (backward compatible), gRPC as opt-in for performance-sensitive callers.
**Key questions:**
- gRPC framework: grpcio (Google) vs grpclib (pure Python async)?
- How to serve HTTP and gRPC on the same port (or separate ports)?
- Security card format: use A2A v0.3 spec or custom NEXUS extension?
- Performance baseline: measure latency improvement of gRPC vs HTTP+SSE for typical tasks

---

### IDEA-031 — Agent Control Plane Dashboard
**Category:** DevOps / Observability
**Added by:** claude
**Date:** 2026-03-21
**Status:** OPEN
**Research:** AGNTCY (Linux Foundation) provides multi-agent collaboration infrastructure with
built-in observability. The "agent control plane" concept (2026 trend) treats AI agents like
microservices — each needs health checks, resource monitoring, and lifecycle management.
NEXUS already has OpenTelemetry tracing, provider health monitoring, and agent heartbeats.
The missing piece is a unified cross-instance view.
**Description:** Build a control plane dashboard that monitors multiple NEXUS instances
(leveraging the federation registry). Show: agent health across instances, task throughput,
error rates, cost trends, provider status, federation connectivity. Think "Kubernetes dashboard
for AI agents." Aggregate OTel traces from multiple instances. Alert on: instance unreachable,
agent failure rate spike, cost anomaly, provider outage. This transforms NEXUS from a
single-instance tool to a fleet management platform.
**Key questions:**
- Centralized dashboard (one instance aggregates from all) or per-instance with links?
- Data collection: pull (dashboard queries instances) or push (instances report to dashboard)?
- Storage: time-series DB (Prometheus/InfluxDB) or existing PostgreSQL?
- Access control: who can see cross-instance data?

---

### IDEA-032 — Agentic Commerce via AP2 Mandates
**Category:** Platform / Billing
**Added by:** claude
**Date:** 2026-03-21
**Status:** OPEN
**Research:** AP2 (Agent Payments Protocol, Google, September 2025) uses cryptographically-signed
"Mandates" as the trust primitive. Mandates are digital contracts that specify: who can spend,
how much, for what, until when. Two transaction models: real-time purchases (Intent → Cart →
approval) and delegated tasks (pre-signed Intent Mandate). 60+ organizations including Adyen,
Mastercard, PayPal support the spec. A2A x402 extension adds crypto payments (Ethereum,
Coinbase, MetaMask).
**Description:** When NEXUS's A2A marketplace matures, implement AP2 Mandates for agent-to-agent
payment settlement. A user pre-authorizes a spending budget (Mandate) → NEXUS CEO can hire
external agents up to that budget → payment settles via AP2 → invoice generated automatically.
This replaces manual approval for each external hire with pre-authorized, auditable, bounded
spending. Aligns with NEXUS's existing `human_approvals` pattern (Mandates are essentially
machine-readable approvals with payment terms).
**Key questions:**
- Integration with existing Stripe billing (AP2 alongside or replacing Stripe for A2A)?
- Mandate storage: extend `human_approvals` table or new `mandates` table?
- Crypto payments: add or defer (regulatory complexity)?
- Trust model: how to verify external agent AP2 credentials?

---

### IDEA-033 — Federated Learning Across NEXUS Instances
**Category:** Self-Improvement / Federation
**Added by:** claude
**Date:** 2026-03-21
**Status:** OPEN
**Research:** Federated learning enables multiple deployments to improve model quality without
sharing raw data. Privacy-preserving techniques (differential privacy, secure aggregation)
allow sharing model gradients or prompt improvements without exposing tenant data. NEXUS
already has RLHF-lite (feedback signals) and fine-tuning pipeline (episodic → dataset → Ollama).
The missing link: sharing learned improvements across instances.
**Description:** Enable NEXUS instances in a federation to share prompt improvements and model
weights without sharing raw task data. Instance A learns "Engineer agent works better with
step-by-step instructions" → shares this as a prompt delta → Instance B applies it. Uses
differential privacy to prevent reconstruction of source data from shared gradients. Requires
federation registry (Phase 6) as prerequisite. Each instance opts in/out of federated learning.
Shared improvements go through Prompt Creator Agent approval flow (never auto-deployed).
**Key questions:**
- What exactly is shared: prompt deltas, model gradients, or aggregated feedback signals?
- Privacy guarantees: differential privacy epsilon budget per sharing round?
- Trust: how to prevent adversarial instances from poisoning shared improvements?
- Performance: minimum number of instances needed for federated learning to add value?

---

### IDEA-034 — Natural Language Workflow Compiler
**Category:** UX / Platform
**Added by:** claude
**Date:** 2026-03-21
**Status:** OPEN
**Research:** Dify (130K+ GitHub stars), Langflow, Flowise prove massive demand for visual/natural
language workflow builders. But all are standalone products — integrating into an existing
multi-agent system with CEO decomposition, QA review, and meeting rooms is architecturally
complex. React Flow library makes UI fast to build, but workflow-to-Kafka compilation is the
hard part.
**Description:** Users describe a business process in natural language: "Every Monday, research
competitors, draft an email summary, get my approval, then send it." NEXUS compiles this into
an executable agent DAG: scheduled trigger → Analyst (research) → Writer (draft) → human
approval → Writer (send email). The compiler maps process steps to agent roles, identifies
dependencies, and generates Kafka message flows. Builds on scheduled tasks (Phase 5) and
meeting room pattern (Phase 2). Start with template-based workflows, evolve to LLM-compiled
workflows as reliability improves.
**Key questions:**
- Compilation strategy: LLM-based (flexible but unreliable) vs template-based (rigid but safe)?
- How to handle ambiguous steps ("process the data" — which agent? which tools?)?
- Validation: how to verify a compiled workflow before execution?
- Version control: how to track workflow changes and rollback?

---

*Last updated: 2026-03-21*
*Next item ID: IDEA-035*
