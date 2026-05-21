# NEXUS — Business Owner's Guide

A plain-English answer to three questions about NEXUS:

1. **Token usage** — what's being spent, and who's spending it?
2. **Learning from experience** — how do agents improve, and how do they know they're right?
3. **Business implementation** — how do I actually run my business on this?

---

## 1. Token Usage — Who Uses the Most?

### What's tracked on every LLM call

Every single LLM call writes a row to the `llm_usage` table. There is no LLM call
in the system that escapes this log.

| Column | Meaning |
|--------|---------|
| `task_id` | Which task the call belongs to |
| `agent_id` | Which agent (CEO, Engineer, Analyst, Writer, QA, Director, Prompt Creator) made the call |
| `model_name` | Which model was used (Claude Sonnet, Haiku, Gemini Pro, Flash, Ollama, etc.) |
| `input_tokens` / `output_tokens` | Exact token counts |
| `cost_usd` | Computed at call time from the price table in `backend/nexus/core/llm/usage.py` |
| `created_at` | Timestamp |

Source: `backend/nexus/db/models.py` (LLMUsage table),
`backend/nexus/core/llm/usage.py` (price table for 12 models).

### Where you see "who uses the most"

The Analytics API exposes the data already grouped four ways. Endpoints live in
`backend/nexus/api/analytics.py`:

| Endpoint | Answers the question |
|----------|----------------------|
| `GET /analytics/performance?period=7d` | Per-agent totals: tasks, success rate, avg tokens, total cost |
| `GET /analytics/costs?period=30d` | Cost broken down **by model** and **by role** + daily average |
| `GET /analytics/costs/{agent_id}` | Drill into one specific agent |
| `GET /analytics/quota` | Current daily spend vs. the $5/day cap, and per-task budget headroom |
| `GET /analytics/agent-cost-alerts` | Which agents are over their configured budget |
| `GET /analytics/approval-rates` | Quality signal: which roles get rework most often |

Periods supported: `7d`, `30d`, `90d`, `all`.

### Budget enforcement (so a runaway agent can't bankrupt you)

Before every LLM call, the system checks two budgets:

- **Daily spend cap** — default **$5/day**, configurable via `DAILY_SPEND_LIMIT_USD`.
  Stored in Redis with key `daily_spend_usd:{YYYY-MM-DD}` (date-keyed so a Redis
  restart can't reset it), with PostgreSQL fallback if Redis is down.
- **Per-task token budget** — default **50,000 tokens/task**, configurable per
  agent in the `agents.token_budget_per_task` column. At 90% consumed, the task
  pauses and posts to `human.input_needed` — you decide whether to top it up.

Code: `backend/nexus/core/llm/usage.py` → `check_daily_spend()` and
`check_task_budget()`.

### Recommended dashboards to build/look at first

1. **"Cost by role" chart** (7d, 30d) — tells you which department is the biggest
   spender. Usually Engineer + CEO dominate; Writer + QA are cheap.
2. **"Cost by model" chart** — tells you whether you're routing too much work to
   Sonnet when Haiku would suffice.
3. **Quota gauge** — current $/$5 daily cap. If you hit this regularly, raise the
   cap consciously rather than letting it surprise you.

---

## 2. How Agents Learn From Experience — and How They Know They're Correct

NEXUS doesn't rely on the LLM "just being smart." There are **seven** feedback
loops layered on top of every task.

### The loop, end to end

```
Task runs
   ↓
1. Episodic memory written     (what happened, with vector embedding)
   ↓
2. Semantic memory updated     (durable facts the agent now "knows")
   ↓
3. QA review (with rework)     (was the output actually correct?)
   ↓
4. Eval scoring (LLM-as-judge) (objective 0–1 quality score)
   ↓
5. RLHF-lite feedback signals  (your approvals, ratings, rejections)
   ↓
6. Preference patterns derived (what does this agent do well / poorly?)
   ↓
7. Prompt Creator improves     (new system prompt → benchmark → human approval)
   ↓
Optional: Fine-tuning pipeline (best episodes become training data)
```

### Each layer in plain English

**1. Episodic memory** — `backend/nexus/memory/episodic.py`
Every completed task writes a row with the full conversation, tools used, tokens,
duration, outcome, and a vector embedding. Next time a similar task comes in, the
agent recalls the 5 most similar past episodes and uses them as context. **The
system literally remembers what worked.**

**2. Semantic memory** — `backend/nexus/memory/semantic.py`
Durable facts (e.g., "our preferred Python style is black-formatted", "user X
prefers terse emails"). Stored per agent, per namespace, with a confidence score
that degrades if a later task contradicts it.

**3. QA review with multi-round rework** — `backend/nexus/agents/qa.py`
Every output passes through the QA agent. If QA rejects it, the original agent
gets specific feedback and tries again. Up to 5 rework rounds (configurable).
If still failing after that, it escalates to a human. **This is the main "how do
they know it's correct" mechanism.**

**4. Eval scoring (LLM-as-judge)** — `backend/nexus/integrations/eval/scorer.py`
A separate cheap model (Claude Haiku) scores each output on 4 dimensions —
relevance, completeness, accuracy, formatting — and produces an overall 0–1
score. This is **independent** of the QA agent, so you get two opinions.

**5. RLHF-lite feedback signals** — `backend/nexus/integrations/rlhf/feedback.py`
Captures 4 signal types whenever you (the human) interact with output:
- `approval` — did you approve or reject the irreversible action?
- `rating` — your thumbs-up / thumbs-down in the dashboard
- `rework` — how many QA rounds it took (1.0 if zero, 0.6 if one, 0.3 if 2+)
- `escalation` — did it need a human bailout?

**6. Preference updates** — `PreferenceUpdater` in the same file.
On a 30-day rolling window, this computes things like "Writer's approval rate is
87%, but drops to 62% on tool X" and writes these patterns back into the
Writer's semantic memory under namespace `preferences.feedback`. **The agent
literally reads its own performance review before the next task.**

**7. Prompt Creator (meta-agent)** — `backend/nexus/agents/prompt_creator.py`
When an agent's failure rate exceeds 10% in the last 20 tasks (or you trigger it
manually), the Prompt Creator analyses the failures, drafts an improved system
prompt, runs it against 10 fixed benchmark cases, and **proposes it for human
approval**. It never auto-deploys — one bad prompt could corrupt every task,
so a human signs off.

**8. Fine-tuning pipeline (optional)** —
`backend/nexus/integrations/fine_tuning/pipeline.py`
The highest-scoring episodes (eval ≥ 0.7) get exported as JSONL training data and
fed into a local Ollama fine-tune of Llama 3.1 8B. Over months this can produce
your own private model that costs ~zero per call.

### The honest answer to "how do they know they're correct"

Two independent checks (**QA agent** + **eval scorer**), then a human in the
loop for anything irreversible (file writes, emails, git pushes, hiring external
agents). Nothing that touches the real world ships without explicit human
approval — enforced at the tool adapter, not in agent code, so a misbehaving
agent literally cannot bypass it. See `backend/nexus/tools/guards.py`.

---

## 3. How to Implement This for Your Business

### Step 1 — Decide which of your work fits

NEXUS is good at four task categories today:

| Your business need | NEXUS agent that handles it |
|--------------------|------------------------------|
| Code, scripts, technical work | Engineer |
| Research, reports, competitive intel | Analyst |
| Emails, content, documentation | Writer |
| Quality control on everything above | QA (automatic) |
| Coordinating multi-step work | CEO + Director |

If your work doesn't match these, you can also create a custom agent role in the
agent builder UI (`backend/nexus/api/agent_builder.py`) — no code required.

### Step 2 — Stand up your workspace

```bash
make up          # starts all services (PostgreSQL, Redis, Kafka, backend, frontend)
make migrate     # creates the 34 database tables
make seed        # seeds the 7 default agents + their prompts
```

Then sign in (Google / GitHub / Microsoft SSO supported via OAuth2 —
`backend/nexus/api/oauth.py`), create a workspace, invite your team. Every
workspace is isolated at the database level via PostgreSQL Row-Level Security —
tenant A literally cannot read tenant B's data even with a SQL injection.

### Step 3 — Set your guard rails (do this on day one)

| Setting | Default | Where |
|---------|---------|-------|
| Daily $ cap | $5/day | `DAILY_SPEND_LIMIT_USD` env var |
| Per-task token budget | 50,000 | `agents.token_budget_per_task` (per agent) |
| Per-agent daily $ alert | unset | `/analytics/agent-cost-alerts` config |
| Irreversible tool approval | always on | `backend/nexus/tools/guards.py` (can't be disabled) |

### Step 4 — Connect your tools

Agents only get the tools you grant them, per role, in
`backend/nexus/tools/registry.py`. Out of the box:

- Web search, web fetch, file read — safe, no approval needed
- Code execution — sandboxed, no network
- **File write, send email, git push, hire external agent — all require human
  approval** before they run, every time

For business-specific tools (Salesforce, Stripe, your internal API), use the
plugin system in `backend/nexus/integrations/plugins/registry.py` — you can
register a Python package or an HTTP endpoint as a tool without touching core
code.

### Step 5 — Wire up the money

`backend/nexus/api/billing.py` integrates Stripe for two modes:

1. **Internal cost tracking** — every task gets a `BillingRecord` showing
   exactly what it cost you to run (LLM tokens + any external agent fees).
2. **Charge your customers** — if you resell NEXUS work, Stripe Connect can
   bill them per task or per month.

### Step 6 — Decide whether to use the marketplace

`backend/nexus/api/marketplace.py` lets you:

- **Publish** your specialised agents (e.g., a tax-prep agent you've fine-tuned)
  for other NEXUS users to hire via A2A
- **Browse** other people's specialist agents and hire them when your own team
  doesn't have the skill

Skip this on day one. Come back to it once you have one or two agents you've
actually fine-tuned and trust.

### Step 7 — Measure the ROI honestly

After two weeks of real use, look at four numbers:

1. **Total $ spent** (`/analytics/costs?period=14d`)
2. **Human time saved** — tasks completed without human intervention. Approval
   rate from `/analytics/approval-rates` tells you this directly.
3. **Quality** — average eval score per role. If it's < 0.7, that role's prompt
   needs work — trigger the Prompt Creator.
4. **Failure modes** — `/analytics/dead-letters` shows what's silently breaking.
   This should be near zero in steady state.

### Realistic timeline

| Week | What you should expect |
|------|------------------------|
| 1 | Setup, first 10 tasks. Lots of human approvals — that's normal and correct. |
| 2 | Approval rate climbs as agents learn your preferences via RLHF-lite |
| 3–4 | First Prompt Creator improvement round. Quality jumps measurably. |
| 6–8 | First fine-tune candidate ready (if you have ≥ 100 high-score episodes). |
| 12+ | Either confidently delegate a whole job function to NEXUS, or admit it's not
       a fit for that function. Don't wait longer than 12 weeks to make that call. |

---

## Quick links

- Token-usage analytics endpoints: `backend/nexus/api/analytics.py`
- Budget enforcement: `backend/nexus/core/llm/usage.py`
- Learning loop: `backend/nexus/memory/`, `backend/nexus/integrations/rlhf/`,
  `backend/nexus/integrations/eval/`, `backend/nexus/integrations/fine_tuning/`
- QA + Prompt Creator: `backend/nexus/agents/qa.py`,
  `backend/nexus/agents/prompt_creator.py`
- Multi-tenant / billing / marketplace: `backend/nexus/api/workspaces.py`,
  `billing.py`, `marketplace.py`
- Architecture deep dive: `docs/ARCHITECTURE.md`
- Risks and guard rails: `CLAUDE.md` §23
