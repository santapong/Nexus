# Nexus architecture: C4 context, containers, and components

**Scope:** DravenIQ's supervised Company Brain and Action Harness, described
against the feature-branch source inspected on 29 October 2026. This is an
architecture guide, not proof that a complete deployed company is operating.
The [C4 model](https://c4model.com/) organizes a software system into context,
containers, components, and code. Here “container” means an application or data
store boundary; it does not necessarily mean a Docker container or a separately
deployed process. This document uses tables to explain the boundaries. See the
[architecture overview](ARCHITECTURE.md), [delivery board](../../TASKS.md), and
[current release gates](RELEASE_GATES_CURRENT.md) for the intended operating
cycle and up-to-date evidence.

The first release target is one **Nexus-owned** cycle: owner goal → evidence →
reviewed plan → authorized change → independent verification → departmental
outputs → owner report. The owner supervises decisions and effects. Delegated
and Board modes are later owner decisions; automatic Meta Harness improvement is
deferred. StockFlow is an optional later integration, not the release target.

## How to read status

- **Source:** code, contracts, configuration, or UI is present. It may require
  explicit composition, settings, or an independently launched worker.
- **Scoped evidence:** a stated scenario ran in the stated environment. Unit,
  isolated PostgreSQL, and SDK-mock tests do not prove live provider quality or
  the complete end-to-end product.
- **Target / unqualified:** required outcome or proposed deployment awaiting
  explicit integration, operating, or owner acceptance evidence.

The current feature checkpoint has scoped isolated PostgreSQL/DBOS planning,
coding and publication evidence using **two mock SDK requests**, with separate
accounting inspection. It is not a signed-in owner-operated company cycle. Live
provider usage, independent native builder on ARM64, same-goal departmental
outputs, external notification delivery, private deployment, restore, rollback,
and a 24-hour soak remain release gates. See the [board](../../TASKS.md) for
newer evidence rather than treating this guide as a live status monitor.

## 1. System context

| Person or external system | Relationship with Nexus | Boundary and status |
| --- | --- | --- |
| DravenIQ owner | Signs in, inspects evidence and reports, sets goals, reviews proposals, and approves or rejects governed work. | Owner UI/API source exists; signed-in acceptance of the complete journey remains open. |
| Company source repositories and documents | Provide registered source material for evidence and citations. | A Git reader accepts an operator-nominated commit, path, blob, size and hash; it does not fetch or interpret a public caller's path. Source use is scoped and access checked. |
| Model providers | Return structured model responses through allowed adapters after governance and budget admission. | OpenAI and Google adapter paths exist; integrated evidence uses mock transports. Real calls, actual billing and quality remain unqualified. |
| External notification provider | Can deliver an authorized owner notification when configured. | Resend transport source exists; actual owner delivery and reconciliation remain unqualified. |
| Operator and independent backup destination | Install, inspect, back up, restore and roll back the selected deployment. | Backup/restore components and a private Pi profile are source/planning evidence; deployment, recovery and soak require actual qualification. |

The Brain can describe company facts and relationships; it cannot grant a tool
or model permission. A departmental role can propose work but does not itself
possess authority to perform an external effect. A candidate artifact is not an
independent verification result. Relevant source: [Git reader](../../backend/nexus/company/brain/git_source.py),
[access contracts](../../backend/nexus/company/access.py), and
[action lifecycle](../../backend/nexus/harness/lifecycle.py).

## 2. Container view

The table describes logical runtime or persistence boundaries. The company API
and worker compositions may share packages, but their startup and authority are
separate; the table does not prescribe production process counts.

| Container / boundary | Responsibility and interfaces | Source / status |
| --- | --- | --- |
| Owner web application | React/TypeScript pages for knowledge, goals, plans, approvals, work, model checks and reports; calls the company API over HTTP. | [Company pages](../../frontend/src/pages/); source exists. A signed-in complete-cycle acceptance is pending. |
| Company API | Litestar routes, authenticated identity, optional Brain, management, planning, coding, report and notification services. | [Factory](../../backend/nexus/company_app.py) and [routes](../../backend/nexus/api/). Factory validates auth configuration and starts no Kafka consumer, legacy agent, provider client or durable worker. Optional controllers mount only when their services are supplied. |
| Management and Brain services | Company directory, source/evidence access, goals, charters, plans and owner-readable projections. | [Planning composition](../../backend/nexus/execution/planning_application.py) builds these services explicitly; [coding composition](../../backend/nexus/execution/coding_application.py) extends it. Composition is not worker launch. |
| Action harness and durable execution | Stores and validates proposals, authority, budgets, intent and receipts; schedules bounded action segments. | [Harness](../../backend/nexus/harness/) and [DBOS queue adapter](../../backend/nexus/execution/dbos_queue.py). Worker processes are explicitly configured and launched; queue identity is not authorization. |
| PostgreSQL company and DBOS data | Company directory, evidence, management, action and cost records; DBOS workflow data used by the selected queue integration. | [Company migrations](../../backend/company_alembic/env.py) use a separate `company_alembic_version` table. Deployed backup/restore is unqualified. |
| Protected source and artifact storage | Stores protected content and carries hashes, source versions and authorization into retrieval and generated outputs. | [Protected blob store](../../backend/nexus/company/brain/blob_store.py), [generated artifacts](../../backend/nexus/company/management/generated_artifact_store.py). Source exists; deployment storage and recovery remain gates. |
| Model adapter boundary | Resolves a governed request to a configured SDK transport and records observed usage/outcome. | [Adapters](../../backend/nexus/core/llm/company_adapters.py) and [model authorizer](../../backend/nexus/harness/model_authorizer.py). Real providers remain unqualified. |
| Native builder and independent verifier | Intended to create an isolated candidate and independently check its evidence. | [Nexus recipe](../../backend/nexus/builder/nexus_recipe.py) and [verification package](../../backend/nexus/verification/); selected image, toolchain closure, isolation, independent verification and ARM64 operation need qualification. |
| Notification delivery | Projects a private inbox and, when authorized/configured, sends an eligible message and records delivery state. | [Inbox routes](../../backend/nexus/api/company_notification_routes.py), [worker](../../backend/nexus/execution/notification_worker.py), [transport](../../backend/nexus/company/notifications/resend_transport.py). External delivery remains unqualified. |

Legacy Kafka, Redis and Taskiq packages and integrations exist in the repository.
They should not be inferred as running in the selected company API profile.
The company API factory explicitly excludes a legacy Kafka consumer; selected
DBOS workers need separate configuration and launch.

## 3. Components and technology

### Owner interface and API

| Component | Function | Concrete boundary |
| --- | --- | --- |
| Company pages and client hooks | Render knowledge, plans, review, work, cost and report state. | [Pages](../../frontend/src/pages/) and [hooks](../../frontend/src/hooks/). UI source is not signed-in acceptance. |
| Session and company identity | Verify signed bearer identity, then resolve current company-directory membership and capability. | [Authentication](../../backend/nexus/api/company_auth.py), [directory and access](../../backend/nexus/company/access.py). Role or company claims in a token do not replace current membership. |
| Management API and read models | Present goals, actions, approval context, budgets, metrics and work to an authorized owner. | [Management routes](../../backend/nexus/api/company_management_routes.py), [owner views](../../backend/nexus/company/management/owner_view_store.py), [cycle cost routes](../../backend/nexus/api/company_cycle_cost_routes.py). |
| Company API composition | Mounts only provided service families and fails closed on signer configuration. | [Factory](../../backend/nexus/company_app.py); mounting a route is not evidence that a worker was launched. |

### Company Brain and management

| Component | Function | Concrete boundary |
| --- | --- | --- |
| Source registration and ingestion | Registers source versions and protects material before it becomes searchable evidence. | [Source registry](../../backend/nexus/company/brain/source_registry.py), [ingestion store](../../backend/nexus/company/brain/ingestion_store.py), [Git source reader](../../backend/nexus/company/brain/git_source.py). |
| Ontology and evidence | Models entities, relationships and revisions with evidence references. | [Ontology models](../../backend/nexus/company/brain/ontology_models.py), [ontology store](../../backend/nexus/company/brain/ontology_store.py). Relationships and work dependencies are distinct; no dedicated graph database is claimed. |
| Retrieval and context | Finds explicit evidence, entity/relationship evidence, and PostgreSQL full-text candidates within access and result limits. Rechecks authorization before materializing content. | [Search](../../backend/nexus/company/brain/retrieval_search.py), [retriever](../../backend/nexus/company/brain/retrieval_store.py), [context](../../backend/nexus/company/brain/context_store.py). Thai tokenization and semantic search are not claimed by the initial full-text recipe. |
| Goals and plans | Represents goals, mandates, charters, plans, revisions and commitments; connects approved evidence to bounded work. | [Goal store](../../backend/nexus/company/management/goal_store.py), [governance](../../backend/nexus/company/management/governance.py), [plan store](../../backend/nexus/company/management/plan_store.py). A saved goal is not an approved plan. |
| Strategy and departmental outputs | Forms strategy, evidence-linked deliverables and operating report material for a goal. | [Strategy producer](../../backend/nexus/company/strategy/producer.py), [cycle artifacts](../../backend/nexus/company/cycle_artifacts/), [operating report](../../backend/nexus/company/management/operating_report_store.py). Same-goal complete departmental output remains unqualified. |

### Harness, scheduling and effects

| Component | Function | Concrete boundary |
| --- | --- | --- |
| Action journal and lifecycle | Records a specific action proposal, decision, state transition, authorization and resulting receipt. | [Journal](../../backend/nexus/harness/journal.py), [lifecycle](../../backend/nexus/harness/lifecycle.py), [approvals](../../backend/nexus/harness/approvals.py). |
| Company control, work limits and spend | Serializes relevant authority/budget decisions and keeps lifetime work allowances and daily reservation records. | [Company controls](../../backend/nexus/company/control_store.py), [budget](../../backend/nexus/harness/journal_budget.py), [reservations](../../backend/nexus/harness/journal_reservations.py). |
| Runtime and effect store | Binds registered work, segments and fenced ownership; records effect intent and outcome. | [Runtime store](../../backend/nexus/execution/runtime_store.py), [effect store](../../backend/nexus/execution/effect_store.py). A fence protects application writes; it cannot reverse or fence an external service that lacks a compatible mechanism. |
| Transactional enqueue | Checks an authorized action and its exact workflow/input binding, then uses PostgreSQL `dbos.enqueue_workflow` inside the caller's transaction. | [DBOS queue](../../backend/nexus/execution/dbos_queue.py). Existing queue IDs/deduplication do not grant permission or prove that an effect occurred. |
| Workers | Planning, coding, company action and notification workflows have explicitly configured worker entry points; the effect steps shown in these workers disable automatic step retries. | [Planning](../../backend/nexus/execution/planning_worker.py), [coding](../../backend/nexus/execution/coding_worker.py), [company](../../backend/nexus/execution/company_worker.py), [notification](../../backend/nexus/execution/notification_worker.py). |
| Model gateway and policy | Performs bounded, governed requests through selected transport adapters and records known or unknown usage. | [Registry](../../backend/nexus/core/llm/company_registry.py), [adapters](../../backend/nexus/core/llm/company_adapters.py), [authorizer](../../backend/nexus/harness/model_authorizer.py). Registry entries are not proof that a provider is qualified. |
| Builder and verifier | Binds a selected source, toolchain policy and image identity to a bounded build/check path and separate evidence. | [Builder recipe](../../backend/nexus/builder/nexus_recipe.py), [coding guard](../../backend/nexus/builder/coding_guard.py), [verification](../../backend/nexus/verification/). Full isolation and independence require execution evidence. |

### Selected dependency evidence

The project declares Python 3.12+, Litestar 2.24.0, SQLAlchemy 2.0.51,
Advanced Alchemy 0.34.0, Pydantic 2.13.4, Pydantic AI 2.54.0 and DBOS 3.2.0;
asyncpg, Alembic and pgvector use declared version ranges. See the actual
[backend manifest](../../backend/pyproject.toml) and [lockfile](../../backend/uv.lock)
for complete dependencies and resolved versions. The frontend manifest uses
React, React Router, TanStack Query, Vite and TypeScript; their resolved package
versions are recorded in the [frontend lockfile](../../frontend/package-lock.json).
Dependency presence is not service activation or provider qualification.

## 4. Dynamic flow: evidence to report

These steps describe the desired handoffs and the boundaries implemented in
source. They do not assert that every step has passed in one real operating run.

1. **Identity and knowledge.** The owner authenticates; Nexus checks current
   membership and capability. A selected source version supplies evidence whose
   provenance and permission are checked. The owner can select a citation and
   save a goal. The owner browser journey remains an acceptance gate.
2. **Planning.** Management constructs a bounded planning request from the goal,
   source/context and governance revisions. The planner may return a candidate;
   the owner reviews the actual plan before authorization. A proposal or model
   output is not approval.
3. **Approval and dispatch.** Nexus records an exact pending action and decision.
   Approved dispatch rechecks current authority and resources; the intended
   transaction consumes authority, binds source, holds cost and enqueues the
   durable segment. Waiting for approval does not require a worker to occupy a
   slot. See [approval journal](../../backend/nexus/harness/journal_authorization.py)
   and [queue adapter](../../backend/nexus/execution/dbos_queue.py).
4. **Effect boundary.** Before a model/tool effect, current membership, pause,
   authorization, revisions, lease, price and available allowance are rechecked
   as applicable. A durable effect intent precedes a one-time permit. A repeated
   or uncertain issued action must be reconciled rather than blindly retried.
   See [effect store](../../backend/nexus/execution/effect_store.py) and
   [model authorizer](../../backend/nexus/harness/model_authorizer.py).
5. **Build and verify.** The target builder consumes a nominated immutable source
   and produces a candidate under bounded isolation; an independent verifier
   assesses it against evidence. A successful local test or candidate does not
   prove the selected ARM64 builder or independent verification passed.
6. **Departmental outputs and owner report.** Accepted evidence and receipts
   feed strategy, presentation and support drafts, then an owner report and
   eligible notification. The complete same-goal chain and external delivery
   remain unqualified.

## 5. Budget, uncertainty and recovery

The selected policy is **US$5 per company day in Asia/Bangkok**, plus persistent
per-work and per-kind limits. [Budget accounting](../../backend/nexus/harness/journal_budget.py)
uses a Bangkok billing day; registered parent work partitions lifetime allowance.
A retry, new segment, or midnight does not create a fresh lifetime allowance.
An unissued reservation may be reassessed at the actual effect boundary; an
issued call with missing billing remains an unknown hold until reconciliation.
The [model authorizer](../../backend/nexus/harness/model_authorizer.py) records
actual server outcome before resolving billing; a missing outcome is not success.
Mock accounting exercises are useful evidence, but actual provider invoices and
live day-boundary behavior still require qualification.

Durable state and receipts support investigation and restart, but a DBOS
workflow result is not by itself business acceptance. Recovery must distinguish
an unissued action, a known receipt, an unknown external outcome and a verified
result. [Runtime recovery](../../backend/nexus/execution/runtime_recovery.py),
[approval recovery](../../backend/nexus/execution/runtime_approval_recovery.py),
[backup capture](../../backend/nexus/operations/backup_capture.py) and
[restore](../../backend/nexus/operations/backup_restore.py) are source
references, not evidence of a successful production restore or rollback.
Published legacy migration history must be preserved; fresh company installation
uses its separate company migration lineage, not an assumed legacy replay.

## 6. Proposed private operating profile

The selected target is a private Raspberry Pi ARM64 profile with an owner-facing
API/UI, PostgreSQL-backed company and DBOS state, protected artifacts, one
bounded native build runner, explicit access to qualified model/notification
providers and an independent encrypted backup destination. Rootless Podman is
the proposed sandbox mechanism, subject to actual runtime and cgroup
qualification. This is a deployment proposal, not a claim of a running Pi
service. Establish exact image/toolchain compatibility, hard limits,
cancellation, independent verification, backup/restore, rollback and 24-hour
soak before release. See [architecture deployment profile](ARCHITECTURE.md#pi-deployment-profile)
and [release gates](RELEASE_GATES_CURRENT.md).
