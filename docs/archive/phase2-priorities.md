# Phase 2 Plan — Grouped by Priority

## Context

The Phase 2 implementation plan (`plan.md`) has 29 steps across 5 weeks. This document reorganizes those steps into priority groups, explaining **why** each group has its priority level based on dependency chains, risk, and architectural impact.

---

## Priority 1 — CRITICAL (Do First)
**Theme: Foundation that everything else depends on**

These items are blocking dependencies — nothing in Phase 2 works without them.

| Step | What | Why Critical |
|------|------|-------------|
| **Step 1** | Add missing tools to `adapter.py` + `registry.py` (web_fetch, send_email, git_push, memory_read) | Every new agent (Analyst, Writer, Prompt Creator) needs tools that don't exist yet. Without these, no new agent can function. This is the single biggest blocker. |
| **Step 2** | Manual prompt testing for Analyst, Writer, QA + seed into `prompts` table | §23 Risk 3 explicitly warns: vague prompts produce garbage. CLAUDE.md mandates 2+ hours of manual testing BEFORE writing agent code. Skipping this cascades failures into every agent built on bad prompts. |
| **Step 6** | Update agent factory + runner to handle new roles | The factory is the wiring — agents exist but can't be instantiated or run without this. |

**Why this group is #1:** These are prerequisites with zero workarounds. Steps 1 and 2 must complete before any new agent class can be coded. Step 6 must exist before any new agent can run.

---

## Priority 2 — HIGH (Core Agents)
**Theme: Get the new agents running individually**

Once tools and prompts exist, build the three new specialist agents. They follow the proven EngineerAgent pattern, so risk is low.

| Step | What | Why High |
|------|------|---------|
| **Step 3** | Implement AnalystAgent | Needed for multi-agent research tasks. Required for the Phase 2 DoD ("competitive analysis" scenario). |
| **Step 4** | Implement WriterAgent | Needed for content/email tasks. Required for the Phase 2 DoD ("draft an email summary"). |
| **Step 5** | Implement QAAgent | Gatekeeper for all outputs. Every multi-agent flow ends with QA review. Without QA, the CEO → specialist → review pipeline can't close. |
| **Step 7** | Unit tests for new agents | Catch bugs now while agents are simple. Much harder to debug agent issues once multi-agent orchestration is layered on top. |

**Why this group is #2:** These agents are the building blocks of multi-agent flows. They must each work in isolation before being orchestrated together. Building them is low-risk (proven pattern from EngineerAgent) but high-value.

---

## Priority 3 — HIGH (Multi-Agent Orchestration)
**Theme: Make agents work together**

This is the architectural leap — going from "one agent does one task" to "CEO decomposes and coordinates multiple agents."

| Step | What | Why High |
|------|------|---------|
| **Step 8** | Upgrade CEO to full task decomposition | The entire multi-agent architecture hinges on CEO correctly analyzing tasks and routing subtasks. This is the most complex single step. |
| **Step 9** | CEO response aggregation logic | Without aggregation, subtask results are orphaned. CEO must track, collect, and merge outputs. |
| **Step 10** | QA review pipeline | Closes the loop: CEO aggregates → QA reviews → final result published. Without this, tasks never "complete." |
| **Step 13** | Behavior tests for multi-agent flow | Multi-agent coordination has many failure modes (wrong routing, lost messages, partial failures). Tests are essential before depending on this pipeline. |

**Why this group is #3:** This is the highest-risk work in Phase 2. CEO decomposition touches task creation, Kafka routing, Redis state tracking, and DB subtask linking. Testing thoroughly here prevents §23 Risk 1 ("building orchestration before the loop works").

---

## Priority 4 — MEDIUM (Verification & Resilience)
**Theme: Prove it works, make it robust**

| Step | What | Why Medium |
|------|------|-----------|
| **Step 14** | Verify all 4 task categories E2E | Confirms that multi-agent flow works for real scenarios, not just unit tests. This is the "does it actually work?" checkpoint. |
| **Step 15** | Auto-fail on heartbeat silence (BACKLOG-016) `OPTIONAL` | Prevents tasks hanging forever when an agent crashes. Important for reliability but not blocking other work. |
| **Step 16** | E2E test suite | Safety net for regressions. Required before Phase 2 DoD sign-off. |
| **Step 12** | Task trace view in dashboard | Visibility into multi-agent flows. Without this, debugging multi-agent tasks is blind. Important for developer experience. |

**Why this group is #4:** These are "hardening" tasks. The system technically works without them, but it would be fragile and opaque. They transform a prototype into something trustworthy.

---

## Priority 5 — MEDIUM (Meeting Room) `OPTIONAL — not required for DoD`
**Theme: Advanced collaboration pattern**

| Step | What | Why Medium |
|------|------|-----------|
| **Step 11** | Meeting room pattern (temporary Kafka topics for agent debates) | Enables richer collaboration than simple CEO-delegate-collect. However, the simpler pattern (CEO routes subtasks, collects responses) handles most Phase 2 use cases. Meeting rooms are an enhancement, not a requirement for DoD. |

**Why this group is #5:** The Phase 2 DoD can be met without meeting rooms. CEO decomposition + response aggregation covers the "competitive analysis + email" scenario. Meeting rooms add value for complex debates but can be deferred within Phase 2 without blocking anything.

> **Deferral note:** Can be pushed to Phase 3 with zero impact on Phase 2 DoD. The DoD scenario is sequential (Analyst → Writer → QA), not a debate.

---

## Priority 6 — MEDIUM-LOW (Prompt Creator Agent)
**Theme: Meta-agent that improves other agents**

| Step | What | Why Medium-Low |
|------|------|---------------|
| **Step 17** | Seed benchmark test cases (10 per role) | Required for Prompt Creator to measure improvement. |
| **Step 18** | Migrate prompts into versioned `prompts` table | Enables versioned prompt management. Agents load prompts from DB instead of seed data. |
| **Step 19** | Implement PromptCreatorAgent | The meta-agent itself: reads failures → drafts improvements → benchmarks → proposes. |
| **Step 20** | Prompt approval UI (diff view + scores) | Human interface for approving/rejecting prompt proposals. |
| **Step 21** | Auto-trigger logic (failure rate > 10%) | Automates prompt improvement requests based on agent performance. |
| **Step 22** | Update factory for Prompt Creator | Wiring to run the agent. |

**Why this group is #6:** The Prompt Creator needs **failure data from real multi-agent operations** to be useful. It depends on Priority 2–4 being done and running. It's also self-contained — nothing else depends on it. It's valuable (systematic prompt improvement) but not blocking any other feature.

---

## Priority 7 — LOW (A2A Gateway)
**Theme: External agent interoperability**

| Step | What | Why Low |
|------|------|--------|
| **Step 23** | A2A Pydantic schemas | Data models for the A2A protocol. |
| **Step 24** | A2A authentication (bearer tokens) | Security layer for external callers. |
| **Step 25** | A2A gateway routes (Agent Card, POST /a2a, SSE stream) | The actual HTTP endpoints. |
| **Step 26** | CEO routing for A2A tasks | Minimal change — A2A tasks look identical to human tasks. |
| **Step 27** | A2A outbound placeholder (Phase 3 stub) | Just a stub, minimal effort. |
| **Step 28** | A2A integration tests | End-to-end verification of external calls. |
| **Step 29** | Register routes + seed dev token | Wiring into the app. |

**Why this group is #7:** A2A is the **most independent** feature in Phase 2. It has zero dependencies on other Phase 2 work (new agents, CEO decomposition, Prompt Creator). It also has zero dependents — nothing else needs A2A to function. For a solo-user Phase 1→2 transition, A2A is the lowest urgency since there are no external agents calling NEXUS yet. However, it's architecturally clean and self-contained, so it can be built in parallel by a separate developer/agent.

---

## Cross-Cutting (Throughout All Priorities)

These apply continuously, not as discrete steps:

| Concern | When |
|---------|------|
| Audit logging (A2A, prompts, QA decisions) | As each feature is built |
| Dashboard enhancements (trace view, prompt page, A2A list) | Alongside the backend feature |
| Documentation updates (CHANGELOG, DECISIONS, BACKLOG) | After each priority group completes |

---

## Summary: Execution Order

```
Priority 1  ──→  Priority 2  ──→  Priority 3  ──→  Priority 4
(Tools +         (3 New            (CEO Decomp +     (E2E Verify +
 Prompts +        Agents +          Aggregation +     Auto-fail +
 Factory)         Tests)            QA Pipeline)      Dashboard)
                                        │
                                        ├──→  Priority 5 (Meeting Room)
                                        ├──→  Priority 6 (Prompt Creator)
                                        └──→  Priority 7 (A2A Gateway)
```

Priorities 5, 6, and 7 can run **in parallel** after Priority 4 is stable. They have no dependencies on each other.

---

## Items Marked as Optional/Deferrable

These are included in the plan but **not required** for the Phase 2 Definition of Done. They can be deferred to Phase 3 if time runs short:

| Step | Item | Can Defer To |
|------|------|-------------|
| Step 11 | Meeting Room pattern | Phase 3 — DoD scenario is sequential, no debates needed |
| Step 15 | Auto-fail on heartbeat silence | Phase 3 — resilience feature, not in DoD |
| Step 12 | Full task trace view | Could ship a simpler "list subtasks" view instead |
| Step 17 | 50 benchmark test cases (10×5 roles) | Could start with 25 (5×5) and still satisfy DoD |

## Missing Items (Not in plan.md but potentially needed)

| Item | Status | Note |
|------|--------|------|
| Multi-provider cost dashboard | Not addressed | Listed as "does NOT exist yet" in current state summary |
| `a2a_tokens` table migration | Mentioned as "possible" | Will be needed for A2A auth (Step 24) |

---

## Key Risks to Watch

1. **CEO decomposition quality** (Priority 3) — This is the hardest step. If the CEO prompt/logic doesn't decompose tasks well, the entire multi-agent system produces bad results. Allocate extra time here.
2. **Prompt quality** (Priority 1, Step 2) — Garbage prompts cascade. Don't skip manual testing.
3. **Meeting room complexity** (Priority 5) — Dynamic Kafka topic management can introduce subtle bugs. Keep it simple (CEO-terminates only).
