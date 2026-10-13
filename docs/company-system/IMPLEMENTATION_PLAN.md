# Nexus company-system implementation plan

**Date:** 2026-10-05. **Status:** documentation delivered; runtime milestones unimplemented.\
Baseline: `6a8c8ef15e522aaa563d53776aef8dedc3209fcf`. Target: [SDD v0.2](../sdd/NEXUS_SDD_v0.2.md). Diagrams: [architecture](ARCHITECTURE.md).

**2026-10-13 implementation update:** See the [complete feature/time roadmap](DELIVERY_ROADMAP.md) and [current progress](PROGRESS.md). Contract/policy foundations and a standalone PostgreSQL journal are delivered and tested. This original plan's gate definitions remain authoritative; full M0/M1 and operating milestones are still open.

## Task contract for this documentation delivery

Create a full design, architecture views, proposed ADRs, and a milestone backlog for DravenIQ's internal company system. Preserve confirmed owner choices, distinguish target behavior from existing code and tested operation, and keep all runtime files unchanged.

Touched paths: this directory, `docs/sdd/NEXUS_SDD_v0.2.md`, `docs/DECISIONS.md`, `docs/BACKLOG.md`, `docs/ERRORLOG.md`, `docs/CHANGELOG.md`, plus top-level README/CLAUDE pointers. Verification: new links/anchors, unique IDs, milestone/ADR traceability, diagram syntax where a parser is available, and Git whitespace/scope review. Definition of done: saved reviewable documents and an honest validation handoff. This does not complete executable M0 fixtures or authorize deployment.

## Delivery rules

Work in small reviewable changes, each with acceptance evidence. Use the repository's branch/PR policy and plain Git; the checked remote has `main` as default and no `develop` branch. Do not assume another repository's integration model. Human merge and any remote publishing follow existing authority.

Freeze contracts, policy cases, evaluation inputs and criteria before implementation optimization. Do not change an evaluator to make a failing design pass. Maintain an evidence manifest per milestone: source commit, environment, configuration versions, commands, results, artifacts, limitations and remaining blockers. Mock/unit, real integration, ARM64, paid-provider and externally delivered outcomes are distinct evidence classes.

Dependencies below are hard gates for activating the relevant functionality. UI/contract scaffolding can be developed in parallel when it cannot execute effects or claim production readiness. No calendar estimate is implied; milestone exits are outcome-based.

## M0 — Freeze the baseline and implementation contracts

**Backlog:** BACKLOG-068. **Prerequisite:** current remote/local state reconciled.\
**Current status:** design documents delivered; executable preparation open.

Deliverables:

- Persist SDD, architecture views, proposed ADR-094–099, and this acceptance plan.
- Reconcile legacy approval, context, queue, QA and tool-entry findings against the exact implementation base; preserve the baseline review.
- Specify versioned JSON schemas, action canonicalization, revision conflicts, error taxonomy, and legacy-to-company mapping.
- Create fake-model scenarios and failure injection seams for action, approval, budget and recovery. Freeze the 30-question Brain pack and StockFlow readiness checklist.
- Inventory old endpoint consumers, DB schemas and migration heads; identify who owns each task during cutover.
- Obtain a nominated committed StockFlow base. Do not copy the currently dirty product checkout by assumption.

Exit: an implementation branch has reproducible offline fixtures and frozen contracts/checklists. Saved prose alone is not that exit. No runtime authority promotion occurs in M0.

## M1 — Prove one governed durable execution path

**Backlog:** BACKLOG-069. **ADRs:** 095, 096, 098. **Depends on:** M0 executable fixtures.

Suggested change sequence:

1. Prove the exact Pydantic AI 2.54.0 / DBOS 3.2.0 compatibility spike with the retained Litestar/ORM pins; update the lockfile only when import, API-family, hooks, usage and deferred-output tests pass. Recheck release/ARM64 compatibility first.
2. Add additive Alembic migrations for company mapping, work/action/approval/receipt state, budget reservation and durable enqueue. Register stable agents and DBOS capabilities before launch.
3. Route one fake-model work item through the harness. Commit pending approval and release the segment; resume through a new segment with unchanged limits and exact action binding.
4. Put every tool adapter, built-in/plugin mutation and workspace write behind the same policy gate. Remove fail-open QA behavior in the company path.
5. Implement registered model profiles, two provider adapters, deterministic eligible routing, capped fallback, dated prices, atomic reservations and usage reconciliation.
6. Implement persistent deduplication, fenced leases, effect-intent receipts, uncertain-outcome reconciliation and one retry owner per operation.
7. Feature-gate new intake; prove crash/restart and compatible workflow upgrade without legacy/new dual ownership.

Exit: real PostgreSQL tests prove two-session approval visibility, stale/edited/revoked decision rejection, atomic enqueue, competing workers, cost reservations and restart recovery. Fake/offline provider conformance is mandatory; live paid provider checks are separate, budgeted activation evidence. No company-scale autonomy claim yet.

## M2 — Build the evidence-backed Company Brain

**Backlog:** BACKLOG-070. **ADR:** 094. **Depends on:** M1 company/auth boundaries.

Deliver ontology tables, provenance claims and validity history, immutable source/artifact references, permission-aware hybrid retrieval, contradiction/supersession handling, and a single ContextAssembler. Include attachments and selected workspace files in actual prompts. Expose typed search/entity/evidence APIs and source freshness.

Exit: frozen 30-question pack meets at least 27 answer rubrics and all permission/false-completion cases. A source update changes downstream context under an explicit revision; inaccessible sources never enter prompts or derived artifacts. Plans and hypotheses cannot be returned as verified outcomes.

## M3 — Make management operate a bounded company plan

**Backlog:** BACKLOG-071. **ADRs:** 094, 096, 099. **Depends on:** M1 and M2.

Deliver owner mandates, department charters, metric-based goals, typed plan/DAG validation, quotas inherited by child tasks, event-driven eligibility, explicit blocked states, commitments and operating report queries. Add Today, company, plan/work and approval UI views. Record decisions and plan revisions without generating hidden authority.

Exit: an internal research/report workflow completes with cited facts and ledger-derived costs. Idle polling performs zero model calls. Approval/budget waiting releases execution capacity. Retries, rework, fallback and new segments share logical counters. Reports remain truthful across failed, blocked and unknown cases.

## M4 — Prove the native Pi builder

**Backlog:** BACKLOG-072. **ADR:** 097. **Depends on:** M1 harness; M3 approved work plans. Deployment setup is a separate authorized step.

Deliver a restricted runner protocol, rootless Podman setup, approved revision workspaces, pinned tool images, staged registry access, path/symlink checks, resource/disk/time limits, command/artifact receipts and independent verification. Keep model/database secrets and production write mounts outside the sandbox.

Exit: one approved StockFlow engineering task is reproduced on ARM64 with baseline/post-change evidence and one bounded worker. Escape/path, forbidden network, resource exhaustion, cancellation, stale lease and missing-tool cases terminate honestly. A patch is reviewable without a Git push or production release. If StockFlow's representative checks do not fit the Pi envelope, record the constraint and revise the hosting plan rather than weakening evidence.

## M5 — Complete the first company operating cycle

**Backlog:** BACKLOG-073. **ADRs:** 094, 099. **Depends on:** M2–M4 plus configured notification prerequisites.

Deliver the [StockFlow readiness cycle](../sdd/NEXUS_SDD_v0.2.md#3-first-operating-cycle-stockflow-customer-readiness): strategy assessment, bounded plan, native change, independent verification, demo/presentation artifact, support draft, owner report, dashboard events and email ledger. Add Customers & Support, Decisions, Knowledge and Audit views.

Exit: all artifacts link to one goal/plan lineage, receipts and actual acceptance results. Browser tests cover reconnect, role/resource authorization, readable source dates and stale approval conflicts. Offline email tests prove retry/deduplication; configured live tests separately prove provider acceptance and delivery/reconciliation. No customer message is sent by this pilot unless separately authorized.

## M6 — Earn delegation and demonstrate recovery/portability

**Backlog:** BACKLOG-074. **ADRs:** 095, 097, 099. **Depends on:** reviewed M5 cycles.

Deliver operating metrics, owner review packets, authority-delta review, independent encrypted backups, restore manifests, workflow version/drain runbook, and a portable cloud/VPS profile. Test Pi capacity, 24-hour bounded soak, process kills, uncertain effects and private authenticated access.

Exit: at least 20 reviewed completed work items have consistent receipts and verification, recovery drills pass, and no unresolved unauthorized action or missing outcome is hidden as success. Restore meets the declared RPO/RTO in a disposable environment. The owner explicitly decides Delegated mode; Board mode is a later decision after several stable approved cycles. No automatic promotion.

## Deferred work

| Backlog | Candidate | Activation condition |
| --- | --- | --- |
| BACKLOG-075 | Meta Harness | Owner requests it after stable operation; frozen offline evaluation and explicit version promotion |
| BACKLOG-076 | Dedicated temporal graph engine | Measured retrieval/traversal limits justify additional infrastructure |

External A2A hiring, a SaaS marketplace, broad social/customer automation and financial transactions require new scoped plans. Voice and visual polish can reuse existing code but must not postpone runtime proof.

## Acceptance matrix

| ID | Requirement | Gate | Proof required |
| --- | --- | --- | --- |
| GOV-01 | Every mutation path enforces context, role/resource policy and action receipt | M1 | Built-in, plugin, MCP and runner boundary tests; denied effects absent |
| GOV-02 | Exact approval is visible and bound across sessions | M1 | Two real DB sessions; hash/edit/expiry/revocation/stale-resource cases |
| GOV-03 | Approval waiting releases execution/build capacity | M1/M4 | Single-slot queue accepts another eligible item; no held sandbox |
| GOV-04 | Owner pause/revocation survives restart and cancellation reconciles issued effects | M1/M4 | Persisted pause, boundary rechecks, cancelled sandbox and unknown-effect status |
| DUR-01 | Business commit and enqueue cannot diverge | M1 | Real transaction crash/rollback around enqueue |
| DUR-02 | Duplicate/concurrent workers cannot double authorize | M1 | Persistent dedup, lease fencing, stale-worker rejection |
| DUR-03 | Uncertain external effects are not blindly repeated | M1/M5 | Crash after provider acceptance before receipt; provider reconciliation |
| DUR-04 | Registered workflow/model versions can resume | M1/M6 | Kill/restart and compatible upgrade; incompatible version blocked/drained |
| COST-01 | Concurrent requests cannot over-allocate company/day/work budget | M1 | Atomic reservation races, midnight rollover, unknown usage holds |
| COST-02 | Failed calls, fallbacks and child work share limits | M1/M3 | Counter/quota tests across all segments and rework |
| LLM-01 | Routing preserves capability, schema and data policy | M1 | OpenAI/Google/compatible adapter conformance, capped fallback, unknown price deny |
| BRAIN-01 | Claims have source/type/time and conflict history | M2 | Frozen questions and changed-source/contradiction cases |
| BRAIN-02 | Context includes intended attachment/workspace evidence | M2 | Actual agent prompt assertions, omission manifest and bounded artifact retrieval |
| BRAIN-03 | Unauthorized facts stay out of context and derived outputs | M2 | Cross-company/customer permissions including summaries |
| MGMT-01 | Plans have valid dependencies, measurable acceptance and bounded children | M3 | DAG/cycle/revision/quota tests and blocked dependency handling |
| MGMT-02 | Idle management spends no model tokens | M3 | Deterministic eligibility/scheduler test and ledger observation |
| BUILD-01 | Builder is isolated and respects paths, quotas and network policy | M4 | Real ARM64 sandbox cases, symlink traversal, kill/cancellation and output limits |
| VERIFY-01 | Baseline failures and verifier uncertainty cannot become approvals | M1/M4 | Timeout/error/inconclusive tests and independent behavior evidence |
| PILOT-01 | Full StockFlow cycle links real outcomes to the mandate | M5 | End-to-end lineage, patch/check evidence, presentation, support draft and report |
| UI-01 | Owner can inspect evidence and approve only current authorized actions | M5 | Browser auth, revision-conflict, reconnect and accessible work views |
| NOTIFY-01 | Meaningful alerts deduplicate and represent delivery honestly | M5 | Ledger/provider retry tests plus separate configured live receipt evidence |
| OPS-01 | Pi profile operates privately within capacity | M6 | ARM64 startup/build, 24-hour soak, authenticated private access |
| OPS-02 | Backup can restore matching DB/artifacts and resume safely | M6 | Independent storage, disposable restore and uncertain-effect reconciliation |
| AUTO-01 | Oversight mode changes only through owner-approved policy | M6 | Authority-delta record, reviewed outcomes, no automatic promotion |

## Migration and release runbook outline

1. Recheck remote, branch, local changes, instruction files, migration head, Pi capacity and storage. Preserve concurrent StockFlow changes.
2. Snapshot database/artifacts and prove the snapshot is restorable before production migration. Record active legacy tasks and approvals.
3. Apply additive company mappings and schema; run contract/RLS tests; enable only isolated fake-model intake.
4. Configure registered model IDs/prices, US$5 cap, sender/allowlisted owner, secrets and backup destination through approved setup. Do not put credentials in artifacts.
5. Reconcile or drain legacy intake and unfinished effects. Never import a seen marker as a successful receipt. Re-review legacy approvals without exact binding.
6. Activate one company execution owner for the approved pilot; capture lineage and ledger evidence. Verify reports and notifications before broadening authority.
7. On failure, stop new intake, preserve/reconcile already-issued effects, drain compatible workers, and restore or forward-correct with retained audit history.
8. Cloud move uses the same manifest/IDs, a compatible runtime and single-owner cutover. Do not activate a second scheduler on copied state.

## Inputs required before live activation

Owner-approved mandate and readiness checklist; nominated StockFlow commit; provider/model allowlist and dated prices; approved credential references; verified sender and owner recipient; independent backup destination; Pi install/route authorization; and explicit production intake decision. These are setup inputs, not unresolved questions that block saving this design.

## Handoff status

The SDD, diagrams, ADR proposals and backlog are saved. [Document validation](VALIDATION_2026-10-05.md) records the completed checks and limits. M0 executable fixtures and M1–M6 remain open. The 2026-10-04 unit/static baseline and the dependency-resolution dry run are historical scoped evidence; they do not validate the proposed new runtime. Keep implementation and operating proof separately recorded as work proceeds.
