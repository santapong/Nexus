# Nexus implementation progress

**Checked:** 2026-10-14. **Branch:** `feature/company-foundation`. **Baseline:** `6a8c8ef`.\
Plan and time assumptions: [delivery roadmap](DELIVERY_ROADMAP.md).

## Working contract

TASK: deliver the agreed supervised company-system release under the active goal, using one root integrator and three bounded workers. Apply milestone reviews to authority, spend, schema and recovery; routine reversible edits proceed with focused author checks.

FILES TO CREATE: `backend/nexus/company/contracts/` (base, company, work, knowledge, actions, results); `backend/nexus/harness/` (canonicalization, approval policy, lifecycle, limits and ledger as validated); focused unit/integration tests; frozen M0 fixtures; roadmap/progress documentation. Any new persistent tables need an additive Alembic migration.

FILES TO CHANGE: documentation indexes/backlog/changelog/decisions; existing application files only when a proved integration boundary requires it. Retain legacy runtime behavior until the new path's activation gates pass.

TESTS: schema validation, graph cycles/unknown dependencies, company mismatches, timestamp/decimal bounds, exact hash/owner/expiry/revision checks, uncertain-result completion rejection, non-resetting limits, and real separate-session approval/cost races where persistence is added. Write failing tests first. Run repository lint/type/unit checks after implementation.

DEFINITION OF DONE: validated M0–M5 company operation plus applicable M6 private-access/recovery proof, concrete release artifacts and the required final deployment/publication steps. Board/Delegated promotion remains an explicit later owner decision. The current wave is an implementation checkpoint, not release completion.

RISK: medium/high at approval and spend boundaries; mitigate with immutable payload snapshots, fail-closed checks, real transaction tests, and no live provider/external effect or deployment activation in this slice.

## Milestones

| Milestone | Status | Evidence |
| --- | --- | --- |
| M0 documentation | Delivered 2026-10-05 | SDD, architecture and ADR/backlog proposals |
| M0 executable foundation | Offline exit verified | 13 schemas, frozen scenarios/questions/checklist, fake-worker44 and committed StockFlow nomination; no business completion claim |
| M1 governed runtime | Offline exit verified; live activation gated | [M1 acceptance](M1_OFFLINE_ACCEPTANCE_2026-10-14.md): real segmented approval/process/version recovery, provider gate/client and independent combined review |
| M2 Company Brain | Offline exit verified | [Acceptance](M2_OFFLINE_ACCEPTANCE_2026-10-14.md): reviewed43-table provenance/ACL/context/API/model boundary, real nominated source access; second29/30/all16critical, first failure preserved. Live quality and full release remain open |
| M3 management | Pending | No live scheduler/company-operation claim |
| M4 native builder | Pending | Pi setup and sandbox proof remain separate |
| M5 full pilot | Pending | No StockFlow/customer/email execution claim |
| M6 delegation/portability | Pending | Requires reviewed cycles and restore/recovery evidence |

## Baseline reconciliation

Fresh remote check on 2026-10-13 returned main/HEAD `6a8c8ef`; no develop branch. The prior documentation remains local and is carried into this implementation branch. Primary Nexus checkout remains untouched. The prior temporary environment had expired; the recreated locked Python 3.12 environment is `/mnt/data/nexus-build-env-2026-10-13`.

## Delivered foundation

- Thirteen strict [contract schemas](CONTRACTS_v1.json): mandate/charter, work/plan, evidence/claim/context, action/approval, receipts, verification and reporting.
- Company-bound DAG validation, source and claim access checks, canonical action digests, exact current owner approval, fail-closed completion and serializable attempt counters.
- Standalone PostgreSQL journal: committed pending decisions, immutable snapshots, single-use consumption, per-company RLS, persisted owner pause, atomic daily/work reservations and unknown-billing holds/reconciliation.
- Additive migration 017 and matching metadata; frozen 30-question synthetic Brain pack, ten-criterion StockFlow checklist, [migration inventory](MIGRATION_INVENTORY.md), ADR-100 and a dedicated PostgreSQL CI job.

## Historical initial-slice evidence

Earlier on 2026-10-13, Python 3.12.9, original lockfile, local PostgreSQL 17 with a non-superuser app role:

- Full unit regression: **275 passed**, 25 existing deprecation warnings.
- Focused foundation acceptance: **59 passed**, including **9 real PostgreSQL cases**.
- New company/harness statement coverage: **94.46%** (614 statements, 34 uncovered). This is new-module coverage, not portfolio/whole-legacy coverage.
- Ruff lint and format pass; CI-style strict-config mypy passes across **224 source files**.
- Migration 017 upgrades/downgrades in a disposable empty DB and matches ORM metadata. CI YAML is parsed; its PostgreSQL 16 job is configured but has not run remotely.

Raw coverage and schema manifest: `/mnt/data/nexus-implementation-evidence-2026-10-13/`. Earlier interrupted runs are not evidence of success. [Validation record](VALIDATION_2026-10-13.md) states scope and remaining gates.

## Current integration wave — 2026-10-13

The user explicitly authorized multi-agent help and a release goal. [Release execution plan](RELEASE_EXECUTION_PLAN.md) records team ownership, interface sequencing, research spikes and risk-based review. Implementation remains local on the feature branch; no remote publication or deployment is implied by a passing package.

Installed/locked runtime: Python3.12.9, Pydantic AI slim2.54.0 (explicit provider/DBOS extras), DBOS3.2.0, Pydantic2.13.4, Litestar2.24, SQLAlchemy2.0.51 and AdvancedAlchemy0.34. Original-SDK and isolated-spike environments remain available for scoped regression.

Delivered in this wave:

- Server-verified JWT/current directory access; owner controls operate before a work task exists. Owner audit reads remain possible for correctly scoped inactive work while execution stays denied.
- Immutable registered work/ancestry with permanently partitioned parent USD allowances; current authorization rechecks membership/resources/versions under the company lock.
- Exact standing capabilities for reviewed offline internal tools only; source links persist which grant authorized each consumed action. Revocation, binding changes and expiry are rechecked at effects.
- Lifetime per-kind quotas and fenced effect stores, with committed intent, one-time call permits, unknown-outcome reconciliation and verification candidates that do not publish completion. Same-dispatch process recovery integration is in progress.
- Independent normal Alembic company001–005 lineage, 16 tables, RLS and immutability/counter-floor guards. Clean install/repeat/schema comparison/downgrade preserves unrelated legacy data/history. The old clean legacy chain still fails in003; it is preserved rather than silently stamped.
- Actual DBOS SQL function enqueue shares approval-consumption/cost/dispatch transaction; immutable run/workspace/version/next-segment binding prevents new workflow IDs from rescheduling one action. Unissued holds crossing midnight transfer atomically into the effect day's allowance; issued/unknown billing is retained.
- Isolated read/control API profile with actual HTTP/non-superuser database tests. Its decision result states decision_saved, scheduled=false, executed=false. New work/model/effect intake remains disabled.
- Legacy SDK call sites preserve explicit API families and reject unknown usage; malformed/error/timeout QA cannot approve. PostgreSQL RLS binding/failure propagation and failed Kafka-start cleanup are corrected.

Current package evidence: full pre-final-wave unit regression542 passes; actual SDK1/SDK2 compatibility82 cases each; QA/usage59; legacy behavior/chaos plus producer cleanup61; registered-governance32, owner-controls10, standing55unit+11PG, standing-consumption5PG, combined atomic enqueue/day-transfer11PG, company-API5unit+15PG, clean16-table profile1PG. Runtime/effect and final combined regression are still evolving; do not add these overlapping counts into a fictitious total. See the current governance validation record and evidence folder.

The first independent integration review confirmed segment-splicing, midnight-accounting and inactive-owner-audit gaps. New targeted cases reproduced the failures before their fixes; queue/day11 and access31 now pass. The review excluded unfinished worker/provider/API packages; their end-to-end proof remains necessary.

## Next release gate

Finish the registered governed DBOS worker with real process-kill/known-output/unknown-effect/version proof and offline OpenAI/Google request/usage conformance. Combine effect-day and same-dispatch recovery with API/durable scheduling before enabling new intake. Then deliver Brain, bounded management, native ARM64 builder, full StockFlow readiness, dashboard/email and restore/private-access proof against the saved M0–M6 acceptance gates.

The successful SDK spike is scoped to its actual TestModel/tool checkpoints and transactional enqueue, not integrated company execution or paid provider conformance. Verification candidates are not verified business outcomes. No live provider, customer/owner message, Pi service change, production migration, Git push, tag or deployment occurred in this wave. The active goal remains incomplete.

## Current closure wave — 2026-10-14

The dated integration paragraph above is historical package progress. Current checked additions:

- Normal company001–007 migration lineage has **17 tables**, including immutable known-receipt billing evidence. Fresh/repeat/metadata/downgrade acceptance passes; the populated old-lease migration separately refuses live leases and fences expired leases without refunding unknown costs.
- Execution and recovery pass **30 PostgreSQL cases**. Lease principal is explicitly actor or current owner; false-owner membership cannot claim or spend. Owner reconciliation records already-issued facts without issuing another effect or completing work.
- The actual offline company DBOS worker passes **7 process cases**, including SIGKILL after intent, protected output and receipt. Same-dispatch recovery preserves counters and avoids a second model request. Integrated compatible-version acceptance is being added; the separate SDK spike does not substitute for it.
- Persistent per-request model authorization passes **52 checks** (19 unit, 33 PostgreSQL/offline SDK). It validates exact request/recipe/catalog/price/input bounds before committed intent, preserves returned evidence after fencing, and records known costs or retained unknown billing. Known overrun blocks further work; actual cost is never clamped to the quote.
- Current-owner billing reconciliation passes **17 PostgreSQL cases**, using exact protected invoice observations and original price versions. It records immutable billing provenance and leaves known effect receipts, work status and attempt counters unchanged. Live billing resolvers are not enabled.
- Whole unit regression before the unfinished client wrapper passes **692 tests**, with 19 existing warnings. The wrapper, final whole-tree checks and independent combined M1 review remain in progress; overlapping package counts are not summed.
- The original 30-question Brain fixture is unchanged. Its separate synthetic source/golden pack is frozen before retrieval implementation; no score or real company truth is claimed. See [M2 implementation plan](BRAIN_IMPLEMENTATION_PLAN.md).

The PostgreSQL CI matrix now includes terminal-receipt and governed-client files. Its configuration is local; no remote CI execution is claimed. Evidence is under `/mnt/data/nexus-implementation-evidence-2026-10-14/` and the prior dated folder. The M1 closure below supersedes that earlier pending state; the next concrete gate is Brain schema/current ACL and source/retrieval acceptance. Model-backed ingestion, new intake and paid provider activation remain gated.

### Offline M1 closure and M2 ownership

The latest [M1 acceptance](M1_OFFLINE_ACCEPTANCE_2026-10-14.md) closes the offline runtime exit. The complete worker package passes56 checks, including10 actual process/database cases; incompatible-version and pending-approval→segment2 proof are included. Governed client32 author checks and post-cap21 database/SDK checks pass. Whole unit703 and mypy330 were checked before separately prepared Brain code. The combined reviewer approved offline scope after reproducing and rechecking ERROR-049/050; generic daily/own/ancestor caps now guard all fresh tool/model intents. Enqueue/day14 and three retained effect-cap negatives pass.

[Committed StockFlow nomination](STOCKFLOW_SOURCE_MANIFEST_v1.json) fixes bb7cc00848bb650069543e843f826703d468058c and five Git blobs; dirty working-tree changes were excluded. This is an implementation source choice within the authorized pilot, not external action/deployment authority.

M2 uses four disjoint lanes: model worker owns shared strict contracts/metadata; replay worker owns deterministic source/blob/parser/ingestion/outbox; planner owns permission-filtered retrieval/context; root owns current locked scope/ACL, migrations, API and acceptance integration. Mandatory server context byte limits and data classification are frozen; unqualified read-only rendering cannot claim token allowance. Actual model use still requires M1's full-input estimator/profile/recipe and current USD gate. No Brain migration or score is claimed from source preparation.

The later [M2 integration checkpoint](M2_INTEGRATION_2026-10-14.md) replaces that source-only state with actual company00843-table install/compare/downgrade, access7/guards5, ingestion36, retrieval20, model-context28/default108 and whole unit847 evidence. Full30-answer acceptance is still open; natural-language model quality and production operation are not inferred. A fresh API/evaluator worker and independent combined reviewer now handle those lanes; root still integrates shared release gates.

### M2 reviewed foundation checkpoint — 2026-10-14

Five independent production findings are reproduced and closed; root retained
ACL/schema13, context-model30, shared execution33, default model45, client21
and real DBOS worker10 checks pass. Optional company-app integration7 and normal
43-table profile proof pass. Whole current unit847 passes with19 existing
warnings. Strict changed-package types pass; full thin-profile strict traversal
reports10 absent optional legacy SDK imports, with existing CI type semantics
recorded separately. Original30 source-derived answer score is17/30 with14/16
critical: M2 acceptance remains open. Preserve its first matrix and improve
generic production/capture handling without relaxing source/golden criteria.
M3 planning can proceed independently; management activation still depends on
the accepted M2 gate. No full release or live-model quality is claimed.

### M3 local preparation — 2026-10-14

[Management implementation plan](MANAGEMENT_IMPLEMENTATION_PLAN.md) selects
atomic bounded DAG registration, explicit independent acceptance, deterministic
eligibility and truthful reporting/views. Separate DTO/metadata preparation and
the same-session registration bridge are in progress. This does not enable
management or close M3; M2's original answer gate still fails17/30,14/16critical.

### M2 offline exit — 2026-10-14

[Offline acceptance](M2_OFFLINE_ACCEPTANCE_2026-10-14.md) records second29/30,
all16critical, independently recomputed fromall30hash-verified observations.
First17/30 remains unchanged and B06 remains a visible second-run failure.
Native source/ACL/publication/context/SDK and nominated actual product-source
evidence complete this offline milestone; live LLM quality/business completion
and M3–M6/full release remain unproven. No execution activation accompanies it.

### Current M3 preparation — 2026-10-14

Owner transaction6realPG4.18s and independent pure report checker55unit0.88s
pass, with scoped strict/lint checks. DTO/native22-table declarations and pure
eligibility/report rules are being finalized. These remain uninstalled and
unactivated; no trusted acceptance publisher/scheduler/management UI or complete
internal operating workflow is claimed. Root next integrates normal009 with
forcedRLS/immutable guards, actual fresh-profile proof and owner control stores.

### Reviewed M3-A checkpoint and scheduler schema — 2026-10-14

Independent review approves only owner controls/goals/schema after ERROR-058:
original goal-grant expiry reproduction1pass4.48s; retained expiry plus20stores
21pass26.55s. Complete current artifact slice/reference revalidation7PG12.91s.
Normal company010 adds one immutable scheduler receipt, while namespaced existing
cursors track Brain/control offsets;66-table fresh/repeat/metadata/downgrade
1PG1.82s,23table forced policies/current/history guards7PG6.24s. Scheduler
services and real dispatch/process recovery remain separate active work.

Production report input loader binds complete protected UTF8/hash/citations and
native author registration, with no owner impersonation or blob I/O under the
mutex.22unit0.88s and strict3/lint pass; its mandatory actual operating report
reader is pending. This does not claim a full production report flow. Plan and
publisher workers continue their boundary tests. M3–M6/release goal stays active.

The selected closed checkpoint146unit1.59s, strict50source files and Ruff54files
passes together. This excludes actively written plan/publisher/scheduler services
and shared runtime delta; a whole evolving-tree gate is still pending.

### Managed gateway and final acceptance permission — 2026-10-14

Root trusted management service composition now reaches the existing exact
model-request gate. Actual public owner/goal/approved-plan/M1 action/lease plus
SDK MockTransport3PG9.59s proves one configured wire request and actual known
billing; missing services/revoked mandate produce zero requests/attempts.
Original gateway45unit/PG38.90s remains green. This is offline SDK conformance,
not live-provider or report-worker qualification.

Root independently reproduced final input source grant expiry during acceptance
outbox write (ERROR-059); unchanged probe closes1PG8.83s. The protected result
and all input contributor expiries are now checked at final timed boundaries.
Retained probe plus full C matrix28unit/PG96.41s, strict6/lint pass. C's original
freeze27/18PG is retained as historical before this delta. B's frozen41PG101.80s
and13unmanaged11.88s are scoped approval/guard evidence. Combined review remains
in progress; native reports/scheduler/cancellation/commitment/UI and full M3
procedure are incomplete. Protected report ABI now passes exact outputRef to the
mandatory native reader so verifier sharing cannot rely on a declared reportId.

### Frozen management core integration — 2026-10-14

Frozen treee2fbebd62c3542fea59f94662e9ac7da1b41262f at the isolated task snapshot
contains the prior718fe91 plus40 explicit B/C/Root gateway/API files. Whole unit
1015pass13.62s with19 existing warnings, strict40/Ruff40/format40 pass. Original
model gateway45unit/PG33.22s passes after the final temporal hook; owner HTTP/API
plus auth41checks9.59s (3actualPG +38unit) pass. Snapshot excludes actively written
scheduler/report/cancellation/view packages, so this is a coherent core gate,
not the whole evolving source tree or M3 exit.

Independent review approves the corrected offline C/mock gateway after original
price1PG6.83s, replaygrant1PG14.57s and inputcommitgrant1PG8.94s. Retained price+
normalgateway4PG11.95s and replay/finalgrant/publication7PG47.29s pass. Root now
has literal-number-safe current signed-owner optional mandate/charter/goal/plan
publication and exact approval/revocation HTTP routes; they admit bounded work
but start no execution, scheduler or provider. Default company intake remains
disabled. Numeric revision/CAS tests and unknown baseline/date retention are real
HTTP cases. Source40manifest and independent review2 retain exact scope/hashes.

Scheduler D freeze separately19checks65.21s (5unit/14PG including realDBOS
OSkill/restart), strict15/Ruff/format is ready for next boundary review. Its process
proof is claim-only, not a report/effect/acceptance completion. Native report store
is being built with explicit selected-work-lifetime ledger basis and current
protected output/verifier sharing; owner day totals are a separate live ledger.
Authoritative cancellation + commitments/owner read views are separate ongoing
packages. Full native research/report workflow, UI, M4–M6 and release remain.
