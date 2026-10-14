# Engineering acceptance and supervised worker completion

Date:2026-10-14. State: implementation proposal after source inspection; no worker,
schema, state transition or private job is activated by this document. Scope is
one owner-approved mechanical engineering author/verifier pair. Root owns shared
interfaces and integration. The existing backup package remains frozen.

## What the current states actually mean

M1 `ExecutionState` in `runtime_contracts.py` and the native database check has
exactly six values: eligible, running, awaiting_approval, outcome_unknown,
verifying and blocked. It has no completed/failed/cancelled enum or completion
method. A succeeded `EffectStore.record_receipt()` sets the work to verifying.
`ExecutionStore.release()` increments the fence, removes the worker lease and
retains verifying, lifetime counters and known receipts. Those records describe
execution ownership/issued facts, not business acceptance. Adding completed to
M1 solely because a checker passed would confuse these meanings.

`harness.lifecycle.ActionState` has completed and a pure transition guard requiring
pass, but this is the action-journal vocabulary. Current M1 effect intents use
intent/outcome_unknown/succeeded/failed. A pure ActionState transition or the
synthetic fake-worker completed phase is not a persistent company completion API.
Neither proves that a native journal action was advanced to completed.

The engineering publisher already stores a separate immutable WorkAcceptance
with actual current protected proof. `current_accepted_work()` confirms it against
current governance, registered author/verifier, exact succeeded author receipt,
criteria, invalidation and protected READ/source freshness. Owner WorkView exposes
that current acceptance separately from execution_state and billing. The scheduler
already returns waiting/already_accepted for this current acceptance, ahead of
its same-work billing check; it does not redispatch an accepted work item merely
because M1 remains verifying. A reporting/UI description such as “mechanically
accepted; billing unconfirmed” is therefore truthful. It is not full StockFlow
business readiness or permission to promote Delegated/Board mode.

The SDD §§9–10 describes business work completion and action completion as target
product semantics. Preserve that scope through a distinct current result/projection
and a durable worker result first. Do not invent a new M1 completed enum/migration
without a separately justified operational need and Root-reviewed ADR.

## Proposed first adapter and ABI

Implement an opt-in engineering worker composition using the existing
`engineering.change/v1` and `engineering.verify/v1` workflow registrations, exact
native profiles, fixed builder source/policy/spec and existing permanent
SegmentDispatch. The constructor supplies trusted services and actual authenticated
actor resolver. A portable DBOS input is the existing SegmentCommand JSON; it
carries no acceptance, lease, callback, provider, cost, path or approval authority.
Author/verifier action selectors come from trusted registration and actual plan
edges, never arbitrary UUIDs accepted from a result payload.

Proposed new modules: `execution/engineering_worker_contracts.py`,
`engineering_worker_services.py`, `engineering_worker_context.py`,
`engineering_worker_effect.py` and `engineering_worker.py`. Keep the generic
report worker/runner contracts unchanged. Reuse EngineeringNativeBuilderRunner,
EngineeringWorkAcceptanceStore and existing scheduler, lease, directory, protected
artifact and cost boundaries. No new dependency or schema is required for this
first composition; immutable acceptance rows/events and DBOS workflow state already
provide durable identity. Root should review the exact service/result ABI before
implementation.

The trusted entrypoint is proposed as
`execute_engineering_segment(services, command, *, workflow_id) -> EngineeringSegmentResult`.
The result is descriptive: exact company/task/action/run/segment/workflow identity,
status `published|accepted|reject|inconclusive|outcome_unknown|blocked`, actual
receipt ID, acceptance ID and protected proof reference where applicable, current
execution fence observation, and billing `known|unconfirmed`. Accepted requires an
actual current native pass; reject/inconclusive requires its stored native
acceptance. Published requires the actual native succeeded receipt. No result field
permits a later tool call or overwrites the original receipt/cost.

Execution order:

1. Resolve exact permanent dispatch, current registration/profile/workflow/actor and
   authenticated current member under CompanyControl. Recover the same dispatch
   using ExecutionStore.recover_dispatched; preserve the original action/run/segment,
   issued intent and lifetime attempts. A changed workflow/version blocks rather
   than converting saved output into fresh execution.
2. Run/reconcile the existing bounded engineering runner. Only a newly committed
   M1 intent grants a one-time invocation. A saved known result restores the durable
   witness and receipt without issuing a second container. Unknown output remains
   unknown and cannot enter acceptance.
3. For author, return published from the actual receipt. For verifier, resolve the
   exact author/verifier pair and call prepare_verified_result followed by
   publish_verified_result using the actual protected proof. These existing methods
   own whole-lineage READ, current declaration/procedure/goal/governance, lease and
   final deadline checks. Raw candidates/pass JSON cannot substitute for them.
4. Before exposing accepted, resolve current_accepted_work for the exact author and
   verify its acceptance/action/run/recipe/criteria match the published record.
   Repeat current proof/source/authority windows at the final response boundary.
   Keep acceptance history visible if a later revoke removes current confirmation.
5. In finally, release only the current owned lease through ExecutionStore.release.
   A renewal may have changed the current lease expiry; retain the latest trusted
   guard lease, never release a stale worker fence. Release frees capacity and keeps
   M1 verifying plus original counters/receipts/holds. A failed release is reported
   honestly; the next same-dispatch recovery waits for actual lease expiry.
6. DBOS records one non-retrying effect step/result. Kill/restart must recover the
   actual same workflow and reconstruct process-local services. Persisted result
   JSON is a historical outcome: polling/auditing it must recheck current proof and
   authority rather than treating cached accepted as perpetual current acceptance.

Pause/cancel/revoke remains current. Historical known receipt reconciliation may
use its existing recording-only path while paused; publishing NEW acceptance
currently requires an execute lease and the active managed scope. If an OS restart
leaves only a reconcile lease after the verifier receipt was committed but before
acceptance, the present EngineeringWorkAcceptanceStore execute-only guard cannot
be bypassed. This needs a specific engineering acceptance recovery adapter, modeled
on `AcceptanceRecovery` for reports: same existing dispatch/receipt/protected inputs,
current actor and current source/governance, no new attempt/effect, no fresh approval
or cost. Root must approve this ABI and exact pause/cancel policy before coding it.
This is the principal recovery integration gap, rather than a missing completed
state label.

## Unknown billing and onward scheduling

NativeBuilderRunner records actual_usd=None, so even succeeded author/verifier
receipts retain positive unknown holds. Do not write zero because execution was
local, a fake resolver returned zero, or acceptance passed. Billing evidence must
name the real charge basis and exact original action/receipt/price. Reuse
OwnerReconciliationStore.claim_billing/resolve_billing/release_billing with its
trusted ReadOnlyBillingResolver and immutable BillingObservation evidence. This
path preserves receipt/business state and updates the original reservation only
once. A genuine observed zero is possible only if the resolver verifies a declared
actual billing basis; such a local-builder resolver is not qualified by this plan.

Current scheduling has three distinct consequences:

- Same accepted work returns waiting/already_accepted and is not redispatched.
  Historical acceptance that loses current proof cannot become new work or reset
  the registration, old attempts or parent allowance.
- Before acceptance, `_uncertain()` blocks fresh work with an unresolved effect or
  an unknown hold. A generic scheduler verifier check merely requires a succeeded
  author receipt; the report-specific NativeReportOperatingLoop additionally stops
  on unknown billing of either author or verifier. That loop is report-profile-only
  and must not be silently reused as engineering orchestration. A new engineering
  loop must state whether its approved independent verifier may proceed after a
  succeeded author receipt with unknown billing, using its own preallocated slice
  and unchanged company cap. Preserve the approved choice in the registration.
- Downstream tasks require current protected dependency acceptance, then still need
  their own owner-authorized hold, lifetime attempt slice, active ancestry and the
  company/day allowance. Unknown holds stay charged to their original Bangkok day
  and own task lifetime; the company/day cap can be exhausted even while a result
  is accepted. Repeated notification/builder work cannot recover spent capacity by
  changing workflow IDs, day buckets, profiles, child registrations or revisions.
  A new legitimate report/digest occurrence needs its actual governed registration
  and permanent notification slot; its cost remains subject to its own task and
  shared daily cap. Only genuine billing reconciliation may release an unknown
  money hold. Daily/weekly notification quota is a separate permanent constraint.

Policy proposal: acceptance may be current with billing unconfirmed, while spending
remains reserved. Show both facts. Allow the independent mechanical verifier only
when its owner-approved separate slice, source and complete current admission pass;
never make unknown billing a refund or fresh execution permit. This policy needs
Root review because the existing report loop is stricter before acceptance.

## Required fixtures and evidence

Use new exclusive normal company015/DBOS fixtures and actual public registration,
owner approvals, protected source/patch, distinct native author/verifier actions,
protected receipts/results and the production acceptance store. Preserve source
and actual tree/manifest/time identities; fixture DTO/kernel descriptors alone do
not qualify production, StockFlow full regression or ARM64.

Positive checks: accepted with unknown billing retains all original hashes,
attempt IDs, registration quotas and positive holds; both worker leases are
released; duplicate timer/event scans report already_accepted and perform zero
container/model/tool calls. A dependent separately preallocated work item can be
eligible while its accepted predecessor has reserved unknown billing only when its
own and shared cap checks pass. Actual observed billing updates once without
receipt/acceptance edits. Exact replay produces the same acceptance/proof and no
new dispatch/attempt. Owner view and operating report show accepted and unconfirmed
cost separately.

Negative checks: raw pass/candidate/receipt-only result, foreign/spliced action or
work, same-actor verifier, stale fence/member/plan/procedure/mandate/charter, source
or proof READ revoke/expiry during final await, invalidated/currently unavailable
proof, unknown effect, conflicting known result and receipt, cancelled work,
paused fresh publication, exhausted daily/work/ancestor/tool quota, missing billing
proof and conflicting bill must not publish accepted or issue another effect.
Denial preserves actual unknown hold/attempt and source history; no test rewrites
immutable registration fields to fabricate a passing state.

Recovery checks need real process kill/wait and same workflow replay at five
barriers: intent committed, native result stored, succeeded receipt recorded,
protected engineering proof registered, and WorkAcceptance committed before worker
release/DBOS result. Show target current_database when testing restored recovery.
For each boundary conserve original intent/run/segment/attempt, reject the stale
fence, record whether publication is historical or currently confirmed, and prove
zero second container/model call. The acceptance-recovery execute/reconcile policy
must be established before its post-receipt positive test can pass.

## Delivery order and effort

Estimated engineering effort after the exact service ABI/recovery policy is agreed:
0.5day for contracts/composition and current acceptance projection;1–1.5days for
same-dispatch worker/recovery adapter;1day for actual crash/expiry/budget fixtures;
0.5day for owner/scheduler/report integration and milestone review. Rough total
3–3.5engineering days, not a measured release date. Actual StockFlow regression,
ARM64 qualification, billing resolver evidence, owner setup, deployment and soak
are separate work and may dominate calendar time. A future persistent business
completion snapshot/migration would be a separate justified proposal, not implicit
in this estimate.

## Source anchors and reconciliation notes

Observed source, checked2026-10-14 on primary0076a59 plus frozen engineering17file
package (source cdd58cbe…); this is a plan, not implementation evidence:

- [M1 states](../../backend/nexus/execution/runtime_contracts.py),
  [receipt state](../../backend/nexus/execution/effect_store.py),
  [release/recovery](../../backend/nexus/execution/runtime_recovery.py),
  [action vocabulary](../../backend/nexus/harness/lifecycle.py).
- [Engineering acceptance](../../backend/nexus/builder/engineering_acceptance.py),
  [known-result runner](../../backend/nexus/builder/engineering_runner.py),
  [current acceptance](../../backend/nexus/execution/management_checks.py),
  [owner projection](../../backend/nexus/company/management/owner_view_work.py).
- [Native scheduling](../../backend/nexus/company/management/scheduling_reads.py),
  [atomic enqueue](../../backend/nexus/company/management/scheduling_queue.py),
  [report loop](../../backend/nexus/company/management/native_loop_store.py),
  [report recovery](../../backend/nexus/company/management/acceptance_recovery.py).
- [Owner billing](../../backend/nexus/execution/owner_billing_store.py),
  [billing resolver contract](../../backend/nexus/execution/billing_contracts.py),
  [cost holds](../../backend/nexus/harness/journal_budget.py),
  [inherited caps](../../backend/nexus/harness/journal_reservations.py).

The generic pure eligibility evaluator checks unknown billing before own current
acceptance, whereas native scheduling and the report loop return current acceptance
first. Preserve this observed ordering difference explicitly in the new engineering
projection tests and Root policy review; do not claim all current report/scheduler
paths already produce identical labels. Regardless of labels, none may refund an
unknown hold, redispatch an accepted task or turn current proof into spend authority.
