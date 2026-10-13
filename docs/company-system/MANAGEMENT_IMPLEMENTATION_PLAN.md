# M3 bounded company management — interface proposal, 2026-10-14

This is the root-selected local implementation plan, not executed management, an installed schema, a live scheduler or M3 acceptance. DTO and transaction preparation is authorized; runtime activation stays gated on M2. The current M2 frozen-question score remains an independent prerequisite. No source/schema edits accompany this proposal.

## Frozen initial integration decisions

- Approval hashes the full versioned manifest, including exact actors/workspace,
  trace/run/workflow/model pins, mandate/goal/charter revisions, USD at six
  decimal places and explicit per-kind quotas. WorkPlan alone is insufficient.
- Exactly one non-executing procedure allocation root exists per company/goal.
  New plan IDs and revisions reuse it. Unchanged child registrations replay
  exactly; changed work uses new child IDs funded from its remaining lifetime
  slice. Cancellation never refunds delegation, attempts or uncertain charges.
- Initial plan approval consumes no revision slot. Later approved revisions
  consume the root's bounded plan_revisions allowance via immutable owner
  administrative events under CompanyControl, without a forged worker lease or
  a fence-zero ExecutionAttempt.
- The approved manifest has VerificationIntent(author_task, verifier_task, registered_check_recipe), because future output hashes do not exist. Runtime VerificationSpec resolves the actual author task/run and receipt/artifact hashes; unbound targets are ineligible.
  Verification-trigger edges participate in cycle validation but do not require
  author acceptance to initiate the independent read/check procedure.
- Independent acceptance and its invalidation history are separate from M1
  receipt/candidate/ExecutionState. No raw completed-state mutation is added.
- Initial metadata consists of21 tables: the19 record groups below plus owner
  administrative revision events and acceptance invalidation history. Metadata
  declarations do not count as normal migration installation or acceptance.
- Root owns normal company009, forced RLS/immutable guards, atomic registration,
  current authority/effect integration and final acceptance. The contract worker
  owns separate management DTOs/metadata/tests. The answer worker continues M2;
  review occurs at concrete interface and combined milestone boundaries.

A same-session directory registration boundary passes14 real restricted-PG checks (3 atomic identity/batch scenarios plus11 existing directory cases),8.54s. A second child exceeding parent model quota rolls back both child registrations, all delegated USD and runtime quota; exact replay delegates once. Wrong verified workspace is denied. Strict types2files and Ruff pass. The complete management
approval/registration transaction and scheduler remain to be implemented.

## Intended result

An actual owner-approved internal research/report procedure should progress from mandate and measured goal to bounded work, cited artifact, independent acceptance and ledger-derived report. Idle management should make no model requests. Unknown effects, unknown billing, blocked work and inactive work should remain visible without fabricating completion or releasing holds.

Normative inputs: `docs/sdd/NEXUS_SDD_v0.2.md` §§4,7,9,13,17; `docs/company-system/IMPLEMENTATION_PLAN.md` M3/MGMT-01/MGMT-02; `RELEASE_EXECUTION_PLAN.md` supervised gates. Current implementation inputs: company/contracts/{company,work,results}.py, directory_store.py, runtime_{contracts,models,registration,store,recovery}.py, effect_store.py, dispatch scheduling, standing authority, owner reconciliation/billing, M2 typed publication and C context/model hook.

## Current reusable boundaries and missing proof

- `CompanyMandate`/`DepartmentCharter` are typed values, not persisted approval or permission. A department is a charter served by a small shared worker pool; it does not need an idle reasoning agent.
- `WorkPlan` already rejects duplicate/foreign tasks, unknown dependencies and cycles, with100-node maximum. `WorkItem` carries goal, department, acceptance and dependency IDs. These shapes do not prove owner approval, an actual measured goal, persistent dependencies, current charter/tool eligibility or runtime registration.
- `PersistentCompanyDirectory.register_work` owns actual actors/workspace/trace/ancestry and permanent parent USD slices. `ExecutionStore.register` owns stable run/workflow/version/model pins and permanent per-kind quota slices. Public methods open their own company-first transactions; a plan batch must use coordinated same-session helpers rather than call them recursively while holding CompanyControl.
- Lifetime counters and parent consumed+delegated quota remain authoritative across retries, fallback, rework, workflow/segment changes and Bangkok midnight. Current persisted root maxima are12 model requests,20 tool attempts,2 rework rounds and2 plan revisions; zero-valued child per-kind quotas are valid. Routing fallback consumes the same model/tool allowance rather than a fresh pool. New plan revisions cannot mint a new root allowance for the same logical procedure.
- Segments and external intents are fenced. Scheduling has immutable dispatch identity and transactional DBOS enqueue. Waiting approval releases worker capacity. Unknown effects cannot be automatically reissued; reconciliation cannot create a new effect or refund an unconfirmed charge.
- M1 has actual receipt/usage/billing evidence and stored format-bound verification candidates. `pass` in verification_json is not independently verified acceptance. Current ExecutionState is only eligible/running/awaiting_approval/outcome_unknown/verifying/blocked; there is no completed state or trusted persistent work-acceptance publisher that can safely enable completed dependencies. Root must choose an additive immutable acceptance/outcome record and terminal-state migration before that transition can exist. M2 knowledge records and verified_by proposals cannot substitute.
- M2 context has exact protected bytes, complete contributor ACL/source-head snapshots, untrusted-data rendering and a model before-intent guard. M3 mandate/goal/charter/work/feedback instructions must enter the same estimator-covered context path, not a second prompt builder.

## Proposed records and interfaces for root to freeze

All writes use verified identity, actual company/workspace membership, typed scope, CompanyControl first and database clock. Append-only versions carry exact canonical hash and audited current owner. New API/DDL shapes remain proposals until root chooses them.

1. **Owner mandate and charters.** `ManagementControlStore.publish_mandate/publish_charter(scope, identity, command, expected_current_version)` persists exact owner-authorized revisions and current pointers. A proposal is a distinct non-operative shape. Mandate revocation immediately blocks fresh work/authorization; historical records and issued effects remain available for truthful audit/reconciliation. Charter tools/resources only restrict eligibility; they never grant M1 permissions or widen data access. Oversight remains supervised: decoding delegated/board is not mode promotion, and M6 evidence plus an explicit actual-owner authority decision remains required.
2. **Measured goals.** `GoalStore.propose/approve(scope, identity, GoalProposal)` binds company, approved mandate, responsible principal, explicit metric, unit, comparator/target, baseline known-or-unknown, observation/evidence recipe and meaningful due precision. A metric name on a Brain Goal entity is insufficient. Actual observations record source/measurement date and independent provenance; missing baseline or unknown time stays unknown. Due scheduling uses explicitly supplied instants or an owner-defined date interpretation, not invented midnight from date-only source text.
3. **Approved persistent plan.** `ManagementPlanStore.propose_plan` validates actual goal/charter/actors/dependencies and proposed M1 reservations; it creates no running tasks. `approve_and_register_plan(scope, identity, plan_id, exact_revision_hash, expected_current_revision)` atomically persists owner approval, immutable plan/items/dependency rows and directory/runtime registrations under one mutex. It validates all ancestors, actual members/verifier separation, resource grants, allowed tools and partitioned budget/quota before any child commits. A failing item rolls back the entire batch. Canonical hash recipe, exact counts and USD normalization must be frozen; current permissive proposal shapes are not automatically an approval wire contract.
4. **Acceptance publisher.** `WorkAcceptanceStore.publish_verified_result(verifier_scope, identity, protected_check_reference)` is a trusted service, not an HTTP raw-verdict endpoint. It binds original task/trace/run/version, immutable acceptance criteria, exact receipt/artifacts and actual verifier distinct from author. Read-only evidence/check execution occurs outside the database mutex; current verifier membership/charter, exact record/hash/ACL/criteria/run and stale-fence safeguards are rechecked before immutable acceptance + work outcome + event commit. Rejected/inconclusive checks remain explicit. Generated code, a saved artifact, tests of a fake fixture and model agreement cannot establish arbitrary business acceptance.
5. **Eligibility.** `ManagementEligibility.evaluate(company_scope, cursor, due_time)` is deterministic database work. It returns typed eligible/waiting/blocked/cancelled reasons and stable operation identities. `reserve_eligible_and_enqueue` rechecks plan/mandate/charter/goal/work/ancestor/acceptance/resource/current authority under CompanyControl and calls the existing transaction-scoped scheduling path. A model is called only by an issued governed segment, never by a scan with no eligible work.
6. **Commitments and reports.** `CommitmentStore.record/revise` binds owner-approved plan lineage, explicit due precision, deliverable and source/resource visibility. A commitment is intent, not delivery. `OperatingReportStore.snapshot(scope, identity, interval)` reads actual receipts, immutable acceptance, holds/spend, unknown outcomes/billing, cancellations, blockers and owner decisions. Company totals require the actual authorized company-report scope; work actors get their own eligible scope. A model may write commentary from the frozen snapshot; it cannot alter its amounts, statuses or completion set. Report/artifact provenance includes actual contributing resources and reader intersection.

## Scheduling and dependency semantics

Normal `depends_on` means independently accepted work, not a successful SDK response, generated file, receipt=success, status=verifying or candidate verdict=pass. Missing/rejected/inconclusive acceptance yields an explicit dependency reason. The scheduler rechecks acceptance invalidation/revision binding; it does not guess that an old result proves changed criteria.

Verification initiation needs a separate typed `verification_of` binding. Otherwise putting a verifier after its unaccepted author in the ordinary dependency DAG deadlocks. An approved verifier procedure becomes eligible when an exact issued result/receipt and its protected evidence are available; this trigger authorizes read/check work only and does not complete the author. A trusted verifier result can then enable ordinary downstream work. Verification adapters use auditable mechanical criteria/evidence rather than an infinite chain of agents verifying one another. Unsupported semantic acceptance remains inconclusive or requires the explicitly registered independent review procedure.

Plan approval allocates one registered parent procedure allowance, with permanently delegated child slices. Priority changes or rework do not create new workflow-root budget/counter pools. New logical work requires explicit bounded owner plan revision and remaining parent allowance. Already registered task/run/trace/criteria cannot be silently rebound. A changed acceptance/policy/resource snapshot requires explicit revision and current authority, preserving old attempts/receipts and no automatic refund.

Current M1 await/release/recover APIs stay authoritative. Approval or budget waiting ends a segment and frees the single worker slot. A model over-bound/invalid result remains blocked; unknown issued effects/billing retain their unknown state/hold. Resume must be an explicit audited operation with current source/authority/work checks, preserving existing counters and principal/fence ownership. A revoked actor cannot write through an owner's reconciliation fence after reactivation.

Eligibility events include approved/revoked mandate or plan, current member/charter/resource change, known receipt, trusted acceptance, commitment due time, approval decision and reconciled uncertainty. Consume an immutable company cursor and stable deduplication key in the same transaction as eligibility/enqueue. Replaying an event cannot schedule a second logical dispatch or acknowledge a failed transaction. Due scans have bounded rows and cheap deterministic SQL, with the proposed one-minute due check/fifteen-minute opportunity policy configurable and unactivated until root selects an operating profile.

No sleeping model loop, one agent per department or model call to discover that nothing is due. Current company pause and work ancestry cancellation stop new calls/attempts; report and trusted issued-effect reconciliation still describe what actually happened.

## First offline procedure

Use nominated committed StockFlow sources through the configured Brain registry and existing protected citations, with explicitly granted reader/verifier access. Freeze one owner-approved measured internal report goal and its acceptance before running it.

1. Research task reads bounded current citations and produces a source-linked draft under its inherited allowance.
2. A distinct approved verifier procedure checks the draft against declared evidence/precision/schema criteria. It publishes independent acceptance or honest rejection/inconclusive; source-reported claims alone are insufficient.
3. Report task becomes eligible from accepted research, creates a sanitized artifact from current cited facts plus an actual authorized ledger snapshot, and retains contributor provenance.
4. Independent report checks validate actual evidence/amount/date/status consistency. Only the trusted acceptance record can mark that declared work completed and satisfy the measured goal.
5. An owner-facing operating packet lists accepted work, known failed/blocked/cancelled work, unknown effects/billing, retained holds, decisions and actual costs. External customer notification/delivery, deployment and Pi operation remain M4/M5/configured authorization gates.

This proves only the frozen internal report criteria. It does not prove arbitrary natural-language truth, StockFlow release readiness, customer impact, email delivery or company autonomy.

## Coherent implementation packages and tests

| Package | Depends on | Required actual proof |
| --- | --- | --- |
| M3-A mandate/charter/measured goal + strict immutable approval records | accepted M2/current owner boundary | owner/role/tenant/revocation/stale-version tests; Brain records cannot issue mandate/tool/budget authority |
| M3-B atomic approved DAG registration and parent allocation | A + existing M1 registration | duplicate/cycle/foreign goal or actor; failure rolls back; parent consumed+delegated USD and per-kind quota conserved; revision/retry cannot reset allowance |
| M3-C independent acceptance and verification initiation | A/B + actual receipt/protected evidence | pass-candidate cannot complete dependency; wrong task/action/run/criteria/verifier/ACL/hash denies; stale/revoked verifier cannot commit; reject/inconclusive remains truthful |
| M3-D deterministic event eligibility/enqueue and controlled resume | B/C + M1 dispatch/current guards | zero model calls over repeated idle/due/replayed events; one enqueue under two scheduler races; DBOS same-dispatch restart; live lease not taken over; approval/budget waiting frees capacity |
| M3-E commitments/report projection + owner views | A-D + actual ledgers | known success without acceptance remains verifying; absent usage/unknown bill never fabricated zero; inactive/blocked/cancelled/unknown shown; actual private resource and role restrictions/reconnect/conflicts |
| M3-F one complete offline research/report goal and failure matrix | A-E | evidence manifest for mandate→approved plan→work→receipts→actual independent acceptance→report; no live/provider/email claim from fake cases |

Use one focused package suite while building, actual isolated restricted-PG fixtures through normal root-owned profile migrations, deterministic TestModel/MockTransport and separate process recovery checks where they establish new behavior. Run the combined M3 gate once these interfaces are coherent; repeat only after changes, failures or unresolved concerns. Current accepted M1/M2 static/unit evidence is a prerequisite, not proof of these executions.

Owner review belongs at initial mandate/material scope or authority changes, consequential external actions and the applicable operating-mode/deployment decisions. Routine internal approved procedure checks use the current grants, bounded ledgers and trusted verification; the plan does not require owner review for every source/code edit.

## Effort estimate and root decisions

Planning estimate after M2 acceptance:12–18 focused engineering days, with A/B then C/D dependency overlap and E started on frozen query DTOs. A supervised offline report procedure is the first coherent slice; the actual duration depends on how much independent verifier/report infrastructure proves reusable. ARM64 builder, full StockFlow readiness, live provider/email and restore/private-access qualification are excluded from this estimate. This is a forecast, not elapsed execution evidence.

Root should freeze: management approval/canonicalization ABI; exact measured-goal metrics; one parent procedure allowance and child allocation rules; same-session registration wrappers; trusted verifier interface/evidence and completion schema; verification initiation trigger distinct from accepted dependencies; event/cursor/enqueue composition; report scopes and commitment due-time policy. Root owns resulting migration/profile/API integration. No new code/schema/activation starts from this proposal alone.
