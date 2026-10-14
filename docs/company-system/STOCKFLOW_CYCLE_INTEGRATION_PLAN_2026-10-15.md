# StockFlow: one goal, one permanent allowance, one traceable readiness cycle

Source review: 2026-10-15 Asia/Bangkok, Nexus `e8f5113`. **Proposed ABI only.**
Amendment5 pins the pure matcher to explicit admission/registry/payload inputs,
with no dependency on an unimplemented catalog field. It retains the staged-head2
revalidation requirement and exact ownership boundary. Earlier plans remain
retained unchanged; StrategyBrief replaces the old quote-dossier proposal.

No DB query/setup, SDK/job/process activation, StockFlow write, source refresh,
model request, email, Pi or deployment occurred in this planning task.

## Result and next slice

Implement an opt-in, server-owned mixed-cycle admission configuration first.
Keep the existing two-child engineering and one-child notification profiles
unchanged when this configuration is absent. One new measured goal retains one
permanent procedure, a strategy pair, the native engineering pair, presentation
and support pairs, an owner-report pair and one finite staging sender. Ordinary
children continue through existing model/catalog/health/charter validation.
Native children cannot consume the ordinary siblings' model allocations.

Do not assemble a supposed full cycle by relabelling old passing fixtures.
Their goals, consumed allowances, source dates, failures and unknown holds stay
historical. Mechanical synthetic composition and actual private StockFlow
operation must have separate receipts and completion claims.

## Source findings that constrain implementation

| Existing boundary | Consequence |
| --- | --- |
| `native_execution_profiles.require_native_plan` requires exactly two native children, seven engineering criteria and one edge | A combined plan is currently denied; simply adding ordinary tasks is insufficient. |
| `native_profile_checks.require_zero_model_ancestry` requires every ancestor's model limit/used/delegated to be zero | A mixed root with ordinary model slices is currently denied at actual execution even if plan admission changes. |
| `native_profile_checks.require_notification_plan` requires one sender child and zero-model root | A sender in the same mixed plan needs an equally explicit closed composition rule. |
| `plan_registration.ensure_procedure` permanently fixes one root per goal | New plan IDs/revisions cannot provide replacement USD, quotas, run or parent. |
| `ManagementPlanStore.current_binding` selects the latest approved plan across that goal | A later separate report plan excluding engineering makes earlier work noncurrent. Retain every earlier child in the full plan. |
| `VerificationSpec` binds author/verifier `RunBinding`, registration hash, receipt, artifacts and criteria, without a plan-reference field | Same unchanged pair may remain current across a plan revision; actual artifact/proof provenance and current accepted projection still need a real test. |
| `render_native_report` emits exact source quotes and accepted-work identities in `StructuredInternalReport` | It is useful for the final operating report. Its saved report selection must match the current plan in operating_report_author.py:38 / operating_report_sharing.py:51; a rev1 saved report cannot be assumed current after rev2. It does not implement strategy/customer/presentation semantics. |
| Native metric recipe is `native.accepted-report-count.v1` | It cannot count engineering/presentation/support acceptance as product readiness. Preserve unknown for unsupported metrics. |
| Notification selectors are decision/blocked/cap/failed-receipt/digest; no generic success selector | A final-success email cannot be invented from a workflow return. Use actual pending-decision staging or the real due digest path. |

The SDDv0.2 §3, IMPLEMENTATION_PLAN M5/PILOT-01 and RELEASE_GATES_CURRENT still
require a full lineage and actual artifacts. This plan does not close M4 ARM64,
live model quality, customer readiness, live email, owner browser, private access,
independent disaster recovery, soak or release publication.

## Exact input basis

The immutable nomination remains `STOCKFLOW_SOURCE_MANIFEST_v1.json`, SHA256
`355ea24003691b33ca1ddc0a7eec2260ebebef15ab6609470613cf163f997b3e`:
commit `bb7cc00848bb650069543e843f826703d468058c`, tree
`e0ed0e5618d3dda4d0cde0fd2cdc5642a99c8ac2`, event time
`2026-09-01T13:56:41+07:00`. Read-only Git-object checks in this review matched
all five listed blobs, SHA256s and lengths. No dirty checkout files were read.

The manifest names README, root package/lockfile, web package and release notes;
it is **not** the complete CSV job input manifest. Additional committed-object
observations, not amendments or execution proof:

| Path | SHA256 | Bytes |
| --- | --- | --- |
| `packages/shared/src/csv/index.ts` | `e1bc9d8dc77ceac370e8790d4bf7dc7126f5693ae37c0866eb9538f084610483` | 5432 |
| `packages/shared/src/csv/csv.test.ts` | `740714d0caff2cc2454694de11afa09e7577cd0af673cf22ba7226c6677e09a9` | 2770 |

Before a real job, freeze the full committed tree, exact two-file candidate patch,
baseline/post module and test bytes, complete shared/web test discovery, CSV
mapping/wrapper, Node/pnpm/Vitest versions, offline cache, image, recipe, tool
policy, containment method and output bounds. Existing Nodev4 and contained
runtime qualification are prerequisites, not replaceable by this source table.
The old failed StockFlow jobs and public CSV fixtures are not this new goal's
author/verifier evidence.

Owner inputs for this new lineage: a precise CSV quantity-readiness checklist,
selected improvement and excluded scope; current mandate/charters; an explicit
USD/attempt partition; current model registrations/prices if any model is used;
private source/output/proof permissions; configured current identities; and exact
action decisions. A nominated committed baseline does not prove current deployed
StockFlow or customer readiness.

New source ingestion later must preserve the September commit event date and
record its actual qualification clock under an explicit policy. No old head,
approval, observation or registration is renewed. Staleness during the cycle
blocks further fresh publication; it does not permit a timestamp rewrite.

## One lineage and finite DAG

All task/trace/run IDs are new, permanently selected once in a reviewed packet.
One company/workspace, goal revision, mandate and fixed procedure bind both plan
revisions. Actor IDs resolve from current membership; author and verifier differ
for every pair. An actor may verify another department's work, never its own.

1. Owner approves revision1 with strategy evidence author S and verifier SV only.
   The root already declares the *entire* lifetime allowance below. S produces a
   typed StrategyBrief with cited findings, candidate actions, tradeoffs, bounded
   recommendation, unknown/deployed limits and required owner decision. SV
   independently checks that explicit brief contract. Producing planrev1
   remains immutable provenance. This is not a live-model strategy-quality claim.
2. Owner reviews the dossier and selects the exact improvement. Revision2 of the
   **same plan** retains S/SV registrations, allocations, charters, edge, criteria,
   output/proof identities and root unchanged, then adds the remaining slots.
   The existing administrative counter consumes exactly one plan-revision slot.
3. Engineering E waits for current independent S acceptance and exact owner plan
   and action decisions. EV is triggered by E's actual succeeded output receipt,
   then independently runs the reviewed patch/check recipe. EV is a trigger edge,
   not a dependency on E acceptance (which would be circular).
4. P and C wait for actual current E acceptance. Their distinct verifiers check
   protected typed presentation/support bytes, sources and truthful limitations.
5. R waits for current S, E, P and C acceptances. Existing native report producer,
   independent RV and trusted publication produce the final operating report.
   The dashboard separately shows full current root/child ledger and exceptions.

| Slot | Workflow/profile | Dependency / check trigger | USD slice | Model/tool maxima |
| --- | --- | --- | ---: | ---: |
| S | proposed `company.cycle.artifact/v1`, ordinary `reasoning` | none | .08 | 1 / 1 |
| SV | same workflow, ordinary `verification` | exact strategy check S | .06 | 0 / 1 |
| E | `engineering.change/v1`, `engineering.native.v1` | accepted S | .20 | 0 / 1 |
| EV | `engineering.verify/v1`, `verification.native.v1` | exact native check E | .20 | 0 / 1 |
| P | proposed `company.cycle.artifact/v1`, ordinary `routine` | accepted E | .08 | 1 / 1 |
| PV | same workflow, ordinary `verification` | exact presentation check P | .04 | 0 / 1 |
| C | same workflow, ordinary `routine` | accepted E | .08 | 1 / 1 |
| CV | same workflow, ordinary `verification` | exact support check C | .04 | 0 / 1 |
| R | `internal.report/v1`, ordinary `routine` | accepted S, E, P, C | .10 | 0 / 1 |
| RV | `internal.report/v1`, ordinary `verification` | existing report check R | .04 | 0 / 1 |
| N | `internal.owner-notification/v1`, `notification.native.v1` | finite exact owner staging profile | .04 | 0 / 1 |

Proposed root: USD1.00, model3/tool11/rework0/plan-revision1; child USD sum .96,
all child rework/revision0. These are finite **proposed maxima**, not invented
usage or known prices. A priced model request must fit its child's remaining
slice including publication cost; otherwise it blocks. Mechanical fixture runs
may leave the three model slices unused. Ordinary zero-model-quota tasks still
need full existing profile/health/catalog validation. The nonexecuting root uses
one fixed ordinary binding and remains denied by `managed_kind == procedure`.

N initially stages a real `decision_required` draft for R's exact pending action,
with no approval/hold/dispatch/POST for N. It has no accepted-R dependency that
would deadlock that preapproval notice. After R is approved, retain the draft's
actual obsolete state. This proves review staging, not a final-success digest.
A final digest requires an exact current saved report and real Bangkok09 due
bucket; before that time the correct result is quiet. Daily-positive qualification
and configured delivery remain separate gates, with no fake due clock.

## Concrete proposed admission ABI — implement this slice first

New `company/management/cycle_admission_contracts.py`:

- `StockFlowCycleSlot`: fixed role, exact `RunBinding`, charter ref, USD/quota,
  criterion tuple, approved tool/version/resource tuple and dependency/edge pins.
- `StockFlowCycleAdmission`: company/goal/plan IDs, immutable `ProcedureRoot`,
  registry revision/digest, exact eleven slots and the closed revision1/revision2
  layouts. Strict bounded values; it grants no identity, permit or acceptance.
- `StockFlowCycleSelection`: descriptive matched stage/native task IDs only.

New `company/management/cycle_admission.py`:

`validate_stockflow_cycle(admission: StockFlowCycleAdmission | None,
 registry: ModelRegistry, payload: PlanPayload) -> StockFlowCycleSelection | None`

The first pure matcher validates the explicit admission object, full exact
registry revision/digest and payload; it does not pretend the future catalog
field exists. No getattr/dynamic mock-catalog shim. Root later passes the optional
shared catalog field into this API and validates the actual complete configured
tools/profiles/resources through existing gates. Pure match is not that proof.

Match the entire configured layout, all children, original root, exact native pair,
seven engineering criteria, each verifier edge and DAG. No extra native/model/
sender slot, ambiguous role, duplicate selection or caller flag. Every ordinary
child subsequently runs unchanged existing validation. Exact serialized catalog
bytes/digest include the server configuration; avoid a self-referential digest.

Keep exact role/edge/stage/partition comparisons in the two NEW pure modules
`cycle_admission_contracts.py` and `cycle_admission.py`, with focused pure tests.
This is the complete first source-only scope. Contracts import primitives/plans
only; catalog types use TYPE_CHECKING to avoid runtime import cycles. Pure input
descriptions confer no actual native authority.

Later Root-owned SQL integration: `execution/cycle_partition_checks.py`,
`require_cycle_partition(session: AsyncSession, work: ExecutionWork,
 catalog: PlanAdmissionCatalog, child: ChildAllocation) -> None`.

Only a fully matched mixed layout can replace the root-zero-model condition.
Verify the actual native leaf's immutable model quota/limit/used/delegated remain
zero, exact company/parent/root registration and all actual sibling allocations
match their permanent slots. Deny intermediate/foreign/hidden children or replaced
roots. Preserve existing runtime counter/delegation semantics rather than invent
a new arithmetic ledger. A positive ordinary-root model slice never grants a
native leaf access to it; model kind/tool calls still hard-deny.

Narrow shared seams to propose before edits:

- Actual definition `management/plan_catalog.py` (plan_support only reexports):
  `PlanAdmissionCatalog.cycle_admission: StockFlowCycleAdmission | None = None`,
  excluded when absent; old catalog wire bytes and defaults remain identical.
- Closed mixed-layout branches in `require_native_plan` and
  `require_notification_plan`, while all `validate_plan` actor/governance/source/
  charter/tool/profile/edge/final-clock checks still run. No broad bypass flag.
- Engineering/notification ancestry functions call the new partition gate only
  for the exact configured mixed family; all old paths retain zero-model ancestry.
- Same-transaction revision2 transition gate resolves actual original S receipt,
  proof and `current_accepted_work` before consuming/registering the revision.
  Revalidate again **after** assigning/flushing the staged current revision2 head
  and registering its children, before commit: actual current accepted-work
  projection plus the new StrategyBrief reader/checker must still resolve the
  exact original output/proof/source closure. The metadata acceptance projection
  alone does not rerun report/strategy semantics. A failure rolls back head,
  decision, revision counter and every new registration/delegation together.
  If a reader dependency is required, add optional constructor-only
  `cycle_artifacts: BoundedArtifactReader | None` to `ManagementPlanStore`; missing
  configured reader/freshness denies, rather than treating supplied DTO as proof.

No schema, HTTP body, `current_binding` latest-plan semantics, root registration,
quota/refund semantics, native seven criteria or generic claim-mode changes.

## Subsequent source integration, after admission review

S requires a distinct `StrategyBrief` contract, not a renamed quote dossier:
company/goal/producing-plan/work refs; findings with claim kinds and exact evidence
spans; bounded candidate actions with patch/tool/scope pins; explicit tradeoffs;
one bounded recommendation referencing those candidates; unknowns and deployed
readiness limits; and the required owner select/defer decision. This last field
is a decision request, never a fabricated approval. Revision2 actual owner plan
decision and the later exact engineering action decision record the real choice.

Proposed independent interface:
`StrategyInputReader.resolve(scope, identity, author_action_id) -> StrategyCheckInput`
resolves the unique actual receipt, protected StrategyBrief bytes, original work
and full current source closure. `check_strategy_brief(input: StrategyCheckInput)
-> StrategyCheckResult` recomputes schema, citation bytes/dates, closed candidate
scope, recommendation/candidate consistency, tradeoff/unknown representation and
absence of unsupported deployed/customer claims. It cannot certify economic or
strategic merit. Only the separately authorized protected checker/publisher and
real verifier receipt can append WorkAcceptance, with those limitations.

The owner review projection for revision2 must expose that exact original brief
and selected candidate before its decision. The same-transaction transition gate
resolves the unique immutable S receipt/output and exact server-fixed candidate;
it cannot pick latest or accept a supplied brief/hash. Existing plan request DTO
need not change for the admission slice; if actual owner-review/selection binding
requires a typed payload amendment, propose it to Root before editing rather than
hiding provenance in a title or treating operator config as owner approval.

P/C need a bounded `CycleArtifactPayload` with closed phase
`presentation | support` and exact
goal/plan/work/source/acceptance refs. Fixed presentation template: demonstration
steps, verified CSV behavior, source dates and deployment/customer limitations.
Fixed support template: hypothetical CSV case, cited supported behavior, unknown
deployment state and owner escalation. No fabricated customer ticket or send.
New producer/checker/publisher must re-resolve actual protected E result/proof,
recompute complete bytes and closure, use real receipts/independent authority and
retain all source/grant/credential/lease deadlines through the last DB clock.
Existing report acceptance cannot accept free semantic text on their behalf.
The new checker records original producing planrev1, but independently re-resolves
S/SV under current planrev2: exact same work/criteria/edge/root and complete
current source/proof READ are mandatory. This is an explicit new artifact
compatibility rule to test; no alteration to existing saved-report sharing.
If existing actual acceptance/provenance cannot satisfy it, the cycle remains
blocked until that narrow ABI is reviewed, rather than publishing replacement
proof or silently substituting a rev2 report.

Reuse existing `EngineeringWorkerServices`/runner/acceptance for E/EV and
`NativeReportProducer`/publisher/worker/acceptance for R/RV; reuse permanent
SegmentCommand and scheduler enqueue. New S/P/C worker composition is a later
reviewed interface, not a hook inside generic runner. A model draft, if used,
goes through the governed model gateway and is never independent acceptance.
Model quality and economic value remain owner-reviewed, not mechanically proved.

Final owner snapshot must state its selected-work lifetime ledger basis, actual
as-of time and unknown costs; do not silently count its own future receipt.
Export final full-root dashboard/ledger separately. Existing metric counts only
actual accepted reports; readiness/checklist metrics need a new exact native
recipe or an honest unknown result, never a raw accepted-count substitution.

## Meaningful tests and bounded next gate

Root owns plan_catalog.py, existing shared validators, ancestry and store edits.
This lane creates only the two NEW pure modules/tests after ABI review; no
parallel shared edits or SQL/proof claims from that first package.

First pure/static package: closed revision layouts and exact pair/edge; unchanged
old pair/sender/catalog bytes; extra/missing native/ordinary/sender rejection;
crossed actor/resource/criteria/root/registry rejection; ordinary unhealthy/expired
profile still denies; native model kind cannot borrow root/sibling allowance.

Then propose one new exclusive disposable DB (suggested
`nexus_company_test_stockflow_cycle_admission`; **not created or assigned here**).
Public normal015 stores only. Actual restricted-role cases must prove:

1. Revision1 actual strategy dossier/receipt/protected check and acceptance;
   revision2 retains the typed strategy pair, current accepted projection and original artifact
   provenance under the staged final current plan before commit, then read them
   again after commit. Force a nominated post-head2 denial and prove complete
   rollback including new child delegation/revision/owner-decision rows. If that
   fails, preserve it and amend
   the ABI; do not weaken proof freshness/currentness.
2. One unchanged permanent root, one consumed revision, old slices/counts/holds
   unchanged; repeated same revision adds nothing; replacement root/new plan ID,
   exhausted revision/USD/tool/model slices and hidden sibling deny atomically.
3. Native E can acquire only its zero-model slice under the mixed root;
   model action/foreign intent/run/extra native pair deny with no issuance.
4. Genuine current source/grant/member/pause/cancel/profile/approval deadlines
   crossing the last awaited boundary deny and conserve all state.
5. Revoked/stale S or E acceptance prevents dependent work; succeeded receipt alone
   does not enable P/C/R. Original current-source proof and missing-body failures
   remain visible, with no SQL state/receipt seeding.

A later full job packet uses a new actual StockFlow goal with reviewed private
committed inputs, independent author/verifier jobs, P/C actual protected artifacts,
owner report/API/dashboard and finite staging. Fresh DB/root/source/image/command/
actor/cost pins and failure-preservation plan precede activation. No resets of
retained notification, CSV, engineering or backup fixtures.

Estimated implementation effort after ABI acceptance: admission/partition source
and meaningful pure/static checks 0.5–1 day; actual transition/allowance/current-proof
PG gate 0.5–1 day after real StrategyBrief evidence exists; StrategyBrief and P/C
typed production integration plus full-lineage fixture 1–2
days, excluding real builder containment/ARM64, model quality, live notification,
owner UAT and operational release prerequisites. These are planning ranges,
not elapsed execution or a release date.
