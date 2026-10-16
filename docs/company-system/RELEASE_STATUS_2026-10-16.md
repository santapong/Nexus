# Nexus release progress and remaining schedule

Checked 2026-10-16, Asia/Bangkok. Production source is pushed at `7acbb8b` on
`feat/company-foundation`. Nexus is in implementation and integration; the
supervised release is open. This page is the concise owner view. Detailed proof
and limitations remain in [the release evidence index](RELEASE_GATES_CURRENT.md).

**Current planning target: 15–25 further working days for the supervised release,
approximately 6–20 November 2026 if work proceeds from 19 October. Confidence is
low until current native execution and a representative ARM64 build pass.**
Access, configuration, owner review and deployment approval waits are additional.
These are engineering estimates; no measured completion rate supports an overall
percentage or a guaranteed finish date.

## Progress by milestone

| Milestone | Verified progress | Remaining exit |
| --- | --- | --- |
| M0 — Design and contracts | Company Brain, management and Action Harness SDD, versioned contracts, frozen evaluation inputs and nominated StockFlow source are established | Keep exact source/profile pins current during integration |
| M1 — Governed execution | Offline acceptance passes with real PostgreSQL/DBOS recovery, approvals, quotas, spend reservations and uncertain-outcome handling | Qualify configured real model usage/cost and the final integrated release profile |
| M2 — Company Brain | Offline acceptance passes: 29/30 frozen answers, all critical cases; protected ingestion, provenance, retrieval and permissions have scoped evidence | Genuine model answer quality and current company inputs; the one failed answer remains visible |
| M3 — Management | Goals/plans, department scopes, bounded scheduling, metrics, reports and owner controls are implemented with scoped checks | Demonstrate the connected operating workflow and populated owner browser journey |
| M4 — Native builder | Local contained execution/cache/recovery pieces have actual evidence; latest production repair passes 4,307 backend unit tests | Current five-case fault qualification, actual StockFlow author/verifier run and representative ARM64/Pi build; this is the critical path |
| M5 — First company cycle | Strategy publication/proof, presentation/support foundations, dashboard/inbox and notification recovery pieces are implemented and partly qualified | One actual goal: strategy → build → independent verification → presentation/support → owner report/dashboard/email |
| M6 — Operations and release | Backup codec and scoped recovery procedures are implemented/tested | Independent backup/key custody, disaster restore with RPO/RTO, private access, rollback, 24-hour bounded soak and release approval |

M1/M2 acceptance is scoped offline evidence. Earlier runtime profiles and
individual component checks do not qualify the current whole system.

## What is happening now

The current V9 owned-container stop repair is committed and pushed. Its production
source passes 4,307 unit tests, configured strict typing and lint/format checks.
The private qualification composition separately passes 354 focused checks and
strict/lint/format checks on 43 files. Those counts describe different scopes.

Fresh public fixture preparation completes in1.07s. The first diagnostic launcher
fails before schema/public setup; its namespace defect is independently reproduced.
After a read-only audit confirms the target is still empty, the corrected direct
CLI completes all-five setup in68.827s. Independent file/SQL audit verifies all
five authorized actions are unissued, with zero attempts/intents/leases.

The first packet producer times out after writing metadata; a separate published
passive check validates those preserved files. Startup plus an additional36s sleep
poses a pre-issuance timing risk inside the45s parent. A new candidate will wait
until actual scope age36.250001s, preserving the existing strict causal guard and
all fault deadlines. No V9 native fault case has run. See the [actual preparation
checkpoint](CURRENT_V9_SETUP_AND_PARENT_AGE_CHECKPOINT_2026-10-16.md). Failed
operations, original clocks/windows and all old failed waves remain preserved.

Earlier parent-expiry and metadata recovery pass under V8. Earlier cancellation
fails physical process retirement, which motivated V9. Pause, READ revocation and
stale-fence cases from that stopped wave remain unissued. The new version must
qualify all five cases before selected StockFlow execution.

## Remaining delivery sequence

| Workstream | Planning allowance | Observable finish |
| --- | --- | --- |
| Current native qualification | 1–3 working days, uncertain | Exact current source passes parent expiry, cancellation, pause, READ revocation and stale-fence cases, with conserved ledgers and original timing bounds |
| Connected local StockFlow pilot | 3–5 working days after the native gate | One full goal has actual author/verifier receipts, accepted presentation/support outputs and a readable owner report; local/offline scope stated |
| Model, dashboard and email integration | 4–7 working days; independent preparation can overlap | Approved models/prices, real quality/usage under the US$5/day controls, populated browser UAT and configured email acceptance/delivery/reconciliation |
| ARM64 and private operations | 4–7 working days after applicable setup is available; preparation can overlap | Representative Pi job, private access, independent restore, rollback and at least 24 hours of bounded soak |
| Integration failures and final review | 3–5 working days across the plan | Unresolved release failures closed or explicitly scoped; concrete release packet ready for owner approval |

Allowances overlap and are planning judgments, not benchmarked task durations.
The 15–25-day release range includes integration contingency. Reforecast after
the first actual StockFlow author/verifier run and representative Pi run. If a
workstream exceeds its allowance, report its exact blocker and a revised range;
do not silently roll the target forward or expand scope.

## Next checkpoint and team

Root owns the release critical path, integration and concrete launch decisions.
One existing worker supports the launcher/native qualification path; a second
checks release evidence and the plan; the third is available for disjoint
owner-facing or recovery preparation. Keep the team at Root plus three workers.
Review high-impact ownership/auth/spend/recovery boundaries at milestones.
Routine reversible fixes use focused checks; repeat full regressions when source
changes or a failure justifies them.

The next checkpoint must show the setup outcome, all-five fault pass/fail state
and the actual next business-cycle step. Native faults remain a release gate.
Prepare other independent work while this gate is unresolved.

The Pi's last read-only preparation found missing rootless tools and disabled
memory control. Configuration/install/reboot, live model spending, real email and
deployment require their applicable concrete setup and existing approval scope.
There is no owner input request in this status update.

## Later autonomy

The first release stays Supervised. Delegated/Board operation requires at least
20 reviewed completed work items, recovery evidence, several stable operating
cycles and an explicit owner decision. The earlier 2–4-or-more-week observation
allowance after the pilot is still a planning estimate. Calendar time alone
cannot promote authority. Automatic Meta Harness changes, dedicated graph
infrastructure and SaaS expansion remain deferred.

The [13 October roadmap](DELIVERY_ROADMAP.md) remains historical whole-program
scope/effort context: its 48–73 engineering days assumed one engineer without a
parallel team. It is not an estimate of work remaining today.

Evidence: [M1 acceptance](M1_OFFLINE_ACCEPTANCE_2026-10-14.md),
[M2 acceptance](M2_OFFLINE_ACCEPTANCE_2026-10-14.md),
[current production repair](NATIVE_OWNED_STOP_V9_SOURCE_CHECKPOINT_2026-10-16.md),
[stopped V8 wave](CURRENT_V8_NEGATIVE_ADMISSION_CHECKPOINT_2026-10-16.md),
[Pi preparation](PI_BUILDER_READINESS_CHECKPOINT_2026-10-15.md).
The actual fresh V9 setup terminal and complete streams are retained under
`/home/santapong/.codex/nexus-v9-n-preparation-command-20261016-1`; terminal receipt
SHA-256 is `7742dc25346e00583d43d23656c1b331705128e1e7e50269aed556f6392538be`.
The independent definitions-only diagnosis is
`/mnt/data/nexus-implementation-evidence-2026-10-14/stockflow/current-v9-setup-launch-namespace-diagnosis-1.json`,
SHA-256 `5342cfab21af47784f4ccd732e463a9789a2c80f5d040c6e4b48272417d474c9`.
