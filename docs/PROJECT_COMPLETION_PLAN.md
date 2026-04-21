# PROJECT_COMPLETION_PLAN.md
## NEXUS — Path From Phase 8 to General Availability

> **Purpose.** Consolidate every remaining work item from `BACKLOG.md`, `IDEAS.md`,
> `DECISIONS.md`, and `CHANGELOG.md` into an executable phase-by-phase plan that
> takes NEXUS from its current state (Phase 8, 2026-04-01) to **v1.0 GA** and
> defines the first post-GA horizon.
>
> **Authoritative plan.** When this document disagrees with `BACKLOG.md` line
> items, this document wins — BACKLOG is the append-only capture log; this is
> the executable schedule.
>
> **Reading order.** Section 1 (where we are) → Section 2 (exit criteria) →
> Section 3–6 (phases 9–12) → Section 7 (cross-cutting) → Section 8 (RACI).

---

## 1. Where we are today

As of 2026-04-01 (Phase 8 ship), NEXUS has closed the following scope:

| Phase | Theme                                   | State     | Key artifacts |
|-------|-----------------------------------------|-----------|---------------|
| 0     | Foundations (Kafka, Redis, pgvector)    | Shipped   | docker-compose.yml, migrations 001–002 |
| 1     | CEO + Engineer single-path              | Shipped   | `agents/ceo.py`, `agents/engineer.py`, 50-task stress passed 100% |
| 2     | QA agent, meeting rooms, Prompt Creator | Shipped   | `agents/qa.py`, `kafka/meeting.py`, `prompt_benchmarks` |
| 3     | Hardening, audit, A2A, circuit breakers | Shipped   | `gateway/`, `core/circuit_breaker.py`, SSE hardening |
| 4     | Multi-tenant, marketplace, Temporal     | Shipped   | Workspaces, RLS, `integrations/stripe/`, Temporal base |
| 5A    | Security & compliance                   | Shipped   | OAuth2/OIDC, RLS policies, injection classifier, Stripe |
| 5B    | Self-improvement & ops                  | Shipped   | Provider health, model benchmarks, agent cost alerts, scheduler |
| 5C    | Observability baseline                  | Shipped   | OTel decorators, structured logs, audit retention |
| 6     | Agent federation registry (centralized) | Shipped   | Centralized agent registry (ADR-060) |
| 7     | Director agent, enterprise security     | Shipped   | `agents/director.py`, meeting-room convergence |
| 8     | Business-grade platform                 | Shipped   | E2B sandbox, SLA engine, Temporal deep rewrite, Jaeger, Uptime Kuma, API keys, invitations |

**Still open at top of Phase 9:**

- [`BACKLOG-001`](./BACKLOG.md) — MCP package docstring/type-hint audit (deferred; now urgent for plugins).
- [`BACKLOG-005`](./BACKLOG.md) — Confirm embedding async timing gap.
- [`BACKLOG-006`](./BACKLOG.md) — Pick log aggregation backend (Loki vs OpenSearch).
- [`BACKLOG-008`](./BACKLOG.md) — Agent naming: generic roles vs named personas.
- [`BACKLOG-010`](./BACKLOG.md) — Shadcn/ui migration (branch exists, unmerged).
- [`BACKLOG-017`](./BACKLOG.md) — Ollama local-model integration test.
- [`BACKLOG-018`](./BACKLOG.md) — Dynamic per-agent model assignment via API.
- [`BACKLOG-035`](./BACKLOG.md) — Agent performance leaderboard + auto model pick.
- [`BACKLOG-037`](./BACKLOG.md) — Plugin system for custom MCP providers.
- [`BACKLOG-041`](./BACKLOG.md) — Federated multi-NEXUS interop (centralized done; federated deferred).
- [`BACKLOG-042`](./BACKLOG.md) — UCP evaluation (deferred; commerce not yet a task category).
- [`BACKLOG-043`](./BACKLOG.md) — AP2 evaluation (ADR-059; adopt only if paid A2A launches).
- [`BACKLOG-044`](./BACKLOG.md) — ANP evaluation (ADR-058; wait for IETF RFC 2026–2027).
- [`BACKLOG-046`](./BACKLOG.md) — SOPS / Vault secrets migration.
- [`BACKLOG-047`](./BACKLOG.md) — OTel distributed tracing end-to-end coverage (decorators exist; not every surface is wired).
- [`BACKLOG-048`](./BACKLOG.md) — Fine-tuning pipeline (episodic → dataset → Ollama).
- [`BACKLOG-050`](./BACKLOG.md) — Multi-modal tool calls (images, PDFs, audio).
- [`BACKLOG-051`](./BACKLOG.md) — RLHF-lite feedback loop.

These 18 items define the remaining runway.

---

## 2. Global exit criteria (how we know we're done)

GA (v1.0) ships when **all** of the following are green:

1. **Reliability** — 99.5% monthly uptime over a rolling 90-day window on the
   reference deployment; error budget burn alerts wired via Uptime Kuma.
2. **Performance** — P50 task latency ≤ 45s, P95 ≤ 4m, on the canonical 50-task
   benchmark, measured via Jaeger spans and `llm_usage`.
3. **Cost** — Mean cost per completed task ≤ $0.08 with fallback chain engaged;
   ≤ $0.02 with a fine-tuned Ollama model on eligible roles.
4. **Security** — External penetration test passed (OWASP Top 10 + LLM Top 10);
   secrets stored in SOPS/Vault, not `.env`; signed Agent Cards.
5. **Extensibility** — At least 3 third-party plugins live in a published
   registry, installable without a code change.
6. **Federation** — Two independent NEXUS instances discover each other through
   a federated directory (not the centralized registry) and complete a
   cross-instance task with AP2-style mandates for settlement.
7. **Learning** — RLHF-lite improves mean QA approval rate by ≥ 10pp over the
   Phase 8 baseline on a held-out task set.
8. **Docs** — `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`
   reconciled; a public `CHANGELOG.md` v1.0.0 entry exists.

---

## 3. Phase 9 — Learning Layer (4 weeks)

**Goal.** Turn NEXUS's accumulated data into a compounding advantage. This is
the highest-ROI remaining phase because the data already exists — only the
training/feedback infrastructure is missing.

**Theme track.** One Track only. No parallel work — learning touches memory,
prompts, and models at once; parallel tracks will collide.

### 3.1 Deliverables

| ID    | Item                                             | Files / surfaces                                          |
|-------|--------------------------------------------------|-----------------------------------------------------------|
| 9.1   | Dual-score feedback UI (helpful + safe)          | `frontend/src/components/TaskFeedback.tsx`, `api/feedback.py` |
| 9.2   | `task_feedback` table + API                      | Migration 008, `POST/GET /api/tasks/{id}/feedback`         |
| 9.3   | Feedback → semantic memory preference writer     | `core/memory/preferences.py`, extends `semantic_memory`   |
| 9.4   | Per-role approval-rate metric                    | `analytics/approval_rates.py`, dashboard widget            |
| 9.5   | Fine-tuning dataset exporter                     | `core/learning/dataset.py` (JSONL format, role-partitioned) |
| 9.6   | Ollama fine-tune job runner (LoRA)               | `core/learning/ollama_trainer.py`, `fine_tuning_jobs` table |
| 9.7   | Model swap via API (per role/agent)              | `PATCH /api/agents/{id}/model`, satisfies `BACKLOG-018`    |
| 9.8   | Benchmark harness: fine-tuned vs cloud           | Extends `core/llm/benchmarking.py`                         |
| 9.9   | Multi-modal `tool_analyze_image` + `tool_analyze_pdf` | `tools/adapter.py`, Claude/Gemini vision path           |
| 9.10  | Tool registry gating: multi-modal per role       | `tools/registry.py` — grants image tools to Analyst, Engineer |

### 3.2 Closes

`BACKLOG-018`, `BACKLOG-035`, `BACKLOG-048`, `BACKLOG-050`, `BACKLOG-051`,
`IDEA-003` (Feedback Loop), `IDEA-009` (A/B + leaderboard), `IDEA-013` (Fine-tuning),
`IDEA-019` (Safe RLHF-V).

### 3.3 Risks and guards

- **Distribution shift.** Fine-tune only roles with ≥ 500 approved episodes.
  Below that threshold the dataset exporter refuses to generate.
- **Preference pollution.** All preference writes go through the same
  newest-wins upsert as regular semantic memory (`BACKLOG-003` resolution), but
  tagged `source=feedback` so the Prompt Creator can weight them.
- **Cost runaway from multi-modal.** Image tool calls charge to a separate
  `multimodal_budget_per_task` setting, defaulting to $0.25. Hitting it aborts
  the task with a human-readable error, not a silent fallback.

### 3.4 Exit gate for Phase 9

- Mean QA approval rate on a frozen 50-task benchmark rises ≥ 10pp after the
  first fine-tuned model ships.
- At least one agent role runs on a fine-tuned Ollama model in the reference
  deployment for ≥ 7 days without regressions vs the cloud baseline.
- Multi-modal tools process the canonical image/PDF test suite at 100% success.

---

## 4. Phase 10 — Federation & Marketplace (4 weeks)

**Goal.** Decentralize the agent registry built in Phase 6 and stand up the
economic primitives for inter-instance agent hire.

### 4.1 Deliverables

| ID     | Item                                                 | Files / surfaces                                   |
|--------|------------------------------------------------------|----------------------------------------------------|
| 10.1   | Federated directory (AGNTCY-style)                   | `integrations/federation/` — OCI-artifact Agent Cards |
| 10.2   | Sigstore signing for Agent Cards                     | `integrations/federation/signing.py`                |
| 10.3   | DID-based agent identity (W3C)                       | `gateway/identity.py`, `a2a_identities` table       |
| 10.4   | Cross-registry capability query                      | `GET /federation/search?skill=…&max_cost=…`        |
| 10.5   | gRPC transport for A2A (opt-in)                      | `gateway/grpc_server.py`, grpcio, reuses auth       |
| 10.6   | AP2 mandate issuance + verification                  | `integrations/ap2/`, extends `human_approvals`      |
| 10.7   | External-hire settlement via Stripe + AP2 mandates   | `integrations/billing/settlement.py`                |
| 10.8   | Marketplace reputation signals (verified hires)      | Extends `marketplace_reviews` — adds `verified` flag |
| 10.9   | Federation connectivity dashboard                    | `frontend/src/pages/Federation.tsx`                 |
| 10.10  | SOPS/Vault migration for provider keys               | `infra/secrets/`, removes `.env` usage in deploy    |

### 4.2 Closes

`BACKLOG-007`, `BACKLOG-041`, `BACKLOG-043`, `BACKLOG-046`, `IDEA-014`
(A2A marketplace), `IDEA-017` (Agent registry), `IDEA-030` (gRPC), `IDEA-032`
(AP2 mandates).

### 4.3 Risks and guards

- **Trust in federated capability claims.** Mandatory Sigstore signatures on
  every Agent Card plus a 30-day "probation" before a new external agent
  counts toward a tenant's search ranking.
- **Regulatory.** AP2 mandates are treated as "pre-authorized approvals,"
  extending the existing `human_approvals` audit trail — no separate finance
  system. Crypto settlement is **out of scope** for GA.
- **Protocol churn.** ANP (`BACKLOG-044`) and UCP (`BACKLOG-042`) remain
  deferred. Federation uses AGNTCY + A2A v0.3 only; ANP adapter is a Phase 12+
  consideration (see Section 6).

### 4.4 Exit gate for Phase 10

- Two independent NEXUS deployments complete a cross-instance task,
  mandate-settled, without human intervention beyond the initial approval.
- `integrations/federation/` passes a chaos test where the directory is
  partitioned for 5 minutes — the system degrades to cached Agent Cards and
  recovers automatically.

---

## 5. Phase 11 — Extensibility Surface (3 weeks)

**Goal.** Let third parties extend NEXUS without forking. Tools first, then
workflows — full custom-agent plugins are deferred to Phase 12.

### 5.1 Deliverables

| ID     | Item                                             | Files / surfaces                                     |
|--------|--------------------------------------------------|------------------------------------------------------|
| 11.1   | MCP package docstring + type-hint audit          | `integrations/mcp/` (closes `BACKLOG-001`)            |
| 11.2   | Plugin manifest schema (YAML)                    | `plugins/schema/plugin.schema.yaml`                   |
| 11.3   | Plugin loader with hot-reload                    | `core/plugins/loader.py`, lifecycle hooks             |
| 11.4   | Sandboxed plugin execution via E2B               | Reuses `tools/sandbox/client.py`                      |
| 11.5   | Plugin registry CRUD + signature verification    | `api/plugins.py`, `plugins` table                     |
| 11.6   | Plugin CLI: `nexus plugin install/uninstall/list`| `scripts/cli/plugin.py`                               |
| 11.7   | Visual workflow builder (React Flow)             | `frontend/src/pages/WorkflowBuilder.tsx`              |
| 11.8   | Workflow DAG spec → Kafka compiler               | `core/workflows/compiler.py`                          |
| 11.9   | Workflow template library (seed: 5 workflows)    | `templates/workflows/*.yaml`                          |
| 11.10  | Webhook + Slack integration as reference plugins | `plugins/slack/`, `plugins/webhook-router/`           |
| 11.11  | Shadcn/ui migration merged                       | Closes `BACKLOG-010`; rebase branch `claude/finish-shadcn-migration-1XmXl` |

### 5.2 Closes

`BACKLOG-001`, `BACKLOG-010`, `BACKLOG-037`, `IDEA-005`, `IDEA-007`, `IDEA-023`
(DAG editor), `IDEA-024` (plugin system), `IDEA-026` (integration hub),
`IDEA-034` (NL workflow compiler — **basic template-based mode only**; LLM
compilation deferred to Phase 12).

### 5.3 Risks and guards

- **Malicious plugins.** All plugin tool calls run inside the E2B sandbox. The
  manifest declares max `cpu_ms`, `mem_mb`, and egress destinations; the loader
  enforces them. Unsigned plugins cannot be installed on production tier.
- **CEO vs explicit workflow conflict.** Workflows override CEO decomposition
  only when attached at task submission time. Unattached tasks go through the
  normal CEO path.
- **Manifest churn.** v0 manifest is versioned (`apiVersion: plugins.nexus.dev/v1alpha1`)
  so GA can ship v1beta1 without breaking early plugins.

### 5.4 Exit gate for Phase 11

- A non-contributor can build, sign, publish, and install a plugin from an
  external repository with no NEXUS source-tree changes.
- The seeded workflow templates execute end-to-end in the reference deployment
  with a 100% pass rate on their canonical fixtures.

---

## 6. Phase 12 — GA Hardening and Launch (2 weeks)

**Goal.** Ship v1.0 — stop feature work, harden, document, and publish.

### 6.1 Deliverables

| ID     | Item                                                  | Owner         |
|--------|-------------------------------------------------------|---------------|
| 12.1   | External penetration test (OWASP + LLM Top 10)        | Security vendor |
| 12.2   | 7-day soak test on the reference deployment           | SRE agent (internal) |
| 12.3   | Ollama local-model integration test matrix            | Closes `BACKLOG-017` |
| 12.4   | Log aggregation pick + deployment (Loki recommended)  | Closes `BACKLOG-006` |
| 12.5   | Embedding async-timing verification + doc             | Closes `BACKLOG-005` |
| 12.6   | Agent persona decision (generic vs named)             | Closes `BACKLOG-008`; record ADR-068 |
| 12.7   | Full OTel coverage audit (every agent, every tool)    | Closes `BACKLOG-047` |
| 12.8   | Docs sweep: README, AGENTS, ARCHITECTURE, DECISIONS   | Writer agent + human review |
| 12.9   | Compliance mapping to NIST CAISI draft (if published) | `docs/compliance/nist_caisi_mapping.md` (`IDEA-029`) |
| 12.10  | Launch CHANGELOG 1.0.0, git tag, container image push | Release coordinator |

### 6.2 Closes

`BACKLOG-005`, `BACKLOG-006`, `BACKLOG-008`, `BACKLOG-017`, `BACKLOG-047`.

### 6.3 Exit gate for GA (v1.0)

All eight exit criteria from Section 2 green. Release notes published. First
paying customer onboarded. Roadmap for v1.1 (Section 7, creative track)
linked from `README.md`.

---

## 7. Cross-cutting work streams (run parallel to phases)

### 7.1 Observability

- Keep Jaeger + OTel coverage on the critical path every phase. A span with
  more than 2s unattributed time is a regression and blocks the phase exit.
- Uptime Kuma probe set grows with each phase (Phase 9 adds fine-tune worker,
  Phase 10 adds federation directory, Phase 11 adds plugin loader).

### 7.2 Error cascade prevention (`IDEA-018`)

- Ship a lightweight CEO-plan validator in Phase 9 (reuses QA LLM). Promote to
  a standalone Validator agent in Phase 10 only if error cascade is still a
  measurable cost sink after the learning layer ships.

### 7.3 Hierarchical planning (`IDEA-025`)

- Prototype in Phase 11 behind a feature flag (`HIERARCHICAL_PLANNING=true`).
  Promote to default in v1.1 if the Engineer agent's self-decomposition
  beats CEO's flat decomposition on the workflow template suite.

### 7.4 Self-healing SRE (`IDEA-020`)

- Extend Phase 8's Engineer-in-SRE-mode experiment with a dedicated policy file
  (`infra/sre/policy.yaml`) in Phase 12. Scope strictly to NEXUS-internal
  healing. No external application healing — ever.

---

## 8. RACI (per phase)

| Role                | R | A | C | I |
|---------------------|---|---|---|---|
| CEO agent           |   |   | x | x |
| Engineer agent      | x |   |   |   |
| Director agent      |   | x | x |   |
| QA agent            | x |   |   |   |
| Writer agent        | x |   |   |   |
| Human maintainer    |   | x |   |   |
| Security reviewer   |   |   | x | x |

- Director **approves** phase exit gates (owns acceptance).
- Engineer & Writer are **responsible** (do the work).
- QA is **responsible** for evaluation signals and blocks merges on regressions.
- Human maintainer retains final accountability for security-sensitive steps
  (Phase 10 mandates, Phase 11 plugin signing, Phase 12 launch).

---

## 9. Schedule summary

| Phase | Weeks | Ends (target) |
|-------|-------|---------------|
| 9     | 4     | 2026-05-19    |
| 10    | 4     | 2026-06-16    |
| 11    | 3     | 2026-07-07    |
| 12    | 2     | 2026-07-21 (v1.0 GA) |

Total runway from today (2026-04-21): **13 weeks** to GA.

---

## 10. What lives after GA

Everything in `CREATIVE_ROADMAP.md`. That file is the v1.1+ horizon and is the
deliberate home for ideas that would pull focus away from shipping 1.0.

---

*Authored by:* claude_code
*Source inputs:* `BACKLOG.md` (051 items), `IDEAS.md` (034 ideas), `DECISIONS.md`
(ADR-001 through ADR-067), `CHANGELOG.md` (Phase 0 through Phase 8).
*Last updated:* 2026-04-21
