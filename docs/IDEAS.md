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

*Last updated: 2026-03-14*
*Next item ID: IDEA-011*
