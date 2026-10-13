# Nexus company-system architecture

**Date:** 2026-10-05. **Status:** proposed target, documentation only.\
The [SDD](../sdd/NEXUS_SDD_v0.2.md) defines semantics; this document explains boundaries. The [implementation plan](IMPLEMENTATION_PLAN.md) owns delivery gates.

## System boundaries

```mermaid
flowchart TB
    Owner[Owner and board]
    UI[Co and company dashboard]
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
    Email[Configured owner email]
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

All consequential operations pass the harness. PostgreSQL owns durable business state; DBOS owns checkpointed execution. Management, knowledge relationships and work dependencies have distinct contracts. The builder has no production write mount or ungoverned API path.

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
    participant Queue as DBOS queue
    participant Worker as Execution worker
    participant Tool as Governed tool

    Worker->>DB: Commit exact proposal, hash and pending approval
    Worker-->>Queue: End segment and release worker slot
    Owner->>API: Approve action revision and hash
    API->>DB: Check owner, revision, expiry and policy
    API->>DB: Commit decision and enqueue continuation atomically
    DB-->>Queue: Continuation becomes eligible
    Queue->>Worker: Resume same logical work item in new segment
    Worker->>DB: Recheck resource, authority, budget and ownership
    Worker->>DB: Consume decision and record execution intent
    Worker->>Tool: Exact payload with action ID and idempotency key
    Tool-->>Worker: Result or uncertain outcome
    Worker->>DB: Record receipt, verification status and cost reconciliation
    DB-->>API: Durable event available
    API-->>Owner: Outcome with evidence or reconciliation needed
```

The short-lived API transaction never waits for model execution. Approval itself does not bypass a later resource or policy conflict. The same counters and budget lineage survive both segments.

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

Podman installation and this profile are future deployment work. Model credentials stay with the gateway; database credentials stay outside builder jobs. Core processes target at most 3 GiB combined; the single builder defaults to 2 CPUs and 4 GiB with explicit disk and time limits. Existing Pi services remain separate. The inspected storage path was root-backed, so an independent backup destination still needs configuration.
