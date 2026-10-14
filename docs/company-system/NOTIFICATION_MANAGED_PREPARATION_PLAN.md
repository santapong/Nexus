# Managed owner notification preparation — bounded integration plan

Approved selector and specialization ABI by coordinator on2026-10-14. This extends
supervised local native conformance; default transport stays disabled. Existing
notification draft/dispatch freezes remain historical, with the separately reviewed
current-target precall amendment recorded explicitly. No real email or activation.

## Public selection and result

`NativeNotificationSelection(company_id,draft_id,sender_task_id,plan:PlanRevisionRef)`
contains only existing native IDs and exact plan reference. It supplies no actor,
run, recipient, body, clock, cost, role or approval. The trusted preparer resolves
the actual current owner sender child and immutable M1 registration under the
company mutex. Caller plan/hash assertions must equal current native state.

`ManagedNotificationPreparation(factory,drafts,catalog,artifacts,freshness,*,policy)`
exposes `prepare(owner_control_scope,actual_verified_identity,selection)` and returns
`PreparedNotification(action:ActionRecord,actual RunBinding/registrationSHA/plan,
payloadSHA/recipientPolicySHA,call_permit=False)`. Policy is explicit server config:
disabled by default, exact registered target/tool/version/resource/workflow tuple
and bounded estimated cost. Pending append creates no hold, allowance, task, run,
lease, grant, owner approval, provider call or new model request.

Action identity derives deterministically from the current plan revision, existing
sender task and draft. Parameters retain exactly the frozen three pins: draft_id,
payload_sha256 and recipient_policy_sha256. A previous-plan pending approval cannot
match a newly selected plan. Exact retry returns the existing journal record without
refreshing approval, counters, proof or native source dates.

## Actual managed admission and dispatch

Prepare resolves actual current PlanStore binding, signed current owner actor,
registered work/run/trace/hash, charter, governance, model-profile evidence and
permanently partitioned child budget/quota. It reuses public management execution
and plan action validation, qualified source/artifact readers, registered recipient
file and current protected draft rederivation. Complete draft resources must fit
the exact sender charter's configured map; unknown/private/unmapped inputs deny.
Actual target grants and complete source/freshness deadlines are retained through
pending append, and current qualification is repeated before returning the record.

`ManagedNotificationEffectStore` specializes actual EffectStore and calls real
`super.begin` with a composite of the frozen before_intent notification check and
current managed qualification. It never fabricates EffectStart or persists a slot
outside native intent. FinalIntentTimeCheck includes actual approval/lease, complete
source/target/charter grants and registered model health/evaluation clocks. Pure
captured deadlines only narrow the last clock; they cannot replace fresh current
ACL/governance checks after commitment.

A new managed dispatch specialization retains the original public dispatch ABI and
rederives managed plan/source/target qualification at precall. Its captured deadlines
join the actual check so the final local clock before POST cannot cross model or
resource expiry unnoticed. Root's public `revalidate_execution_locked` delegates
actual configured M1 admission without exposing private configuration fields.
Existing public journal exact owner approval/authorization and managed execution
claim remain separate supervised steps. No preparer autoapproves pending work.

## Tests and ownership

New modules only: managed_contracts, managed_admission/sources, managed_preparation,
managed_effects/dispatch as needed, with owned test-only native setup. Normal015 on
exclusive notifications DB; public actual source/control/goal/plan approval creates
fixture sender children before execution. No raw operative pass/receipt/allowance
seeds. Fixture registry values are explicitly synthetic offline qualification.

Tests first: pending only/default disabled; exact existing plan/task/run/source
binding; genuine native acceptance event and protected draft; owner approval then
managed claim/one permit/one mock POST; actual old plan/charter/model/source/recipient
and target revocation/expiry; wrong owner/unmanaged work/extra params/version/resource;
full rollback before intent; postcommit denial preserves committed unknown intent
and held billing; replay preserves budget/counters and never resends. New work or
plan revision must never renew the existing draft's permanent dispatch slot.

015 decision/block/cap/digest typed reader adaptation and atomic cursor acknowledgement
follow as separate packages. This bounded first sender is the actual current owner;
non-owner notification worker intersection admission remains unsupported. No full
NOTIFY-01/M5, live provider delivery, engineering/goal completion or release claim.
