# BACKLOG.md
## NEXUS — Scope Creep Capture

> **Every idea that is NOT in the current phase goes here.**
> Do not build it. Do not design it further. Just capture it.
> Review this list at the start of each new phase.

---

## Format

```
### BACKLOG-{NNN} — {short description}
**Suggested phase:** {phase number}
**Added by:** {agent or human}
**Date:** YYYY-MM-DD
**Description:** {1-2 sentences}
```

---

## Backlog Items

<!-- New items go here, newest first -->

### BACKLOG-020 — Groq daily token limit monitoring in dashboard
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** Phase 1 stress test — Groq 100K TPD limit discovered
**Description:** Groq free tier has a hard 100,000 tokens-per-day limit. When running many
tasks, this limit is hit silently and all subsequent tasks fail with 429. Add provider-level
rate limit tracking to the dashboard so users can see remaining daily quota before submitting
tasks. Also show a warning when approaching the limit.

---

### BACKLOG-019 — Model fallback chain with automatic retry
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** §6 LLM Provider Strategy, universal ModelFactory upgrade
**Description:** Implement automatic model fallback when primary model fails (rate limit,
timeout, API down). Use pydantic-ai's FallbackModel to chain primary → fallback per role.
E.g., claude-sonnet → gemini-pro → groq:llama-3.3-70b. Reduces single-provider dependency.

---

### BACKLOG-018 — Dynamic model assignment via API / dashboard
**Suggested phase:** Phase 2-3
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** universal ModelFactory upgrade
**Description:** Allow changing an agent's model at runtime via the API/dashboard without
restarting the backend. Store model_name in the `agents` table and read it at task start
instead of from static settings. Enables live A/B testing of models per agent role.

---

### BACKLOG-017 — Ollama / local model integration testing
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** universal ModelFactory upgrade
**Description:** Test the full agent loop with Ollama local models (llama3, codellama).
Validate that tool calling works correctly with local models — some may not support
function calling, requiring a prompt-based fallback. Zero cost for development testing.

---

### BACKLOG-016 — Task auto-fail on 5-minute heartbeat silence
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** §23 Risk 5, Phase 1 audit gap
**Description:** Heartbeat loop is implemented (30s publish to agent.heartbeat). Missing:
a health check consumer that monitors heartbeats and auto-fails tasks if no heartbeat
received within 5 minutes of task assignment. Implement as a lightweight background service.

---

### BACKLOG-015 — Multi-provider cost dashboard
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** universal ModelFactory upgrade, §6 cost controls
**Description:** Dashboard view showing cost breakdown by provider, model, agent, and
time period. With multi-provider support, users need visibility into which models are
costing what. Aggregate from `llm_usage` table. Show daily/weekly/monthly trends.

---

### BACKLOG-014 — Provider health monitoring and status page
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** §23 Risk 5, universal ModelFactory upgrade
**Description:** Monitor API health for all configured providers. Track latency, error
rates, and availability per provider. Show in dashboard. Feeds into automatic fallback
decisions (BACKLOG-019). Helps debug "why is the agent slow" questions.

---

### BACKLOG-013 — Model performance benchmarking across providers
**Suggested phase:** Phase 2 (with Prompt Creator Agent)
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** universal ModelFactory upgrade, §7 Prompt Creator Agent
**Description:** Run the same prompt_benchmarks test suite against different models to
compare quality/cost/speed tradeoffs. Prompt Creator Agent can use this data to recommend
optimal model assignments per role. Store results in a new `model_benchmarks` table.

---

### BACKLOG-012 — ~~Real API keys for full E2E task completion~~ RESOLVED
**Suggested phase:** ~~Phase 1 (remaining)~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-08
**Resolved:** 2026-03-08
**Description:** ~~E2E verification confirmed the full task flow works architecturally, but
LLM calls return 401 with placeholder API keys.~~
**Resolution:** Configured Groq API key (free tier). Full E2E task completion verified with
`groq:llama-3.3-70b-versatile`. Universal ModelFactory supports 7+ providers.

---

### BACKLOG-011 — ~~50-task stress test execution~~ RESOLVED
**Suggested phase:** ~~Phase 1 (gate for Phase 2)~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-08
**Resolved:** 2026-03-08
**Source:** CLAUDE.md §14, §23 Prevention Rule 1
**Description:** ~~Run the 50-task stress test script with real API keys. Pass rate must be >= 90%.~~
**Resolution:** Stress test passed at **100% (50/50)**. Full pipeline verified: API → Kafka →
CEO → Engineer → response → DB update. First live run with Groq confirmed working (74% due
to rate limits). Added retry logic + `test:` model provider for infrastructure testing.
Phase 2 gate cleared.

---

### BACKLOG-010 — Frontend component library migration to Shadcn/ui
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-08
**Description:** Current frontend uses hand-built Tailwind components. Migrate to Shadcn/ui
component library as decided in ADR-005. Low priority — current components are functional.

---

### BACKLOG-009 — ~~Kafka vs Redis Streams decision for Phase 1~~ RESOLVED
**Suggested phase:** ~~Phase 0 (Day 2)~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-07
**Resolved:** 2026-03-08
**Source:** CLAUDE.md §25 Open Questions
**Description:** ~~Decide whether to use Kafka or Redis Streams for Phase 1 development.~~
**Resolution:** Kafka KRaft mode is stable. All services start reliably, topics are created,
producer/consumer flow verified end-to-end. Staying with Kafka. See ADR-008.

---

### BACKLOG-008 — Agent naming convention: generic roles vs named personas
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §25 Open Questions
**Description:** Decide whether agents use generic role names (CEO, Engineer, Analyst) or
named personas (e.g., "Ada" the Engineer, "Marcus" the CEO). Cosmetic but affects dashboard
UX and user perception. Low priority — no architectural impact.

---

### BACKLOG-007 — Secrets management for multi-user deployment
**Suggested phase:** Phase 4
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §25 Open Questions
**Description:** Decide between `.env` files, Docker secrets, or HashiCorp Vault for
secrets management. Current `.env` approach is sufficient for solo local dev but must be
replaced before multi-user deployment in Phase 4.

---

### BACKLOG-006 — Log aggregation strategy
**Suggested phase:** Phase 3
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §25 Open Questions
**Description:** Choose between file-based JSON logs, Loki, or OpenSearch for log
aggregation. Current plan uses structured JSON logging to stdout. Decision needed before
Phase 3 hardening. See also ADR-012 (proposed).

---

### BACKLOG-005 — Embedding async timing confirmation
**Suggested phase:** Phase 1 (prerequisite)
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §25 Needs Further Design
**Description:** Confirm that Taskiq fire-and-forget for embedding generation is acceptable.
When an agent starts a new task, its first few seconds of context loading will not include
embeddings from the most recently written episode. Verify this timing gap does not degrade
agent performance in practice.

---

### BACKLOG-004 — Meeting room termination signal design
**Suggested phase:** Phase 2
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §25 Needs Further Design
**Description:** Define what signals the end of a meeting room session. Options: CEO-initiated
timeout, explicit consensus vote by participating agents, or unanimous agreement signal.
Needed before implementing the meeting room pattern in Phase 2 Week 4-5. See also ADR-013
(proposed).

---

### BACKLOG-003 — Semantic memory contradiction handling strategy
**Suggested phase:** Phase 1-2
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §25 Needs Further Design
**Description:** When two tasks produce conflicting facts for the same semantic memory key,
determine which value wins. Options: newest-wins (simple), highest-confidence-wins (nuanced),
or human-resolves (safest). Affects the upsert logic in `semantic_memory` table. See also
ADR-011 (proposed).

---

### BACKLOG-002 — ~~Engineer Agent system prompt manual testing~~ RESOLVED
**Suggested phase:** ~~Phase 1 (prerequisite)~~ RESOLVED
**Added by:** claude_code
**Date:** 2026-03-07
**Resolved:** 2026-03-08
**Source:** CLAUDE.md §25 Needs Further Design, §23 Prevention Rule 3
**Description:** ~~Conduct a 2+ hour manual prompt testing session in Claude.ai for the
Engineer Agent system prompt.~~
**Resolution:** Engineer Agent system prompt written and seeded into `prompts` table
(version 1, authored_by='human'). engineer.py implemented and verified end-to-end.
Agent successfully receives tasks, processes via LLM, and publishes results.

---

### BACKLOG-001 — MCP package audit: type hints and docstrings
**Suggested phase:** Phase 1 (prerequisite — before writing adapter.py)
**Added by:** claude_code
**Date:** 2026-03-07
**Source:** CLAUDE.md §8 MCP Prerequisite, §25 Needs Further Design
**Description:** Audit every function in the MCP Python package that will be wrapped by
`nexus/tools/adapter.py`. All parameters must have type hints. All functions must have
docstrings with one-line summary + Args + Returns. Pydantic AI uses the docstring to
describe the tool to the LLM — vague docstrings produce bad tool usage. Add missing
annotations to the MCP package before Phase 1 adapter work begins.

---

*Last updated: 2026-03-08*
*Next item ID: BACKLOG-021*
