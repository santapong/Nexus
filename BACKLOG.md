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

### BACKLOG-012 — Real API keys for full E2E task completion
**Suggested phase:** Phase 1 (remaining)
**Added by:** claude_code
**Date:** 2026-03-08
**Description:** E2E verification confirmed the full task flow works architecturally, but
LLM calls return 401 with placeholder API keys. Configure real ANTHROPIC_API_KEY and
GOOGLE_API_KEY in `.env` to complete full end-to-end task execution.

---

### BACKLOG-011 — 50-task stress test execution
**Suggested phase:** Phase 1 (gate for Phase 2)
**Added by:** claude_code
**Date:** 2026-03-08
**Source:** CLAUDE.md §14, §23 Prevention Rule 1
**Description:** Run the 50-task stress test script (`backend/nexus/tests/e2e/stress_test.py`)
with real API keys. Pass rate must be >= 90% before Phase 2 starts. Script exists but has
not been executed with live LLM calls yet.

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
*Next item ID: BACKLOG-013*
