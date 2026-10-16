# Nexus SDD v0.2 — DravenIQ Autonomous Company System

**Owner scope amendment, 2026-10-16:** [Nexus-focused delivery](../company-system/NEXUS_FOCUSED_DELIVERY_PLAN_2026-10-16.md)
is the current implementation sequence. Nexus is the sole product deliverable;
its own repository/evidence supplies the first operating cycle. StockFlow-specific
examples below are historical optional integration scenarios. All Brain,
management, strategy, builder/verification, presentation/support, notification,
budget, authority and operations requirements remain. Existing failed/frozen
evaluations are preserved; changing the reference project does not qualify them.

**Document date:** 2026-10-05 (Asia/Bangkok)\
**Status:** proposed system design; product direction and operating constraints confirmed by the owner.\
**Baseline:** GitHub `santapong/Nexus`, `main` at `6a8c8ef15e522aaa563d53776aef8dedc3209fcf` (2026-07-13).\
**Scope of this delivery:** documentation. No runtime, schema, dependency, service, or external account changes.\
**Version meaning:** `v0.2` is this SDD's revision, not a package or production release.

Companion documents: [implementation plan](../company-system/IMPLEMENTATION_PLAN.md), [architecture diagrams](../company-system/ARCHITECTURE.md), [ADRs 094–099](../DECISIONS.md#adr-094--draveniq-company-system-as-the-first-product), and [backlog](../BACKLOG.md#company-system-program-2026-10-05).

## 1. Purpose and product direction

Nexus will operate DravenIQ's internal work as a coordinated company: understand goals, maintain company knowledge, plan work across departments, execute authorized actions, verify results, keep commitments, and report to the owner. The owner begins as an active supervisor and may later act as a board member reviewing decisions, exceptions, performance, and changes in authority.

The product combines a **Company Brain** with an **Action Harness**. The Brain stores what the company knows and why it believes it. Management chooses work under an owner mandate. The harness governs how work becomes actions and verified outcomes. Co is the owner's conversational entry point into this system.

Success means a real operating cycle with receipts and measurable progress. An animated collection of agents, a plausible answer, generated code, or a completed model call is insufficient evidence of company operation.

### 1.1 Confirmed choices and design defaults

| Item | Owner-confirmed constraint |
| --- | --- |
| First audience | DravenIQ's internal company |
| First end-to-end workflow | StockFlow customer readiness |
| Engineering execution | Native builder inside Nexus |
| Models | Multiple providers |
| Hosting | Raspberry Pi first; cloud/VPS migration later |
| Notifications | Dashboard and email |
| First authority scope | Internal work and drafts |
| Build capacity | One bounded Pi worker |
| Initial model budget | US$5/day |
| Self-improvement | Defer automatic self-improvement |
| Oversight trajectory | Closely supervised first; periodic board review later |

The framework pins, quotas below the daily cap, schedules, alert limits, evaluation thresholds, and resource limits below are proposed defaults. They become versioned configuration after implementation validation. No design document independently grants permission to deploy, publish, message customers, purchase, or change credentials.

### 1.2 Initial scope

The first product supports company mandates, departmental charters, goals, work plans, evidence-backed knowledge, internal research and artifacts, isolated engineering, independent verification, approvals, cost controls, audit history, and owner reporting.

Defer multi-tenant SaaS commercialization, paid agent hiring, external agent marketplaces, automated financial transactions, public federation, autonomous prompt promotion, and model fine-tuning. Accretion may become a reviewed adapter later; it is not the first builder dependency.

## 2. Company organization and authority

A department is a charter with responsibilities, tools, limits, deliverables, and escalation rules. It need not be a separate continuously running agent. A small pool of workers serves multiple roles; idle departments consume no model tokens.

| Department or role | Responsibility | Typical verified deliverable |
| --- | --- | --- |
| Owner / board | Mandate, priorities, authority, material decisions | Signed mandate, approved exception, review record |
| Management / Co | Coordinate plans, track commitments, handle exceptions | Work plan, operating report, owner decision request |
| Strategy and direction | Compare evidence, choose proposed priorities | Decision memo with alternatives, assumptions, metrics |
| Builder / engineering | Implement bounded changes in isolated workspaces | Patch, commands and exit codes, tests, reproducible artifact |
| Verification / quality | Check acceptance independently of the author | Pass, reject, or inconclusive result with evidence |
| Presentation / communications | Turn verified facts into useful artifacts | Sanitized report, customer draft, presentation |
| Customer support | Triage cases, retrieve product facts, draft responses | Case record, cited response draft, escalation |
| Operations / finance | Monitor commitments, service facts, costs, risks | Budget ledger, exception report, proposed remediation |

Management can assign tasks and recommend priority changes within the mandate. A builder cannot expand its authority by creating a child task. Verification checks outcomes; it cannot waive policy. Finance in V1 tracks and recommends; it cannot move money.

### 2.1 Oversight modes

| Mode | Permitted operation | Owner involvement |
| --- | --- | --- |
| Supervised | Execute authorized internal work; draft external actions | Review plans, proposed external actions, exceptions, and results |
| Delegated | Run explicitly allowed recurring procedures within limits | Review meaningful decisions and exceptions; inspect periodic reports |
| Board oversight | Operate approved departmental mandates with established evidence | Audit company outcomes, risks, budgets, and authority changes |

Mode is a policy version approved by the owner, not a model's confidence estimate. Promotion is never automatic. The initial internal scope permits research, internal coordination, temporary isolated changes and tests, and drafts. Customer communications, Git pushes, production changes, publishing, credentials, and spending beyond approved model use require their appropriate explicit authorization.

Owner notifications are a separate action category: they may use a configured allowlisted owner address after notification setup is approved. They do not authorize sending to customers or arbitrary recipients.

## 3. First operating cycle: StockFlow customer readiness

The cycle begins with an owner-approved readiness goal, a nominated committed StockFlow source revision, and a checklist for a design-partner demonstration. Existing uncommitted StockFlow work is excluded unless the owner deliberately supplies a snapshot for this cycle.

1. Strategy gathers current product evidence and identifies readiness gaps. Historical release notes are context, not proof of current deployment.
2. Management proposes a bounded plan: readiness assessment, one selected engineering improvement, verification, demo material, customer-support draft, and an owner report.
3. The native builder works from the nominated revision in an isolated workspace, makes the authorized change, and captures commands, logs, and artifacts.
4. Verification checks the changed behavior and the readiness checklist. Existing failures are reported separately; a failing baseline never becomes a passing release claim.
5. Presentation prepares a demo/readiness report. Support prepares a response or FAQ draft from approved product facts.
6. Management reconciles deliverables, unresolved gaps, costs, and decisions, then updates the dashboard and notifies the owner when configured.

**Pilot completion:** one traceable cycle contains the goal, approved plan, cited evidence, isolated change, independent verification, presentation, support draft, action receipts, budget ledger, and owner report. If access, hardware capacity, verification, or authorization prevents progress, the cycle finishes as blocked or inconclusive with the specific dependency. External delivery and production release remain separate decisions.

## 4. Baseline assessment and validation limits

The existing project already describes an AI company, with CEO/Director/Engineer/Analyst/Writer/QA agents, Kafka, Pydantic AI, PostgreSQL, Redis, tools, and A2A. July design documents propose harness modernization and Co. Merged code includes Co, uploads, parsing, attachments, and UI work even where prose still says design-only.

The 2026-10-04 review of the baseline passed **225 locked-environment unit tests**, Ruff, and CI-style mypy across 204 source files. These are unit/static results. No live PostgreSQL/Kafka/Temporal integration, paid model run, external write, or browser operating-cycle acceptance was established by that review.

| Finding | Evidence level | Design consequence |
| --- | --- | --- |
| Production context binding has no caller; an irreversible file tool raises `ToolContextUnsetError` without writing | Source plus bounded actual-function probe | Context binding must be a required harness boundary |
| Approval polling occurs before the adapter's commit | Source plus mocked transaction probe; cross-session invisibility is an inference | Commit pending approval before ending a segment; test with two real DB sessions |
| `AgentTaskWorkflow` lacks Temporal workflow metadata and the installed SDK rejects it | Actual SDK validation | Existing Temporal code is not a proven durable runtime |
| Engineer prompt includes attachments but drops workspace files; semantic memory is outside normal assembly | Actual prompt assembly plus source | One tested, permission-aware ContextBundle |
| Kafka auto-commit and early Redis seen markers can outlive unfinished execution | Source-level crash scenario | Durable task state, enqueue consistency, fenced ownership, recovery tests |
| Optional Temporal QA defaults to approval on timeout/exception | Source-level finding | Verification failures and uncertainty cannot approve actions |
| Workspace write tool directly commits without the documented approval call | Source-level finding | Every mutation entry point must use the same policy gate |
| Email is not configured in the current adapter | Source; raises `ToolNotConfigured` | Implement explicit provider setup and honest delivery status |

Raw review artifacts live outside the repository at `/mnt/data/nexus-review-2026-10-04/`; retain their commit and date when citing results. [ERROR-038](../ERRORLOG.md#error-038--company-runtime-integration-gaps-at-july-head) tracks open remediation. Existing RLS transaction injection is present in the July code; this design must preserve it rather than repeat an obsolete missing-hook claim.

## 5. Target architecture

Use a modular Python system with three deployed processes: API, management/execution worker, and isolated build runner. The runtime shares a dedicated PostgreSQL database and typed contracts. The runner uses a narrow authenticated job protocol and cannot bypass the harness.

| Layer | Owns | Boundary |
| --- | --- | --- |
| Owner experience | Co, dashboard, approvals, reports | Authenticated API; durable event cursor |
| Company Brain | Entities, claims, evidence, decisions, commitments | Permission-aware queries and versioned records |
| Management | Goal decomposition, dependencies, eligibility, exceptions | Validated plans under a mandate |
| Action Harness | Context, budgets, tools, approval, limits, receipts | Only entry point for consequential execution |
| Durable execution | Checkpointed segments, queues, recovery, timers | DBOS; one execution owner per work item |
| Native builder | Repository snapshot, bounded commands, artifacts | Rootless sandbox with explicit resource and network policy |
| Verification | Acceptance results and evidence | Distinct verifier identity and no self-approval shortcut |
| Model gateway | Allowed providers, routing, usage reservations | Registered model IDs, price and capability checks |
| Tool gateway | Local functions, provider APIs, optional MCP adapters | Typed tools behind identical policy checks |
| Reporting | Operating facts, notifications, audit exports | Receipts and verified outcomes; no invented delivery status |

Brain state and work state are separate concepts in the same database. A knowledge relationship is not a scheduling dependency. The dependency graph is a validated DAG; bounded rework creates explicit attempts without turning the dependency graph into an uncontrolled cycle.

## 6. Tools and framework decisions

| Component | Proposed implementation | Reason and adoption gate |
| --- | --- | --- |
| Language | Python 3.12 | Preserve backend investment; ARM64 smoke test |
| API | Litestar 2.24.0 | Preserve current baseline; test auth, DB sessions, streaming |
| ORM and migrations | SQLAlchemy 2.0.51, Advanced Alchemy 0.34.0, Alembic | Existing patterns; additive schema migration and rollback/restore validation |
| Agent runtime | `pydantic-ai-slim[openai,google,dbos]==2.54.0` | Typed agents and DBOS integration; migrate from locked 1.107.1 through M1 tests |
| Durable execution | DBOS 3.2.0 | PostgreSQL-backed execution; test recovery, versions, and enqueue semantics |
| System of record | Dedicated PostgreSQL 16 with pgvector | Company state, action ledger, full-text and vector retrieval |
| Graph representation | Typed entity and relationship tables | Ontology and temporal claims without an additional graph database |
| UI | Existing React + Vite + TypeScript, TanStack Query, Zustand | Preserve working shell; role/goal UI first, React Flow as inspection view |
| Model adapters | OpenAI, Google, evaluated compatible endpoints | Provider choice separated from business workflow |
| Builder | Plain Git, rootless Podman, bounded command runner | Native Nexus execution on Pi; validate isolation and ARM64 toolchains |
| Browser verification | Playwright where the approved task requires it | Behavior evidence; ARM64 installation and resource checks |
| Artifacts | Markdown, sanitized HTML; optional python-pptx export | Reviewable reports and presentations; validate generated output |
| Ingestion | Reuse existing document parsers | Normalize once; provenance, quotas, timeout and malformed-file tests |
| Notifications | Resend API for owner email plus durable dashboard records | Explicit setup; persistent Nexus deduplication and delivery reconciliation |
| Observability | OpenTelemetry and structlog | One company/work/action correlation chain; existing monitoring optional |
| Deployment | Private Pi profile first, portable containers later | Dedicated DB, authenticated tailnet access, independent backup |

The Pydantic AI 2.54.0 / DBOS 3.2.0 combination resolved with the baseline API/ORM pins in an ARM64-targeted dependency dry run on 2026-10-05. This establishes dependency resolution only. Neither the upgrade nor a working ARM64 runtime has been installed or verified. Pin exact versions in the eventual lockfile only after the M1 compatibility spike; recheck releases before changing the pins.

Pydantic AI's DBOS integration attaches durability capabilities before DBOS launch and runs the agent inside a DBOS workflow. Custom tool I/O still needs explicit durable step boundaries; framework integration does not supply application authorization or external idempotency. See [Pydantic AI DBOS integration](https://pydantic.dev/docs/ai/capabilities/durable_execution/dbos/), [migration guide](https://pydantic.dev/docs/ai/overview/migration/), and the proposed package versions on [PyPI Pydantic AI](https://pypi.org/project/pydantic-ai/2.54.0/) and [PyPI DBOS](https://pypi.org/project/dbos/3.2.0/).

The new Pi profile has one durable execution engine. Kafka, Redis, Taskiq, and Temporal remain legacy paths during migration; retire them from the new profile only after data mapping, ownership, and recovery gates pass. Do not run two schedulers or two engines against the same company work item. A future need for another transport must have measured requirements and a new ADR.

## 7. Ontology and Company Brain

### 7.1 Minimum domain model

| Type | Meaning | Important relationships |
| --- | --- | --- |
| Company | DravenIQ boundary and operating policy | Has departments, mandates, budgets |
| Principal | Owner, service, role assignment | Belongs to company; holds scoped authority |
| Department | Charter and responsibility | Owns goals and work; cannot mint permissions |
| Product / Project | Business offering and bounded initiative | Supports goals; references source artifacts |
| Goal | Desired measurable outcome | Has parent goal, metric, owner, due date |
| WorkItem | Executable unit with acceptance criteria | Belongs to plan; depends on other work |
| Customer / SupportCase | Customer identity and reported need | Access restrictions; references product and evidence |
| Decision | Choice with rationale and alternatives | Made under mandate; cites evidence |
| Commitment | Promised outcome, recipient and deadline | Tracks obligation independently of work status |
| Evidence | Source observation and provenance | Supports or challenges a claim |
| Artifact | Addressable output and content hash | Produced by action; assessed by verification |
| Action / Verification | Consequential operation and its check | Connects actor, inputs, receipts and acceptance |
| Budget / AuthorityPolicy | Quantitative and permission limits | Versioned scope for company, role and work |

Every record carries company ID, stable ID, revision, timestamps, and access scope. Foreign keys and company-scoped uniqueness enforce relationships. Apply existing RLS mechanisms and explicit resource checks; do not assume a nullable legacy workspace ID proves company ownership. Relationships support typed traversal and effective dates. A new graph engine is optional future work driven by measured query limits.

### 7.2 Facts, uncertainty and provenance

Store claims as `observation`, `decision`, `hypothesis`, `plan`, `commitment`, or `verified_outcome`. Each claim includes source reference/hash, source event date, ingestion time, valid interval where meaningful, author, access rules, and supporting/conflicting evidence IDs. Keep superseded claims with explicit replacement links. Conflicting sources remain visible until a justified resolution is recorded.

Model extraction proposes claims; it does not turn text into verified truth. Authoritative customer/product state stays in its source system. Cached Nexus facts record freshness and must be refreshed before actions depend on volatile state. A plan is not a completed action; an artifact is not a deployment; provider acceptance of email is not delivery.

Ingestion stores immutable source artifacts, deterministic parsed content, document/chunk lineage, and extraction versions. Bound file size, parse time, content size, and embedding cost. Retrieval combines company-scoped SQL, full-text search, vector retrieval, and typed relationships. Enforce permission filtering before retrieval and again when materializing context or artifacts.

## 8. Context engineering

One ContextAssembler serves all roles. It emits a typed `ContextBundle` containing mandate and goal ancestry, relevant charter, work and attempt IDs, acceptance criteria, policy and budget versions, retrieved claims with dates and citations, prior verifier feedback, attachments, selected workspace files, and artifact references.

Context uses a configured token allocation: mandatory policy/work instructions first, acceptance and recent feedback next, relevant evidence thereafter. Large artifacts remain addressable and tools read bounded sections. Record what was included, omitted, summarized, or stale. Do not silently drop workspace material or give one department a separate uncatalogued memory path.

Retrieved documents, tool responses, and repository content are untrusted data. They cannot issue authority, change budgets, replace the mandate, or grant tools. Preserve provenance through summaries and prohibit cross-company or unauthorized customer facts. Refresh affected source revisions before consequential execution; a stale precondition returns a conflict for review or replanning.

## 9. Harness engineering and durable execution

Every worker follows **receive → validate → assemble context → reserve budget → reason → authorize → execute → verify → record outcome**. An action may need several durable segments, but its logical work item, attempt counters, authority, and budget lineage remain stable.

### 9.1 Contracts

All public/domain boundaries use Pydantic schemas with an explicit schema version. The minimum contracts are:

| Contract | Required information |
| --- | --- |
| CompanyMandate | Company, owner, goals, priorities, allowed scope, budget, escalation, revision |
| DepartmentCharter | Responsibilities, permitted tools, deliverables, limits, verifier, version |
| WorkPlan | Goal, DAG of work items, acceptance, quotas, dependencies, revision |
| ContextBundle | Source identities, revisions, permissions, policy, budget and inclusion manifest |
| ActionProposal | Actor, exact resource and parameters, preconditions, policy/cost versions, immutable hash |
| ApprovalDecision | Approver, action revision/hash, decision, scope, expiry, single-use identity |
| ActionReceipt | Action/attempt IDs, external ID where present, input/output hashes, timestamps, artifacts, outcome |
| VerificationResult | Verifier, criterion IDs, pass/reject/inconclusive, evidence, limitations |
| OperatingReport | Goal/commitment progress, customer impact, costs, blockers, owner decisions, receipt links |

Canonical action hashing includes company, actor, tool version, resource, normalized parameters, source preconditions and policy/cost versions. A deterministic versioned canonicalization function owns normalization. Editing any bound value creates a new proposal and invalidates the old approval.

Persist JSON contracts and artifact references for application interchange. DBOS may use its native serialization internally in its trusted system database. Do not expose native serialized objects to external APIs or load them from untrusted sources. Resolve model clients, sessions and service objects inside steps from registered identifiers; they are not checkpoint payloads.

### 9.2 Action lifecycle and approval

An action moves through `proposed`, `validated`, `awaiting_approval` when needed, `authorized`, `executing`, `verifying`, and `completed`. Alternatives are `rejected`, `cancelled`, `expired`, `failed`, or `outcome_unknown`. Terminal outcome and verification result are separate: an external operation can have succeeded while its intended business outcome remains unverified.

Before requesting approval, commit the exact proposal and its pending decision record. End the execution segment and release the worker slot and sandbox. Dashboard approval records a decision in another committed transaction and enqueues a continuation. Re-entry uses the same logical work item but a new segment, checks hash/revision/expiry, current permissions, resource state, and budget, then atomically consumes the approval at the effect boundary.

Default approval expiry is 24 hours. A changed resource, revoked mandate, edited payload, expired decision or price version change cannot silently reuse it. Routine internal actions can execute under explicit standing authority from the plan and charter; the policy check still runs. Approval grants one exact action, not arbitrary later actions or altered recipients.

### 9.3 Transactions, replay and uncertainty

Persist work state and enqueue its DBOS continuation atomically in the same PostgreSQL database using supported transactional enqueue. Fence action ownership with a monotonically increasing lease generation; stale workers cannot record a successful state transition. A unique logical action key prevents duplicate scheduling from becoming duplicate authorization. The receiver validates the same ownership token for local mutations.

Durable checkpoints avoid redoing recorded steps; external effects still require receiver idempotency keys or reconciliation. A crash after an external effect but before its receipt may produce `outcome_unknown`. Query the provider using its durable external reference; do not blindly repeat an uncertain non-idempotent action. A local fence cannot stop an external API that has no fencing interface.

Use one configured retry owner for each operation. Account for transport, SDK, model, workflow and rework attempts; avoid multiplying their defaults. Terminal permission/schema/configuration failures stop immediately. Unknown billable requests retain reservations until reconciled. Shutdown and cancellation stop new work and track any already-issued effect to a resolved or uncertain outcome.

DBOS queue limits do not replace persistent application deduplication. Approval waiting must not hold the only builder or execution queue slot. Model definitions/capabilities are registered before launch with stable IDs; workflow versions drain or retain compatible workers during an upgrade. Test replay across a real process kill and a real upgrade. See [DBOS queues](https://docs.dbos.dev/python/tutorials/queue-tutorial), [transactional outbox](https://docs.dbos.dev/python/examples/outbox), and [workflow upgrades](https://docs.dbos.dev/python/tutorials/upgrading-workflows).

### 9.4 Owner controls and fail-closed operation

The owner can pause company intake, revoke a mandate, cancel a work item, or stop the builder through authenticated audited controls. A persisted company pause blocks new model reservations and action authorization, including after worker restart. Workers recheck pause/revocation at each consequential boundary; cancellation requests terminate bounded sandbox jobs. Already-issued external requests still require reconciliation, so the UI reports pending/unknown effects rather than claiming an instant undo.

Work status is distinct from action status. Work can be pending, eligible, running, awaiting approval, blocked, paused for budget, completed, failed or cancelled. Changing status cannot erase receipts, reset limits, release an unknown billing hold, or make rejected verification pass. Resume requires current policy and an audited owner decision where scope changed.

## 10. Loop engineering and graph engineering

Loop engineering means explicit continuation criteria and stopping conditions. Each logical work item has default limits of **12 model requests, 20 tool attempts, 2 rework rounds, and 2 plan revisions**. Failed calls count. Resuming after approval or crash does not reset limits. Child tasks receive reserved slices of the parent budget; splitting tasks cannot evade the company cap or grow work without bounds.

Known procedures use deterministic workflows with model calls only where reasoning is required. Open research uses bounded reasoning/tool steps and terminates on acceptance, a limit, repeated identical failure, missing authority, unavailable resources, or unresolved uncertainty. Semantic similarity can help diagnose stagnation; it cannot be the only stopping or success criterion.

Management validates the dependency DAG, goal ancestry, assigned roles, tool eligibility, quotas, and acceptance before scheduling. It evaluates eligibility on events and inexpensive due-time checks. A proposed default is a one-minute due check and a fifteen-minute management opportunity when eligible work exists. Idle checks use zero model calls.

Record concise decisions, assumptions, selected actions, tool outcomes and verification evidence. Do not require hidden chain-of-thought as an audit artifact. Explain why a business decision was made using visible evidence and alternatives.

## 11. Model methods, routing and cost control

Use structured tool-using agents, deterministic workflow composition, targeted retrieval, plan/dependency decomposition, and independent verification. Multi-agent work is justified by distinct responsibilities or independent checks, not by creating many personas to discuss every task. A verifier must check external evidence and acceptance criteria; another model's agreement alone is insufficient.

These methods operate at different layers of the same system:

| Method | Nexus implementation | First proof |
| --- | --- | --- |
| Ontology engineering | Typed company objects, relationships, domain rules and claim types | M2 company evidence pack |
| Graph engineering | Knowledge relationships and validated work dependencies | M2 retrieval plus M3 plan validation |
| Context engineering | One permission-aware ContextBundle with source revisions and inclusion manifest | M2 actual prompt/context tests |
| Harness engineering | Governed action boundary, exact approval, cost, tool execution and receipts | M1 real approval/recovery tests |
| Loop engineering | Durable counters, explicit continuation, bounded rework and deterministic idle checks | M1 limits plus M3 operating procedure |
| Evaluation engineering | Frozen scenarios, independent verification and evidence manifests | M0 fixtures through M5 cycle acceptance |
| Memory engineering | Source-backed claims, validity, conflict and supersession instead of uncategorized recall | M2 changed-source and contradiction tests |
| Meta Harness | Future proposal/evaluation/review/promotion/rollback around harness versions | Deferred; no V1 automatic improvement |

### 11.1 Profiles and routing

| Profile | Use | Required capabilities |
| --- | --- | --- |
| Reasoning | Strategy and difficult planning | Structured output, evaluated planning quality |
| Engineering | Bounded implementation and diagnosis | Tool use, code/context capability, schema adherence |
| Routine | Classification, summaries, drafts | Appropriate language/output quality at low estimated cost |
| Verification | Evidence checks and acceptance reasoning | Independent checks and uncertainty handling |
| Embeddings | Retrieval index | Explicit vector dimension, price and reindex version |

A registry records provider/model IDs, adapter/API family, context/output limits, capabilities, price with date/version, allowed data classification, evaluation results, health and fallback priority. Seed OpenAI and Google adapters plus explicitly evaluated compatible endpoints. Preserve legacy adapters only behind the same registry and gates. Do not auto-enable newly released models.

Routing filters by policy, capabilities, evaluation threshold, health, and available reservation, then chooses the lowest estimated eligible cost with a stable configured priority for ties. Permit at most two registered fallback alternatives under the same work-item reservation and counters. A fallback cannot silently relax data policy, tool capability, output criteria, or the remaining budget. Record actual model selection and why it was eligible.

Pydantic AI's 2.x migration changes model names/API prefixes and capability hooks. Explicitly configure API family instead of assuming a historical `openai` prefix retains old behavior. Conformance tests cover structured outputs, tools, cancellation, usage, errors and fallback. See [migration guidance](https://pydantic.dev/docs/ai/overview/migration/) and [hooks](https://pydantic.dev/docs/ai/core-concepts/hooks/).

### 11.2 Budget ledger

The company cap is **US$5 per Asia/Bangkok calendar day**. Proposed default work-item cap is US$1; a plan can allocate smaller slices. Before each call, reserve an upper-bound estimate from known input size, configured output limit and dated pricing. Use atomic PostgreSQL reservations so concurrent workers cannot spend the same remaining allowance. Include embeddings, failed/billable requests, fallback, and rework.

Reconcile reported provider usage against the reservation. Keep a hold for unknown billing; a timeout does not refund an unconfirmed charge. Models with unknown or unsupported cost semantics cannot enter paid autonomous routing. Define treatment of cached/reasoning/multimodal tokens for each supported model. Do not claim that local estimated limits are identical to a provider's final bill.

Jobs crossing midnight reserve calls against the new day's ledger without resetting their logical task limits. Alert on budget stop and show spent, held, and available amounts separately. Spend stops produce an explicit paused-for-budget work state until a new authorized allocation/day is available; they do not create a new task to bypass the limit.

## 12. Native builder and tool harness

The Pi builder is part of Nexus. A dedicated runner receives an immutable job specification: approved repository/revision, allowed path and command policy, artifact outputs, timeout, resource limits, network permissions, and task/ownership IDs. It returns a manifest with commands, exit codes, source hash, diff, logs, outputs and limitations.

Use one rootless Podman worker, initially limited to **2 CPUs and 4 GiB RAM**, with explicit disk/output quotas and a per-job timeout. Reject jobs whose requirements exceed this envelope. Heavy research training and cross-company arbitrary commands are outside this pilot. Rootless containers reduce privilege; they are not a proof of a hardened hostile multi-tenant sandbox.

Mount only the job workspace and required read-only caches. The runner has no production repository write mount, owner home directory, credential store, database credential, model credential, or unrestricted engine socket. The API cannot submit arbitrary engine commands. Validate paths and symlinks before reads/writes, pin allowed tools/images and bind the job to policy. Runtime network is denied by default; an explicit install phase can use constrained access to approved dependency registries.

Create an isolated Git workspace from the approved committed source and keep the exact patch as an artifact. Use plain Git; do not depend on the `gh` CLI. Nexus may prepare a branch/diff and review package. GitHub-only PR creation in the first workflow uses a review URL/manual browser step until an authenticated, explicitly authorized connector is designed.

Capture baseline checks before changing code and relevant checks after. A verifier receives the patch and acceptance criteria independently. Failed checks, missing test dependencies, ARM64 incompatibility and resource limits remain visible. Publishing, pushing and deploying are distinct governed actions. No worker can declare its own changed code verified merely by producing it.

MCP is an optional integration protocol, not an authority system. Every MCP, built-in, plugin and runner entry point passes the same company/tool/resource policy, schema and receipt boundary. See [MCP architecture](https://modelcontextprotocol.io/specification/2025-11-25/architecture) and [Podman run options](https://docs.podman.io/en/latest/markdown/podman-run.1.html).

## 13. Dashboard, reporting and email

The working UI is organized around owner decisions and company outcomes: **Today, Company, Goals & Projects, Work, Customers & Support, Decisions, Knowledge, and Audit**. Today shows verified progress, the next needed decision, blockers, budget, and operating exceptions. Co answers questions by linking to durable company records and can propose a plan with typed acceptance and authority.

React Flow is an optional inspection surface for work dependencies and actor activity. A graph animation never defines completion. Show source date/freshness, claim type, action status, verification status, and artifact links in ordinary work views. Browser acceptance covers accessibility, authorization, reconnect, and approval conflicts.

Reports derive numbers and statuses from the ledger and verified records. They distinguish completed, rejected, blocked, unknown, and proposed work. Default reporting is a daily digest at 09:00 Asia/Bangkok and weekly board packet Monday at 09:00; actual schedules activate only with the operating profile. Report goals, customers, delivery evidence, commitments, model costs, risks, decisions and unresolved exceptions.

Notify the owner for required decisions, meaningful blockers/failures, cap exhaustion, and major verified completion. Proposed targets: persist an actionable alert within 60 seconds, coalesce duplicate alerts, send at most ten routine emails/day plus digests, and keep critical events visible in the dashboard even if delivery is unavailable. An unchanged or idle state creates no repeated notification.

Store a durable notification ledger with event ID, recipient class, template version, payload hash, provider ID, attempts and delivery state. Resend supports idempotency keys with a limited retention window; Nexus must maintain its own long-term deduplication. Poll provider email status on the private Pi and reconcile accepted, delivered, bounced, failed or unknown states; do not open public ingress solely for notification webhooks. See [Resend idempotency](https://resend.com/docs/dashboard/emails/idempotency-keys) and [email retrieval](https://resend.com/docs/api-reference/emails/retrieve-email).

Email approval links open the authenticated dashboard. An email reply, unverified link request, or delivery receipt cannot approve an action. Missing sender/domain credentials produce a visible configuration block, not a success receipt.

## 14. Interfaces and repository layout

Expose company-system endpoints under `/api/v2` for company/department, goals/plans/work, knowledge/evidence, actions/approvals, runs/artifacts, budgets/models, reports/notifications, owner pause/cancel controls, and durable events. Bind every request to authenticated company/principal context. Use `202` for accepted asynchronous work, `409` for stale revisions or conflicts, `403` for denied authority, `422` for invalid schemas and `503` for unavailable required integrations.

Mutating requests require request IDs/idempotency keys and optimistic revision checks where applicable. Duplicate keys with different payloads conflict. List endpoints paginate; artifact access is permission-checked and bounded. Durable event streaming resumes from a persisted cursor and delivers ledger state rather than relying on volatile pub/sub history.

Retain existing `/api` endpoints through adapters where support is necessary. A legacy endpoint cannot enter the new execution path without a mapped company, policy, context and budget. Document removal only after compatibility consumers are identified and migrated.

Proposed additions, subject to repository conventions during M1:

```text
backend/nexus/company/       # mandates, charters, goals, management
backend/nexus/brain/         # ontology, claims, evidence, retrieval, context
backend/nexus/harness/       # actions, authority, budgets, limits, receipts
backend/nexus/execution/     # DBOS registration, segments, queue, recovery
backend/nexus/core/llm/      # extend existing factory with registry and governed gateway
backend/nexus/builder/       # runner protocol, workspace, sandbox policy
backend/nexus/verification/  # acceptance and independent evidence checks
backend/nexus/reporting/     # operating reports and notification ledger
backend/nexus/api/v2/        # company API adapters
backend/nexus/tests/integration/ # real DB, recovery and operating-cycle acceptance
frontend/src/features/      # company, work, approval, knowledge and audit views
infra/company/              # proposed private Pi/container deployment profile
```

Do not blindly create paths that conflict with existing packages. The contract map and import changes are an M1 deliverable. Settings stays the configuration boundary; structured logs carry company/work/action/run IDs without secrets or raw confidential context.

## 15. Deployment, recovery and portability

Read-only inspection on 2026-10-05 found a Pi 5 with ARM64, four cores, 16 GiB RAM, Docker installed, and Podman absent. Existing services share the host. The path `/media/santapong/seagate` resolved to an ext4 bind of root-backed service data at that check; it was not evidence of an independent backup disk. Recheck capacity and storage before installation.

Deploy a dedicated Nexus PostgreSQL service/database and company profile without altering n8n or unrelated services. The API/management memory target is at most 3 GiB combined, separate from the 4 GiB builder limit. Serve through authenticated tailnet-only access. The Pi makes outbound provider calls; no public exposure is required for owner email status.

Back up PostgreSQL and artifact content together with a consistent manifest of referenced hashes, versions and model/policy configuration. Encrypt backups and use a destination independent of the Pi's root device. Proposed recovery targets: **RPO 24 hours, RTO 2 hours once a host is available**. Validate restoration into a disposable environment; an untested backup is not a demonstrated recovery capability. Keep credentials out of artifacts and obtain them through approved deployment secret configuration.

For cloud migration, drain or checkpoint work, back up durable state, preserve company/action IDs and idempotency history, restore on the target, reconcile uncertain effects, and activate exactly one execution owner. A portable container profile and restore test precede a cloud cutover. Kubernetes, GPU hosting and separate graph clusters are not initial requirements.

## 16. Migration and compatibility

Start from current remote main in an isolated branch. Add schemas via new Alembic revisions; never edit previously merged migrations. Map legacy workspace IDs to Company IDs explicitly, preserve audit and source identities, and retain old records with their provenance.

The feature-gated company profile receives new mapped work. Keep legacy code available while callers migrate, but prevent the same task from entering both engines. Stop legacy intake and reconcile unfinished work before cutover. A Redis seen marker, Kafka offset, or legacy QA default is not evidence that a task completed. Legacy approvals lacking an exact hash and usable authority return for review rather than being upgraded to new authority automatically.

Apply Pydantic AI 2.x changes in one compatibility milestone with tested agent output, hooks, tools, model API families, deferred approval, usage and checkpoint registration. Register agents before DBOS launch and wrap consequential custom I/O in explicit durable steps. Test connection/session ownership and RLS on both API and worker connections.

Rollback can disable new intake and drain compatible workers; it cannot pretend committed external effects did not occur. For schema rollback, use a validated restore or forward correction rather than destructive migration of ledger history. Preserve receipts and unresolved actions across both rollback and upgrade.

The new SDD is the target for the company-system program. Existing README/CLAUDE/runtime describe the legacy system until milestone cutover. ADR-094–099 record proposed changes to previous accepted decisions; do not mark an older ADR superseded merely because this proposal exists.

## 17. Delivery and acceptance gates

Detailed tasks and the requirements matrix are in the [implementation plan](../company-system/IMPLEMENTATION_PLAN.md).

| Milestone | Outcome | Gate |
| --- | --- | --- |
| M0 | Baseline and specification | Saved design, ADRs, backlog, frozen contract/evaluation plan; documentation is delivered, executable fixtures pending |
| M1 | Governed durable runtime | Real approval visibility, binding, budget concurrency, restart/replay and provider conformance |
| M2 | Company Brain | Typed ontology, provenance, permissions, freshness and retrieval/context acceptance |
| M3 | Company management | Mandates/charters, valid bounded plans, deterministic eligibility, truthful reports |
| M4 | Native builder | One isolated Pi runner, resource/path/network checks, independent StockFlow behavior verification |
| M5 | Full readiness cycle | Strategy → build → verify → presentation/support → owner report and configured notification |
| M6 | Delegation and portability | Reviewed outcomes, recovery drills, explicit authority promotion, validated backup/restore and cloud profile |

Required suites cover every mutation route, two-session approval visibility, edited/expired/revoked decisions, stale resources, duplicate and competing workers, crashes around enqueue/effects/receipts, cost reservation concurrency, non-resetting limits, permissions and source conflicts, and realistic end-to-end StockFlow acceptance. Use fake models for deterministic correctness; separate live paid-provider and configured email proof from offline tests.

The Brain acceptance pack contains 30 frozen company questions spanning citations, source freshness, conflict, hypotheses, attachments, workspace context, and authorization. At least 27 must meet the predeclared answer rubric; all permission and false-completion cases must pass. Freeze cases and expected evidence before optimizing prompts. Passing a threshold does not authorize a tool outside policy.

Before Delegated mode, require at least 20 owner-reviewed completed work items with matching receipts and verifier results, passing crash/recovery drills, no unresolved unauthorized actions, and no missing terminal outcomes hidden as success. The owner explicitly reviews the authority delta. Board oversight follows several approved operating cycles under stable charters; workload and authority remain bounded.

Pi deployment acceptance includes real ARM64 startup, a representative StockFlow build/check job, a 24-hour bounded soak with crash injection and recovery, a backup restore, private authenticated access, and live configured owner notification proof. These tests are planned; none are claimed by this documentation delivery.

## 18. Meta Harness and future evolution

The future Meta Harness may observe failures, propose a bounded policy/prompt/tool change, evaluate it on frozen offline scenarios, present an owner review, promote a version, monitor it, and roll back. V1 records versions and feedback to make this possible, but contains no automatic optimizer, self-modification, prompt activation, or fine-tuning loop.

Reconsider Graphiti or a dedicated graph store only when measured temporal retrieval workloads exceed the typed PostgreSQL design. Reconsider Accretion delegation only after the native pilot identifies a concrete integration benefit and an explicit reviewed adapter. Neither future direction silently replaces the owner's current choices.

## 19. Inspiration and rationale

| Primary reference | Useful idea | Nexus application |
| --- | --- | --- |
| [Paperclip](https://github.com/paperclipai/paperclip) | Company goals, organization, budgets and board supervision | Mandates and outcome-based oversight; not a runtime dependency |
| [Palantir Ontology](https://www.palantir.com/docs/foundry/ontology/overview) and [Action Types](https://www.palantir.com/docs/foundry/action-types/getting-started) | Business objects connected to governed operations | Typed company objects plus action contracts; no Foundry dependency |
| [OpenAI harness engineering](https://openai.com/index/harness-engineering/) | Engineer the environment and feedback around agents | Observable boundaries, reproducible artifacts and verifier gates |
| [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | Distinguish predictable workflows from open-ended agents | Deterministic company procedures with bounded reasoning where needed |
| [Graphiti overview](https://help.getzep.com/graphiti/getting-started/overview) | Temporal relationships and provenance | Validity and source history; graph-engine adoption deferred |
| [DBOS architecture](https://docs.dbos.dev/architecture) | Durable state and execution through PostgreSQL | One Pi execution engine with application-owned action governance |

These references inspire design choices; they are not proof that Nexus has implemented them. The recommended architecture is a synthesis for this owner's constraints. Next implementation gate: finish executable M0 fixtures, then prove M1 before expanding the agent roster or delegating real company authority.
