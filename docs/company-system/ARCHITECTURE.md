# Nexus company-system architecture

**Updated:** 2026-10-29. This document describes the selected architecture and
its intended boundaries. Diagrams are **target flows**, not evidence that every
connection has been exercised in one deployed system. The
[SDD](../sdd/NEXUS_SDD_v0.2.md) defines semantics; the owner-directed
[Nexus-focused delivery plan](NEXUS_FOCUSED_DELIVERY_PLAN_2026-10-16.md)
supersedes its earlier StockFlow-first scenario. The [task board](../../TASKS.md)
tracks current work and evidence; the [implementation plan](IMPLEMENTATION_PLAN.md)
defines the delivery gates.

Nexus is DravenIQ's internal **Company Brain and Action Harness**. The first
release is supervised: the owner sets direction, reviews proposed plans and
authorizes governed effects. The intended operating cycle uses Nexus's own
goal and evidence, proceeds through an approved plan, authorized change and
independent verification, and produces departmental outputs and an owner report.
StockFlow is an optional later integration test, not the first release target.
Delegated and Board modes require a separate owner decision after operating
evidence; automatic Meta Harness improvement is deferred.

## Current evidence and open boundaries

At the 29 October feature checkpoint, the repository contains the company Brain,
management, harness, model, planning, coding, strategy, reporting and notification
components. A fresh isolated PostgreSQL/DBOS integration exercised planning,
coding and publication with **two SDK mock requests** and a separate read-only
accounting audit. This is useful integration evidence, not proof of real provider
quality or a complete owner-operated cycle. The signed-in owner journey, live
provider qualification and usage, independent native builder/ARM64, same-goal
departmental outputs, notification delivery, deployment, restore, rollback and
24-hour soak remain release gates. Check the [task board](../../TASKS.md) for
newer results; test counts and coverage are tied to the particular source and
environment that produced them.

## The supervised operating cycle

The following is the intended first-release journey. An arrow describes a required
handoff, not a guarantee that the complete path has already passed acceptance.

```mermaid
flowchart LR
    Goal[Owner sets Nexus goal] --> Evidence[Find dated evidence and citations]
    Evidence --> Plan[Management proposes a bounded plan]
    Plan --> Approval[Owner reviews and approves]
    Approval --> Action[Harness authorizes a specific change]
    Action --> Build[Isolated builder produces candidate]
    Build --> Verify[Independent verifier checks candidate]
    Verify --> Outputs[Strategy, presentation and support drafts]
    Outputs --> Report[Owner report and governed notification]
    Report --> Goal
```

A saved goal is not an approved plan; an approved plan is not an executed action;
a candidate is not an independently verified result. Failures, blocked work and
unknown effects stay visible in the report.

## System boundaries

```mermaid
flowchart TB
    Owner[Owner]
    UI[Company dashboard]
    API[Authenticated company API]
    Manage[Management and departmental charters]
    Brain[Company Brain: entities, evidence, decisions]
    Harness[Action Harness: context, authority, limits, budget]
    Durable[DBOS execution segments]
    Models[Model gateway: registered providers]
    Tools[Governed tools and optional MCP adapters]
    Builder[Native isolated builder]
    Verify[Independent verification]
    Ledger[PostgreSQL: work, actions, approvals, receipts]
    Artifacts[Artifacts: hashes and permission-checked references]
    Report[Operating reports and notification ledger]
    Email[Owner email when configured and qualified]
    Sources[Repositories, documents and approved company sources]

    Owner --> UI --> API
    API --> Manage
    Sources --> Brain
    Manage <--> Brain
    Manage --> Harness
    Brain --> Harness
    Harness --> Durable
    Durable --> Models
    Durable --> Tools
    Durable --> Builder
    Tools --> Verify
    Builder --> Verify
    Verify --> Ledger
    Harness <--> Ledger
    Durable <--> Ledger
    Brain <--> Ledger
    Builder --> Artifacts
    Tools --> Artifacts
    Artifacts --> Verify
    Ledger --> Report
    Report --> UI
    Report --> Email
    Ledger --> Brain
```

The intended boundary sends consequential effects through the harness rather than
letting a departmental role or knowledge object authorize itself. PostgreSQL owns
durable business state; DBOS coordinates checkpointed execution segments.
Management, knowledge relationships and work dependencies have distinct
contracts. The target builder has no production write mount or ungoverned API
path; native isolation and recovery are still qualification gates.

## Engineering methods and roles

| Method | Nexus application | Boundary |
| --- | --- | --- |
| Loop engineering | Observe evidence, propose work, authorize, execute, verify and report; blocked or unknown outcomes remain explicit. | A loop is not evidence of autonomous completion. |
| Harness engineering | Enforce current identity, policy, approval, budget, ownership and receipt checks at action boundaries. | A model response, tool adapter or knowledge citation cannot grant authority. |
| Graph engineering | Model work dependencies and the relationships between goals, evidence, decisions and artifacts. | These are distinct contracts; a dedicated graph database is deferred. |
| Ontology engineering | Use typed company concepts and evidence references with explicit revisions and provenance. | Knowledge records describe the company; they do not confer execution authority. |
| Meta Harness | Consider evidence-based changes to the operating harness in a future phase. | Automatic self-improvement is deferred and is not a release capability. |

Management, strategy, engineering, presentation and support represent different
responsibilities over shared company evidence. Their presence as concepts or
components does not prove that all roles have produced accepted outputs for the
same goal. The focused plan specifies the first integrated demonstration.

## Action lifecycle

```mermaid
stateDiagram-v2
    [*] --> Proposed
    Proposed --> Validated: schema and policy checks
    Validated --> AwaitingApproval: explicit decision required
    Validated --> Authorized: standing authority
    AwaitingApproval --> Authorized: committed exact decision and recheck
    AwaitingApproval --> Rejected: owner rejects
    AwaitingApproval --> Expired: decision expires
    Authorized --> Executing: budget reserved and ownership fenced
    Executing --> Verifying: effect receipt recorded
    Executing --> OutcomeUnknown: effect cannot be confirmed
    Executing --> Failed: confirmed failure
    OutcomeUnknown --> Verifying: reconciliation confirms effect
    OutcomeUnknown --> Failed: reconciliation confirms failure
    Verifying --> Completed: acceptance passed
    Verifying --> Failed: acceptance rejected
    Verifying --> Verifying: inconclusive result recorded
    Proposed --> Cancelled: cancellation before execution
    Validated --> Cancelled: cancellation before execution
    AwaitingApproval --> Cancelled: cancellation before execution
    Authorized --> Cancelled: cancellation before effect
    Rejected --> [*]
    Expired --> [*]
    Failed --> [*]
    Completed --> [*]
    Cancelled --> [*]
```

`inconclusive` is a verification result: the action remains `verifying` until evidence resolves it or it is explicitly closed as failed with an inconclusive result. An unknown external effect is reconciled without blind retry. Already-issued effects cannot be undone by changing a task to cancelled.

## Approval without occupying a worker

```mermaid
sequenceDiagram
    actor Owner
    participant API as Company API
    participant DB as PostgreSQL ledger
    participant Scheduler as Authorized scheduler
    participant Queue as DBOS queue
    participant Worker as Execution worker
    participant Tool as Governed tool

    Worker->>DB: Commit exact proposal, hash and pending approval
    Worker-->>Queue: End segment and release worker slot
    Owner->>API: Approve action revision and hash
    API->>DB: Check owner, revision, expiry and policy
    API->>DB: Commit exact decision
    API-->>Owner: Decision recorded; work not yet scheduled
    Scheduler->>DB: Recheck and atomically consume authority, bind source, hold cost and enqueue
    DB-->>Queue: Continuation becomes eligible
    Queue->>Worker: Resume same logical work item in new segment
    Worker->>DB: Recheck resource, authority, budget and ownership
    Worker->>DB: Persist effect intent and issue one-time permit
    Worker->>Tool: Exact authorized payload with action identity
    Tool-->>Worker: Result or uncertain outcome
    Worker->>DB: Record receipt, verification status and cost reconciliation
    DB-->>API: Durable event available
    API-->>Owner: Outcome with evidence or reconciliation needed
```

This is the target protocol; implementations may separate approval and dispatch
requests while keeping the dispatch's authority consumption, source binding,
reservation and enqueue in one transaction. A short-lived API transaction does
not wait for model execution. Approval does not bypass a later resource or policy
conflict. Parent work permanently partitions lifetime allowances; retries, new
segments and a new Bangkok day do not reset them. The selected company-day model
limit is US$5 in Asia/Bangkok. Issued calls with unknown usage keep their holds
until reconciliation. A fence protects application writes; it cannot undo or
fence an external effect that does not support fencing. Actual provider billing
and live day-boundary behavior remain to be qualified.

## Pi deployment profile

```mermaid
flowchart LR
    Owner[Owner browser]
    Tailnet[Private authenticated route]
    Providers[Allowed model and email providers]
    Backup[Independent encrypted backup destination]

    subgraph Pi[Pi 5 ARM64: proposed Nexus profile]
        API[API and UI]
        Worker[Management and DBOS worker]
        PG[Dedicated PostgreSQL and pgvector]
        Files[Artifacts and source snapshots]
        Runner[Restricted build runner]
        Sandbox[One rootless Podman sandbox]
        API --> PG
        Worker --> PG
        API --> Files
        Worker --> Runner
        Runner --> Sandbox
        Sandbox --> Files
    end

    Owner --> Tailnet --> API
    Worker --> Providers
    PG --> Backup
    Files --> Backup
```

This is a proposed private deployment, not a claim that Nexus is deployed or
that the sandbox limits are enforced. Model credentials are intended to stay
with the gateway; database credentials stay outside builder jobs. Core processes
target at most 3 GiB combined; the single builder defaults to 2 CPUs and 4 GiB
with explicit disk and time limits. ARM64 toolchain, actual enforcement,
cancellation/recovery, independent backup and restore, rollback, and the 24-hour
soak require separate evidence. Existing Pi services remain separate. The
inspected storage path was root-backed, so an independent backup destination
still needs configuration.
