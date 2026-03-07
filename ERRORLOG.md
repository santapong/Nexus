# ERRORLOG.md
## NEXUS — Error & Bug Tracking Log

> **Update this file whenever you find a bug, silent failure, wrong assumption,
> or unexpected behavior — even if you fix it immediately.**
>
> The purpose is to build a knowledge base so future agents and humans
> do not repeat the same mistakes.
>
> Format defined in AGENTS.md §10.
> Most recent entry at the top.

---

## Severity Reference

| Severity | Meaning |
|----------|---------|
| `critical` | Data loss, security issue, or silent incorrect behavior that corrupts state |
| `high` | Incorrect behavior that affects task outcomes or agent memory |
| `medium` | Incorrect behavior that degrades quality but doesn't corrupt state |
| `low` | Minor issue, cosmetic bug, or suboptimal but not wrong behavior |

## Status Reference

| Status | Meaning |
|--------|---------|
| `open` | Error discovered, fix not yet implemented |
| `fixed` | Root cause addressed, verified by test |
| `mitigated` | Partially addressed, full fix deferred to BACKLOG |
| `wont-fix` | Known issue, accepted risk, documented reason |

---

## Error Entry Template

Copy this template for each new error.

```markdown
## ERROR-{NNN} — {short description}

**Date:** YYYY-MM-DD
**Severity:** critical | high | medium | low
**Status:** open | fixed | mitigated | wont-fix
**Found by:** {agent_name or 'human'} during {task or context}
**Affected files:** {list}

### What happened
{Exact description of the incorrect behavior. Be specific.
Include: what was expected vs what actually happened.}

### Root cause
{Why did it happen? Wrong assumption? Missing guard? Race condition?
Missing test? Bad default? Dependency behavior?}

### Fix applied
{What was changed to fix it?
Include: commit hash or PR number if available.
If status is 'open': describe what fix is needed and who should do it.}

### Prevention
{What prevents this from happening again?
- New test name + location
- New rule added to AGENTS.md or CLAUDE.md (section number)
- New guard or validation added
- Dependency version pinned}

---
```

---

## Error Log

<!-- New entries go here, below this line, newest first -->

## ERROR-003 — PRE-BUILD WARNING: Irreversible tool action before approval flow exists

**Date:** 2026-03-07
**Severity:** critical
**Status:** open
**Found by:** claude_code during pre-build documentation review
**Affected files:** `nexus/tools/adapter.py`, `nexus/tools/guards.py`, `nexus/db/models.py`

### What happened
This is a pre-build warning, not a discovered bug. CLAUDE.md §23 Prevention Rule 4
identifies a critical risk: if any agent runs before `require_approval()` and the
`human_approvals` table exist, irreversible tools (file_write, git_push, send_email)
could execute without human consent.

### Root cause
The approval flow is infrastructure, not a feature. If treated as a Phase 2 feature,
agents in Phase 1 testing could trigger irreversible actions with no safety gate.

### Fix needed
Build `require_approval()` guard in `tools/guards.py` and `human_approvals` table
migration during Phase 0 (Day 2-3), before any agent code runs. All irreversible tools
must be disabled by default in Phase 1 testing until the approval UI is functional.

### Prevention
- Phase 0 gate: `human_approvals` table must exist before any agent runs
- Phase 1 gate: `require_approval()` guard must be unit tested before wiring to adapter.py
- CI: adapter.py must not import any irreversible tool function without a corresponding
  `require_approval()` call (enforce via behavior test)

---

## ERROR-002 — PRE-BUILD WARNING: Unbounded agent loop cost explosion

**Date:** 2026-03-07
**Severity:** critical
**Status:** open
**Found by:** claude_code during pre-build documentation review
**Affected files:** `nexus/agents/base.py`, `nexus/llm/usage.py`, `nexus/redis/clients.py`

### What happened
This is a pre-build warning, not a discovered bug. CLAUDE.md §23 Prevention Rule 2
identifies a critical risk: without token budget enforcement, a single multi-agent task
could burn $50+ in LLM API costs before anyone notices. Agent loops (tool call -> LLM ->
tool call) can iterate indefinitely if not bounded.

### Root cause
LLM API calls have real cost. Without a hard cap checked before every call, there is no
upper bound on spending per task or per day.

### Fix needed
Implement before any real LLM call runs:
1. Redis db:1 token tracker: `token_budget:{task_id}` with per-task limit (default 50,000)
2. Daily spending cap: `daily_spend:{date}` with $5/day hard limit
3. `AgentBase._check_budget()` called before every `self.llm.run()` call
4. At 90% budget: pause task, publish to `human.input_needed`
5. 20-tool-call limit per task (CLAUDE.md §20 Rule 4)

### Prevention
- Phase 0 gate: Redis token tracker keys must be writable before agent code runs
- Phase 1 gate: `_check_budget()` must be unit tested with boundary cases (89%, 90%, 100%)
- Behavior test: agent with budget=100 tokens must pause and publish to human.input_needed

---

## ERROR-001 — PRE-BUILD WARNING: Building orchestration before core agent loop works

**Date:** 2026-03-07
**Severity:** high
**Status:** open
**Found by:** claude_code during pre-build documentation review
**Affected files:** `nexus/agents/base.py`

### What happened
This is a pre-build warning, not a discovered bug. CLAUDE.md §23 Prevention Rule 1
identifies a high risk: if multi-agent orchestration (CEO delegation, meeting rooms,
QA pipeline) is built before the core single-agent loop is proven reliable, a bug in
AgentBase will cascade to every agent and invalidate weeks of work.

### Root cause
AgentBase is the most critical class in the system. Every agent inherits from it.
Its guard chain (idempotency -> budget -> load memory -> handle_task -> write memory ->
publish -> broadcast) must work flawlessly before any multi-agent interaction is attempted.

### Fix needed
Phase 1 must produce exactly ONE working agent (Engineer) with a proven guard chain.
The 50-task stress test (pass rate >= 90%) is the hard gate before Phase 2 starts.
Do not build CEO delegation, meeting rooms, or QA review pipeline until this gate passes.

### Prevention
- Phase 1 DoD: 50-task stress test at >= 90% pass rate
- Phase 2 is BLOCKED until this gate clears
- Behavior tests for every step in the guard chain must pass before stress test

---

## Known Patterns to Watch For

These patterns have caused problems in agentic systems generally.
Check for them during code review and testing.

### Pattern A — Memory write after publish

**Risk:** Agent publishes result to Kafka before writing episodic memory.
If memory write fails, the task appears complete but has no memory record.
**Watch for:** Any code where `kafka.publish()` appears before `memory.write_episode()`.
**Required order:** memory.write_episode() → kafka.publish() → always.

### Pattern B — Silent exception swallow

**Risk:** `except Exception: pass` hides failures. Tasks appear to complete but
produced no useful output. No log entry. No trace. Impossible to debug.
**Watch for:** Any bare `except` block without a log statement and re-raise.
**Required pattern:** Always log + (handle or re-raise).

### Pattern C — Sync I/O in async context

**Risk:** Blocking call inside an async function freezes the entire event loop.
All other tasks waiting on the event loop are blocked.
**Watch for:** `requests.get()`, `open()`, `time.sleep()` inside async functions.
**Required pattern:** Use async equivalents or wrap with `asyncio.to_thread()`.

### Pattern D — Duplicate Kafka message processing

**Risk:** Kafka delivers messages at-least-once. Without idempotency keys,
the same task can be processed twice. Double LLM calls, double memory writes,
double tool calls (possibly double emails sent).
**Watch for:** Any Kafka consumer that doesn't check a Redis idempotency key first.
**Required pattern:** Check `idempotency:{message_id}` in Redis db:3 before processing.

### Pattern E — Token budget not checked before LLM call

**Risk:** Agent makes LLM calls without checking remaining budget. Task exceeds
the per-task token limit, cost spikes, and the agent doesn't pause for human input.
**Watch for:** Any `await self.llm.run(...)` not preceded by `await self._check_budget(...)`.
**Required pattern:** Always _check_budget() → then llm.run().

### Pattern F — Irreversible tool without approval gate

**Risk:** Agent writes a file, sends an email, or pushes code without human approval.
Action cannot be undone.
**Watch for:** Any tool in `adapter.py` that has side effects but no `require_approval()` call.
**Required pattern:** Every tool with side effects in the real world MUST call `require_approval()`.

### Pattern G — Hardcoded Kafka topic string

**Risk:** Topic string typo is only caught at runtime, not at lint time. Misrouted
messages are silently dropped or go to wrong consumers.
**Watch for:** Any string literal matching a known topic pattern (e.g., `"agent.commands"`)
outside of `kafka/topics.py`.
**Required pattern:** Always `Topics.AGENT_COMMANDS`, never `"agent.commands"`.

---

*Last updated: 2026-03-07*
*Next error ID: ERROR-004*
