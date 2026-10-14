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


### Native cancellation and artifact input checkpoint — 2026-10-14

Owner cancellation and additive011/012 artifact input permissions are ready for a local
checkpoint. [Evidence and limits](M3_PROVENANCE_CANCELLATION_CHECKPOINT_2026-10-14.md)
retain independent original failures and the six unchanged passing ancestry probes.
Root artifact/target10PG37.81s and existing Brain17PG103.84s pass. This does not
qualify the in-progress native publisher/DBOS report procedure or complete M3.
Native report preparation/check preparation2PG32.52s and scheduler cancellation plus
existing scheduling8PG58.28s are separate active integration evidence. Owner UI/action
review and actual private/dev session composition continue with the bounded workers.


### Native report/recovery and owner UAT integration — 2026-10-14

Root new native report worker executes deterministic registered report/check tools with
actual configured actors, dispatch/fences, current compilation before intent, native
artifact publication, actual receipts and separately trusted acceptance. First fresh
check1PG30.95s proves one tool attempt/zero model requests; full-pin known receipt
recovery/replay and wrong selector cases3PG89.99s pass. These are native service/step
checks, not the still-pending actual DBOS process kill/restart qualification. Root
acceptance recovery accepts only an actual succeeded verifier check action ID; full
current target/protected bytes/source/permissions and production input/output/recipe
pins are independently recomputed. No pending blob or cached permit grants success.

Independent review reproduced a final action approval expiry gap during actual intent
flush. The intent now retains exact/standing authority expiry alongside lease/source/
recipient/profile windows for the final pure clock. Original failing probe is retained;
unchanged corrected probe is pending at this write. Profile expiry probes2PG51.20s and
pending-blob/forged-or-revoked-scope/reconcile-lease expiry3PG84.38s pass. This does not
claim the whole worker/release review has finished.

Owner backend API7PG53.53s and frontend build/four actual-client identity race checks
are frozen; actual member login correctly denies owner content. Actual loopback UAT
API9188 and frontend5188 expose task-only signup/login and native current company,
plan, action/commitment/receipt/held-unknown-cost facts. No providers/workers/business
acceptance were activated. Owner browser flow awaits the human password step; the
browser page is handed over and remains untouched. SDK TestModel smoke1request,
no tools/retries and2/2 exact conformance checks backs a named UAT-only4h profile,
not live-provider quality. Runtime OpenAPI tuple/money response correction has1unit
pass4.34s; source import errors during restart are retained as failures, then corrected.

Read-only M4 Pi preflight found ARM64 Debian13/Python3.13.5, no Podman/crun/uidmap,
and cgroup_disable=memory in boot arguments. Required4GiB sandbox enforcement and
ARM64 qualification remain unproven; agent prepares a concrete setup/rollback packet
and local native-builder code. No Pi mutations or service repairs were performed.


Independent final authority repro closes unchanged:2PG45.07s including the separate
pending-blob cost conservation confirmation. Root source snapshot2 SHAe29b5415ba7e346714a8e817bbd9477dbf0dd709cc17464555956514e85bbfb3
is under review; the final combined six-case matrix is running. No actual DBOS
process completion or full M3/release claim follows from those finite probes.


### Actual native durable process qualification — 2026-10-14

Actual owner scheduler→DBOS native workflow→check publication/receipt→OSkill
before acceptance→same executor restart→trusted acceptance→SDK completed replay
passes1restrictedPG85.66s. Retained proof SHAfd34027251718469a43b8587ef4e582b09f208f5d802188e2739c2b9736cb402:
`native-workflow-process/kill-after-check-receipt-proof.json`, SDK SUCCESS with2
recovery attempts. One tool attempt, zero model requests, same segment/run and
one acceptance row; original reconciled native charge0 preserved. This scope is
an offline source fixture and native check workflow, not live-provider/customer
readiness or the remaining intent/artifact/acceptance interruption cases.

Original process run first reached the actual receipt phase but fixture assertions
used incorrect ORM names (22.43s failure). Corrected test then reproduced a genuine
restart timeout (125.55s): the worker used a random process-specific DBOS executor
identity. Pinned DBOS3.2 recovery code and official workflow recovery documentation
show startup recovery selects that executor. Native services now use an explicitly
configured executor identity, stable across restart and unique per logical host;
M1 worker UUID/fence still changes. Recovery wait covers M1 maximum300s leases
with a finite310s observation bound instead of30s. The expanded four-phase actual
OSkill matrix is running; its result is unclaimed at this write.

Fresh dispatch recovery now calls current configured management admission before
new fence/segment/execute capacity is allocated. Original public-plan revoke probe
failed1PG8.64s; unchanged corrected probe plus known-issued reconciliation positive
passes2PG25.99s. Independent eight-case restricted-PG worker boundary review passes
(six122.92s plus two25.99s), with original failures retained. Known issuance remains
reconciliation-only and costs/attempts are not reset.

Actual live JSON/YAML response-schema probe now parses port9188 safely and matches
13 exact response roots after reload. YAML Python tuple tags were independently
reproduced and removed through the actual JSON serializer normalization. Root full
Brain+management schema unit1pass3.31s. No user credential entry was automated.


Expanded native DBOS four-phase OSkill/restart matrix passes4restrictedPG332.32s:
intent, artifact publication, receipt and acceptance. Missing published output stays
unknown with its reservation; preserved native output/receipt/proof resumes without
another tool/model attempt, segment/run reset or duplicate acceptance. Actual phase
proofs/config/observations are retained in native-workflow-process/four-phase with
hash manifest. Pure composition split keeps helpers42/35/18lines and strict/lint
passes; no authority semantics changed. M3 measured observations, operating profile,
owner browser and coherent full-source integration remain open.

### Verified continuation — 2026-10-14 06:06 UTC

Local commits ce53345 (native builder),17cb8c8 (owner report dashboard) and
1338684 (native event015 schema) are integrated. Builder recovery privacy issue
is independently closed by its unchanged PG probe; combined74 checks and stable
1291unit pass. Owner report controls build and pass18 client/input checks plus4
session races; backend composition/schema6unit pass. Separate visible synthetic
preview verifies unknown billing, acceptance separate from receipts, and exactly
one uncertain snapshot POST. Human sign-in remains handed over and untouched.

Normal015 schema12PG+2unit and separate install/reflection/downgrade1PG pass;
stable1315unit pass.008/014 event SQL and014 ingestion compatibility are scoped
separately from a pre-existing008 artifact read gap.50 configured CI groups
resolve staged paths; remote CI unrun. Real decision/block/cap/digest emitters
and failed-receipt production wiring remain required. Frozen native draft store
4PG+6unit awaits integration; new M1 dispatch has one actual-owner/public-M1/mock
POST positive so far, without a full negative/recovery matrix or real mail.

Public pnpm tiny offline CAS passed. A long-name archive issue was reproduced
and corrected before full cache launch. Amended exact517-package download/offline
import completed within fixed local bounds:517 downloads193,711,174bytes40.81s,
offline import26.22s, store677,763,226bytes and streamed GNU archive725,964,800bytes.
Qualified extraction has26,721files with bounded normalized metadata. Actual
post-extraction pnpm resolution/status and representative project checks remain open.
Representative StockFlow/ARM64/engineering acceptance, live provider/email,
private deployment/backup/restore/rollback/soak and final approval remain open.
The full supervised release goal stays active.

### Verified continuation — 2026-10-14 07:48 UTC

New local checkpoints bfc0539 and a5548bd commit genuine failed-receipt/private
draft integration and disabled governed notification dispatch. Actual failed
process→one native wake→current licensed owner draft passes, with same-transaction
outcome/cost/event rollback and independent review. Root12PG67.33s, independent
4PG23.65s, original unconfigured M1 execution13PG31.52s and stable1321unit32.96s
support that receipt checkpoint. Source-revoked/paused already-issued outcomes
remain recordable; later protected body disclosure is independently checked.

The dispatch checkpoint passes corrected coherent13restricted pinned014PG237.40s,
stable1321unit24.61s and strict20. Independent post-intent target revocation exposed
ERROR-072, then closes unchanged1PG17.99s. Current target and actual configured
managed admission are rechecked before HTTP; acceptance/delivery/unknown billing
remain separate.53 CI groups resolve index paths; remote CI unrun. Lower-level
sender tests are explicitly unmanaged owner conformance. Actual managed preparation,
new-kind drafts/digests/atomiccursor and worker/API/dashboard integration continue.

The first actual nominated historical StockFlow sandbox run installed offline and
passed web typecheck, then stopped at test startup EAI_AGAIN localhost. No build or
post commands ran; one native failed receipt and protected summary are preserved
with toolattempt1/model0 and unknown billing. A test-only collector PK error was
corrected without reexecution. Node-only static localhost mapping is being tested
as a changed harness condition; a later action must use genuine remaining approved
parent slices, preserving the first action/receipt/holds/counters. This is not current
customer readiness or an accepted engineering change. Current business evidence,
live providers/email, ARM64/Pi memory controller, private deployment/recovery/soak
and final approval remain open. Human signup and owner email information are pending;
no credential entry, live send, device change or deployment occurred.

### Checked2026-10-14 — Native notifications and bounded build integration

Local feature/company-foundation now1c03990. Existing governed owner sender5d4739b,
current eligibility53d86c5, offline Node/cache0aa46df and qualified native drafts/
atomic cursor1c03990 are committed. Latest coherent1414unit56.37s and independent
6restricted015PG98.58s/strict26 pass; prior Node gate1403unit75.74s/strict42 is
scoped to its49-file package.58 CI groups resolve index paths; remote CI unrun.

Actual unchanged nominated historical StockFlow v2 baseline install/typecheck/test/
build passes; postbuild hits provenENOSPC under the same2GiB scratch. One native
failed receipt/process/attempt and unknown billing remain. Proposed v3 removes only
completed baseline copiedscratch while retaining evidence/caps; actual unused
verifier is denied over failedauthor. Genuine remaining sameparent newpair/second
revision/freshchecked model/source/newexactprivatepacket remain required. Generic
runner remains frozen; new phase capture stays Node-specific.

Qualified decision/block/cap/digest drafts, licensed obsolete reads and draft/link/
cursor final checks are integrated. Owner inbox API26case freeze and optional Root
mount/schema7units pass in scope; independent revoked-anchor→empty200 metadata gap
is being corrected with all queried IDs/recipient pins/deadlines and total<=9.
No sender or timer is activated; digest dispatch quota specialization remains open.

Owner inbox11filefrontend patch is reviewable and gitapply-check green in external
notifications/owner-inbox-ui.patch (SHA4bf85aa0...). Exact mounted schema/types,
3GETclient+4session checks and finalbuild69s pass. Separate synthetic preview proves
accepted submission retains unknown delivery, plain escaping, refresh404 hides body
and mobile320/360 fits after headerwrap. Primaryfrontend stays untouched while the
human signup page is held; temporary5314 servers/tabs are closed. This is UI preview,
not actualowner signup or native provider acceptance/delivery.

CurrentStockFlow readiness/BrainB06/liveprovider quality and owneremail/ARM64Pi memory
controller/privateaccessbackuprestore/rollbacksoak/finalapproval remain open. Goal
active; no push/tag/deploy/liveemail/provider/Pi changes. Verified model-observation
procedure was saved reversibly in the Nexus skill with exact evidence and limitations.

### Checked2026-10-14 — Successful bounded build and recovery format

Local81d0256 follows Nodev3 integration8dcc625 and digestquota250bb9a. V3 actual
nominated unchanged StockFlow baseline/post all8commands exit0/252.422s, one native
process/attempt, actualcaps/protectedoutput/cleanup verified. Billing unknown and
work verifying; the report-only verifier cannot publish code acceptance. Root
1438unit30.44s/strict22 plusworker5PG75.41s and independentcleanup/capture review
support that mechanical scope. Native engineering contract/independentproof and
currentCSV correctness goal nowdesigned separately; no oldparent/revision reset.

Native daily/weekly slots nowretain exactkind/window/policy andonepercompany/bucket
permanently, separate fromroutinecap. Root3privacy/finalflushPG102.38s, coherent
1443unit37.86s/strict15; worker9PG31unit+additional2PG retains originalfailures and
unknownholds. No liveemail/timer/worker activation.61CIgroups resolve pathsremoteunrun.

Encryptedbackupcodec/privatefiletree committed81d0256:28focusedunit0.71s, coherent
1482unit43.23s/strict8. Independenttargetreplacement probe originallyfailed0.35s,
thenpassedunchanged0.26s afterFDanchored writes. Typed directrestore aggregatecap
alsoenforced. Directcryptography49 pin changes no packageversions. This is bounded
codec/pathproof, not matchingPG/DBOSrestore orindependentstorage; thoseactualdrills
arethenextapprovedoperator-localimplementationplan. No prodkeys/DB/Pi/UAT changes.

Currentmodelobservationsatactualgateway areinprogresswithoriginalregistry/request
identities preserved, preSDKcurrentchecks and protectedprovenance; first2actual
normal015 mockSDK/nativebilling casespassed. Fullclock/revoke/version boundary
packagepending. Human signup/owneremail andARM64/privateoperatingrelease gates
remainopen; frontendinboxpatch staysisolated, previewsclosed. Goalactive.

### Checked 2026-10-14 — Isolated native engineering admission

Root's [native profile plan](NATIVE_ENGINEERING_PROFILE_PLAN.md) now has an
eight-file implementation in an isolated snapshot based on a1adec7. The active
shared admission code is unchanged while the gateway agent finishes its package.
The explicit profiles bind an exact registry digest and workflow, a closed
engineering author/verifier pair, seven criteria, and zero model quota throughout
actual immutable ancestry. Model requests are denied; current charter, approval,
source, lease and budget gates remain in force. No model-health evidence is invented.

The snapshot passed 1,501 unit tests in 34.16s (19 existing warnings), 9 restricted
normal015 PostgreSQL cases in 19.69s, strict types on 8 files, and Ruff/format.
The original test-first missing-module result and a mistaken quota-mutation fixture
are retained. PostgreSQL correctly rejected that mutation through its immutable
registration trigger; the corrected test preserves this safeguard, and a separate
publicly registered positive ancestor demonstrates the native guard's denial.

Source manifest: native-builder/native-profile-freeze-1.json, SHA
de4f0a030947a719a6dc294303c0d1f02caff4132da9d63b892c8c8eb39902bf under the
dated implementation evidence directory. Independent review and integration are
pending. Actual CSV module regression, patch, independent process and engineering
acceptance remain required. The reduced no-mount JavaScript probe establishes the
malformed quantity semantics only.

The release still needs genuine model quality, current StockFlow business evidence,
owner setup/email, ARM64 sandbox qualification, private deployment, matching
database/DBOS recovery, independent backup storage/key custody, rollback and a 24h
soak. Gateway and operator-local recovery implementation continue in parallel.
