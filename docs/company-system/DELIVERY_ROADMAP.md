# Nexus feature delivery roadmap and estimate

**Estimate date:** 2026-10-13 (Asia/Bangkok). **Baseline:** `6a8c8ef`.\
**Status:** implementation authorized; foundation work started locally. Target: [SDD](../sdd/NEXUS_SDD_v0.2.md). Acceptance: [implementation plan](IMPLEMENTATION_PLAN.md).

## Estimate assumptions

These are engineering estimates, not measured delivery promises. One experienced engineer works a focused five-day week with AI assistance and owner reviews available. An engineering day is roughly six productive hours. The same engineer handles backend, frontend, testing and deployment preparation. Existing API/UI/parsers/auth are reused where validated. No parallel agent team is assumed. External credentials, owner decisions and infrastructure access must be available when their gate is reached.

The initial US$5/day is Nexus's operating model budget; it is not a software-development time budget. Model calls used in product tests must fit their explicit test allocation. Native Pi build capacity, Pydantic AI/DBOS compatibility, migration correctness and the StockFlow checklist can move the estimate. Re-estimate after M1 and the first representative Pi build.

## Milestone estimates

| Milestone | Deliverable | Engineering days | Activation dependency |
| --- | --- | --- | --- |
| M0 | Contract freeze, approval/hash policy, fake scenarios, Brain pack, pilot checklist and migration inventory | 2–3 | Baseline reconciled; initial implementation underway |
| M1 | Durable engine, all-entry-point tool governance, approvals, model gateway, budget ledger and recovery | 8–12 | M0, real DB/replay/provider conformance |
| M2 | Ontology, provenance, retrieval, permissions and unified context | 6–9 | M1 company/auth boundary |
| M3 | Departments, goals, planning, scheduler, commitments and management views | 6–9 | M1/M2 |
| M4 | Native isolated runner, verification and representative Pi/StockFlow build | 5–8 | M1/M3 plus authorized Pi setup |
| M5 | Complete readiness cycle, presentations, support drafts, owner reports, dashboard/email | 6–9 | M2–M4 plus notification setup |
| M6 | Delegation review, backup/restore, soak/recovery, private deployment and cloud portability | 5–8 | M5 operating evidence |
| **Core total** | **M0–M6** | **38–58** | **7.6–11.6 focused working weeks** |

Add 25% integration/unknowns contingency: **48–73 engineering days, approximately 10–15 calendar working weeks** under these assumptions. Time awaiting access/reviews is additional. A supervised M5 pilot is **33–50 base days**, or **8–13 weeks with contingency**. First reviewable foundation/demo is approximately **1–2 weeks**, before production pilot acceptance.

Board oversight needs at least 20 reviewed completed work items, recovery drills and several stable approved operating cycles. Allow **2–4 or more weeks of observed operation** after the pilot; this is evidence collection, not a guarantee that promotion will be appropriate. The owner decides authority changes.

## Feature coverage

The feature rows are work packages inside milestone estimates; do not add their rough sizes again to the total.

| Feature | Delivery | Rough effort within milestone | Acceptance |
| --- | --- | --- | --- |
| Versioned company contracts and schemas | M0 | 1–2 days | Strict JSON boundaries, defaults, source identity and revision validation |
| Frozen evaluation scenarios and pilot checklist | M0 | 1 day | Cases/criteria exist before optimization; unverified inputs remain explicit |
| Durable work/action ledger and DBOS execution | M1 | 2–3 days | Atomic enqueue, stable IDs, restart and compatible upgrade |
| Exact approvals, pause/cancel and scoped authority | M1 | 2–3 days | Two-session visibility, expiry/edit/revocation checks, single use |
| Multi-provider model registry and gateway | M1 | 1–2 days | Explicit API family, capabilities, evaluated selection/fallback |
| Cost reservations and request/tool/rework limits | M1 | 1–2 days | Concurrent caps, unknown billing holds and limits preserved across segments |
| Tool registry and governance coverage | M1 | 1–2 days | Built-in, plugin, workspace and MCP mutations obey the same gate |
| Company ontology and source-backed claims | M2 | 2–3 days | Typed relationships, provenance, validity and conflict/supersession |
| Ingestion, hybrid retrieval and context | M2 | 2–3 days | Actual attachments/workspace evidence reaches prompts; permission filtering |
| Knowledge/evidence API and views | M2 | 1–2 days | Citations, freshness, source revision and access tests |
| Department charters and company mandate | M3 | 1–2 days | Management, strategy, builder, QA, presentation, support and operations scopes |
| Goal decomposition, plan DAG and bounded loops | M3 | 2–3 days | Valid dependencies, inherited quotas, explicit acceptance and stops |
| Deterministic scheduling and commitments | M3 | 1–2 days | Idle checks cost no tokens; due events and blocked dependencies are visible |
| Today/company/goals/work/approval views | M3 | 2–3 days | Owner can understand work and safely approve current proposals |
| Native Git workspace and rootless sandbox runner | M4 | 2–3 days | One bounded worker; path, mount, network and resource checks |
| Independent checks and build artifacts | M4 | 2–3 days | Baseline/post-change behavior and honest inconclusive/failed outcomes |
| ARM64/StockFlow toolchain fit | M4 | 1–2 days | Representative job fits or a measured hosting constraint is recorded |
| Strategy/readiness assessment and coordination | M5 | 1–2 days | Decisions cite real current product evidence |
| Reports/presentations and export | M5 | 1–2 days | Sanitized readable artifacts built from verified records |
| Customer support case triage and drafts | M5 | 1–2 days | Customer permissions, cited facts, review and escalation |
| Owner dashboard/email notification ledger | M5 | 1–2 days | Meaningful deduplicated alerts, accepted/delivered/unknown distinction |
| Whole-cycle browser and operating acceptance | M5 | 2–3 days | Goal-to-receipt lineage; no fabricated completion |
| Audit, metrics and oversight promotion | M6 | 1–2 days | Reviewed evidence and explicit owner-approved policy delta |
| Backup/restore and crash/soak drills | M6 | 2–3 days | Independent destination and demonstrated recovery |
| Private Pi profile and cloud migration package | M6 | 2–3 days | One execution owner, bounded capacity and portable restore/runbook |

Finance/operations initially means costs, commitments and proposed actions. It does not include autonomous payments. Customer support initially produces drafts; customer sending is a separately governed capability. Existing voice/UI work may be reused, but a visual polish project is outside the critical path.

## Deferred features

The owner's earlier deferral still applies. Estimate only; no automatic activation:

| Candidate | Additional effort | Prerequisite |
| --- | --- | --- |
| Meta Harness: proposed changes, offline eval, review, version promotion and rollback | 8–15 days | Stable M6 and explicit request to activate improvement |
| Dedicated graph engine such as Graphiti | 4–8 days | Measured PostgreSQL retrieval limits and a justified ADR |
| Accretion adapter | 3–6 days | Owner chooses a specific benefit after the native builder pilot |
| SaaS/marketplace/external hiring/payment execution | Unestimated | New product/security/commercial requirements |

## First implementation slice

Implement the versioned contracts, validated plan graph, source/context schemas, deterministic action hashing, exact approval checks, fail-closed action transitions and persistent limit semantics. Add a dedicated PostgreSQL journal with exact owner approval and atomic cost holds if the local integration environment is available. Keep this path unmounted from the legacy API until its authentication/migration gates are proven.

Then complete the M0 executable fixture/evaluation inventory and move to the Pydantic AI/DBOS compatibility and real durable-worker gate. A pure policy test or standalone ledger is not the completed M1 runtime. Track actual completed behavior in [progress](PROGRESS.md), separately from the estimate.
