# Nexus release execution plan

**Started:** 2026-10-13 (Asia/Bangkok). **Goal:** deliver the agreed supervised company-system release with evidence, then follow the approved release workflow.

## Team and interfaces

Use one orchestrating/integrating root and three bounded agents. Root owns sequencing, shared contracts, dependency/lock changes, schema and authenticated runtime integration. The model worker owns registry/pricing/routing modules. The replay worker owns execution/checkpoint fake fixtures. The planner owns critical-path review and then the isolated access/auth module package.

Agents work on disjoint files in the existing implementation checkout. They report interface changes before integration, keep local task/evidence records and do not recursively create teams. No automatic branch reset, mass refactor, provider activation or release publishing accompanies delegation.

**2026-10-14 ownership update:** the M1 offline exit has independent combined acceptance. M2 preparation now assigns shared Brain DTO/models to the model worker, deterministic ingestion/parser/blob/outbox to replay worker, permission-aware retrieval/context to planner, and current scope/ACL/migrations/API/acceptance integration to root. Actual package namespace is `backend/nexus/company/brain/`. Agree fields and method signatures before parallel writes; head migrations remain coordinator-owned. [M1 evidence](M1_OFFLINE_ACCEPTANCE_2026-10-14.md) and [M2 plan](BRAIN_IMPLEMENTATION_PLAN.md) define activation gates.

## Current wave

### Active continuation — 2026-10-15

Latest reviewed local milestone: `6e37386` adds dormant full-plan admission windows
to the actual-owner proof reader in `943c5ec`. Root combined3,253unit/54.77s and
strict/lint/format12 pass. The following older foundation/notification-wave tables
are historical; current lane ownership is:

| Owner | Current deliverable | Next evidence |
| --- | --- | --- |
| notification_profiles | Actual-owner current Strategy proof SQL fixture | Four independent public lineages, unchanged ledgers, current READ/blocked/credential-expiry denials |
| recovery_resume | Independent contained outer-fault review, then owner-transition plan | Exact controller/collector ownership and bounded launch; choice/revision2 interfaces before implementation |
| engineering_resume | Separate contained outer-fault fixture and dynamic launch packet | Normal015/public setup, actual config/approval/hold pins, one separately reviewed bounded fault operation |
| Root | Integrate milestones and qualify actual cases | Owner proof SQL, owner choice/full cycle, then remaining provider/ARM64/UAT/operations gates |

The successful methodv6 M1/replay and native Strategy publication/expiry rollback
are actual saved qualifications. The outer fault and actual owner reads are still
pending. Frozen source packages remain pinned to their original committed bases;
later dormant source additions do not silently rebase or activate them.

The initial foundation lanes below are historical. Current local headae7d9b5 plus
notification OS qualification integrates Brain/management, native engineering
acceptance/recovery, notification staging/atomic enqueue and configured contained
runtime source. Root2,518unit/24.36s and strict/Ruff/format12 pass. Four actual
notification crash/immediate-restart cases qualify no-reissue and conserved native
history. Actual contained payload M1/timeout, full business/provider/ARM64 and
operational release gates remain separate; production workers stay unconfigured.

| Owner | Active deliverable | Required next evidence |
| --- | --- | --- |
| engineering_resume | Exact contained M1/outer-timeout fixture and source staging | New public setup packet, actual payload/conmon/caps/sidecar/protected receipt/replay/cleanup, then timeout |
| recovery_resume | Frozen notification OS fixtures and retained evidence | Four-case terminal inventory and focused source preservation; no real email activation |
| notification_profiles | Independent review at combined runtime milestones | Actual barrier/liveness/native outcome conservation and no second request |
| Root | Integration, concrete qualification launches and release gates | Full StockFlow, owner UAT/email, live models, ARM64/private operations and supervised release |

The first OS intent case completed after source expiry and proves historical
unknown-state conservation only. The saved-result case recovered current protected
acceptance without another container; neither is full StockFlow or ARM64 evidence.
Retain all prepared process databases and protected backup pairs. The four known
cases ran sequentially under reviewed unchanged code, exact pins and source>=180s
before launch. Actual owned-container cleanup is separately scoped after the wave;
there is no repeated process-wave claim. Fixture authority does not activate workers.
Immediate automatic engineering acquisition is now qualified separately by two
actual cases with live old leases observed inside the restarted helper; see the
2026-10-15 immediate restart checkpoint. The earlier five controllers' manual wait
receipts remain historical and are not relabeled as this later proof.

| Lane | Deliverable | Exit |
| --- | --- | --- |
| Models | Registry, dated prices, conservative bounded quotes, deterministic eligible routing/fallback | Negative conformance/cost cases pass; no invented live model or price |
| Replay | Stable fake worker/checkpoint, non-resetting counters, approval segment release, honest unknown effects | Deterministic resume/error/limit tests pass; no claim of DBOS durability |
| Access | Verified JWT identity plus current directory/work ownership and capability policy | Denied foreign/inactive/revoked/spoofed access; owner controls work without an active task |
| Root integration | SDK/DBOS spike, migration replay/RLS preflight, persisted work/parent ownership and runtime integration | Real database/auth/recovery evidence before mounting intake |

M0 freezes worker/model interfaces. M1 proves the actual durable runtime, standing internal grants, parent quota ownership, effect fencing, atomic enqueue and authenticated API. M2–M5 deliver Brain, management, native builder and the readiness cycle. The supervised release also requires operational recovery/private-access proof from M6.

## Review policy

Routine reversible local implementation choices and fixes proceed under the current scope. Agents run targeted tests and lint for their packages. Root reviews changed interfaces and high-impact approvals/auth/budget/ownership/migration/recovery boundaries at integration checkpoints. An independent agent reviews the combined milestone once the implementation and evidence are concrete.

Run the full relevant regression at milestone integration, not after every edit. Repeat checks when code, failures or unresolved concerns justify it. Security/permission failures stop activation; visual/wording polish does not block unrelated backend work. Owner review is reserved for material authority/product changes, external commitments, and applicable final deployment/publication decisions.

## Research policy

When framework semantics or implementation style are uncertain, first inspect the pinned local package and official primary documentation, then run a bounded compatibility/failure spike. Record the result and version before changing architecture. A current documentation example cannot establish behavior of an older selected package.

The DBOS enqueue must share the business transaction; approval waits end a segment and release capacity. Permanent application IDs remain separate from active queue deduplication. API scope comes from authenticated identity plus live membership/work ownership, not a caller-supplied LedgerScope or the legacy anonymous personal-mode fallback.

## Release gates

Release initially in Supervised mode with internal work/drafts. Require authenticated M1 governance/recovery, M2 frozen Brain acceptance, M3 bounded work/zero-cost idle operation, M4 representative bounded ARM64 build, M5 full StockFlow goal-to-receipt cycle, and demonstrated backup/restore/private access/rollback.

Twenty reviewed completed items and several stable cycles govern later Delegated/Board authority; they do not force premature authority promotion or block a release that stays supervised. Automatic Meta Harness improvement and dedicated graph infrastructure remain deferred.

The [roadmap estimate](DELIVERY_ROADMAP.md) remains the measured-planning baseline. Parallel agents shorten independent work, while SDK/schema/auth/recovery integration remains the critical path. Re-estimate from package throughput after M1 rather than dividing calendar time by agent count.

Source references: [DBOS outbox](https://docs.dbos.dev/python/examples/outbox), [DBOS queues](https://docs.dbos.dev/python/tutorials/queue-tutorial), [Pydantic AI DBOS integration](https://pydantic.dev/docs/ai/capabilities/durable_execution/dbos/), [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).
