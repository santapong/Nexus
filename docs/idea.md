# idea.md — NEXUS Future Ideas & Vision

> **Ideas that go beyond the current backlog.**
> These are exploratory concepts, moonshots, and long-term vision items.
> Not committed to any phase. Reviewed quarterly.
>
> For items committed to a specific phase, see [BACKLOG.md](BACKLOG.md).

---

## Phase 5 Core Ideas — Assigned to Tracks

### IDEA-016 — Row-Level Security Enforcement in PostgreSQL
**Status:** Assigned → Phase 5 Track A (BACKLOG-038)
Full PostgreSQL RLS policies per workspace. Every SELECT automatically filtered by
workspace_id via `SET LOCAL nexus.workspace_id`. Zero-trust data isolation at the database
layer. Required before production multi-tenant deployment.

---

### IDEA-017 — Stripe Payment Integration for Marketplace
**Status:** Assigned → Phase 5 Track A (BACKLOG-040)
Real payment processing for cross-company A2A task billing. Stripe Connect for marketplace
payouts to listing owners. Automatic invoice settlement. Escrow for disputed tasks.

---

### IDEA-018 — OAuth2 / SSO Integration
**Status:** Assigned → Phase 5 Track A (BACKLOG-039)
Replace JWT-only auth with OAuth2 providers (Google, GitHub, Microsoft). SAML for enterprise.
Per-workspace SSO configuration. Required for enterprise adoption.

---

### IDEA-019 — Horizontal Auto-Scaling with Pod Autoscaler
**Status:** Assigned → Phase 5 Track C (BACKLOG-047 area)
Kubernetes HPA for backend pods based on Kafka consumer lag metrics. Scale agents independently
based on queue depth per topic. Zero-downtime deployment with rolling updates.

---

### IDEA-020 — LLM-Based Prompt Injection Detection
**Status:** NEW → Phase 5 Track A (BACKLOG-045)
**Added:** 2026-03-19
Move beyond regex-only defense. Run a small classifier model (or Haiku/Flash API call) on
every task instruction before execution. Separate from the task-executing LLM to avoid
recursive manipulation. Target: 95%+ block rate on OWASP prompt injection test cases.

---

### IDEA-021 — OpenTelemetry Distributed Tracing
**Status:** NEW → Phase 5 Track C (BACKLOG-047)
**Added:** 2026-03-19
Replace structured-logs-only observability with proper distributed traces across Kafka →
agent → tools → LLM. Flame graphs for task execution. Export to Jaeger or Grafana Tempo.
Prerequisite for debugging production multi-tenant at scale.

---

### IDEA-022 — Secrets Vault Migration (SOPS / HashiCorp Vault)
**Status:** NEW → Phase 5 Track A (BACKLOG-046)
**Added:** 2026-03-19
Replace `.env` + KeepSave with proper secrets management. Auto-rotation for LLM API keys.
Per-workspace secret scoping. Required for enterprise multi-tenant with real customer data.

---

### IDEA-023 — Webhook Notifications for External Integrations
**Status:** Promoted from BACKLOG-036 → Phase 5 Track A
**Added:** 2026-03-19
Users register webhook URLs for task completion/failure/approval events. Retry with
exponential backoff. Slack/Discord integration templates. Simple but high-value for
integrating NEXUS into existing workflows.

---

## Phase 4 Core Ideas (Completed)

### IDEA-001 — Agent Personality & Voice Profiles

Give each agent a distinct personality beyond its role. Configure communication style,
verbosity level, risk tolerance, and decision-making approach. A "cautious" Engineer
writes more tests; an "aggressive" one moves faster. Users pick personality profiles
from a preset library or create custom ones.

**Impact:** Higher user engagement, more natural agent interactions.

---

### IDEA-002 — Agent Learning from Human Feedback (RLHF-lite)
**Status:** Assigned → Phase 5 Track B (BACKLOG-051)

When humans approve or reject agent outputs (QA reviews, approval gates), feed that
signal back into the agent's semantic memory as preference data. Over time, agents
learn what "good" looks like for this specific user/company without retraining the LLM.

**Impact:** Agents improve with use. Competitive moat.

---

### IDEA-003 — Visual Workflow Builder (No-Code Orchestration)

Drag-and-drop UI for building custom agent workflows. Connect agents in a DAG (directed
acyclic graph). Define conditions, branches, and loops. Generates the equivalent of CEO
decomposition logic but with a visual editor. Exports to a workflow JSON spec.

**Impact:** Non-technical users can build complex agent pipelines.

---

### IDEA-004 — Agent Specialization via Fine-Tuning
**Status:** Assigned → Phase 5 Track B (BACKLOG-048)

Use collected episodic memory and eval scores to create fine-tuning datasets per agent
role. Fine-tune smaller models (e.g., Llama 8B) to match the behavior of larger models
for specific roles. Run fine-tuned models via Ollama for zero API cost.

**Impact:** 10x cost reduction. On-premise deployment without API dependency.

---

### IDEA-005 — Cross-Company Agent Marketplace

Public directory where NEXUS companies advertise their agents' specialties via A2A.
Browse agents by skill, rating, cost, and response time. Escrow-based billing.
Reputation system based on eval scores and completion rates.

**Impact:** Network effect. Each new NEXUS deployment makes the ecosystem more valuable.

---

### IDEA-006 — Real-Time Agent Collaboration Streaming

Stream agent-to-agent discussions (meeting room) live to the dashboard. Users watch
CEO delegate, specialists debate, and QA review in real-time. Like watching a team
standup. Add ability for humans to interject mid-conversation.

**Impact:** Transparency. Trust. Entertainment value for demos.

---

### IDEA-007 — Multi-Modal Agent Capabilities
**Status:** Assigned → Phase 5 Track B (BACKLOG-050)

Extend agents to handle images, PDFs, audio, and video. Analyst can analyze charts.
Engineer can review screenshots of UI bugs. Writer can generate image descriptions.
Uses multi-modal LLM capabilities (Claude, Gemini).

**Impact:** Dramatically expands the task types NEXUS can handle.

---

### IDEA-008 — Agent Memory Graph (Knowledge Graph)

Replace flat semantic memory with a graph database (or PostgreSQL with ltree/jsonb
graph patterns). Agents build a connected knowledge graph over time. Enables complex
queries like "What does the Engineer know about the payment system that the Analyst
researched last week?"

**Impact:** Deeper cross-agent knowledge sharing. Better context for complex tasks.

---

### IDEA-009 — Scheduled & Recurring Tasks
**Status:** Assigned → Phase 5 Track B (BACKLOG-049)

Cron-like scheduler for recurring tasks. "Every Monday, have the Analyst compile a
competitive intelligence report." "Every day at 5pm, have the Writer draft a standup
summary from today's completed tasks." Uses Temporal (Phase 4) for durable scheduling.

**Impact:** Autonomous operation. NEXUS works even when the user is away.

---

### IDEA-010 — Agent Skill Leveling System

Track agent competency per skill domain (e.g., "Python: Expert", "TypeScript: Intermediate").
Skill levels increase based on successful task completions and eval scores in that domain.
CEO uses skill levels to route tasks to the most qualified agent. Gamification element
for the dashboard.

**Impact:** Smarter task routing. User engagement through visible growth.

---

## Moonshot Ideas

### IDEA-011 — Self-Healing Agent Infrastructure

Agents monitor their own infrastructure health. If Kafka is slow, agents automatically
switch to Redis Streams. If a model provider is down, the system reroutes traffic to
fallback providers and sends a status report. The system heals itself without human
intervention.

---

### IDEA-012 — Agent Code Review for Its Own Codebase

Engineer Agent reviews PRs to the NEXUS codebase itself. It understands the architecture
(from CLAUDE.md in its semantic memory), checks for pattern violations, and suggests
improvements. Meta-level: the system improves its own code.

---

### IDEA-013 — Natural Language to Agent Workflow Compiler

"I need a process where the analyst researches competitors, the writer drafts a report,
and the CEO reviews it weekly." Natural language input → generates a workflow spec →
creates scheduled task with agent routing rules. No technical knowledge required.

---

### IDEA-014 — Agent Negotiation Protocol

When two agents disagree in a meeting room (e.g., Engineer says "too complex" and
Analyst says "necessary"), implement a structured negotiation protocol. Agents present
arguments, weigh trade-offs, and reach consensus. CEO mediates. Full transcript for
audit.

---

### IDEA-015 — Federated Learning Across NEXUS Deployments

With user consent, share anonymized eval data and prompt improvements across NEXUS
deployments. A prompt improvement discovered by one deployment benefits all. Privacy-
preserving aggregation. Opt-in network effect.

---

*Last updated: 2026-03-19*
*Owner: NEXUS Project*
