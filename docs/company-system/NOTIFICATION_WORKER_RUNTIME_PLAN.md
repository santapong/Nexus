# Bounded notification event and timer worker

Planning only, checked 2026-10-14 at committed `f68fce4` (native admission
`154e5bf`). This document authorizes no launch, credential setup, email, provider
call or owner UAT mutation. Root owns implementation and integration. Owner login
completion and live sender configuration are not established by this inspection.

The recommended first release composes the existing native fact emitter, atomic
draft consumer, exact owner action approval, managed sender and M1/DBOS recovery.
It does not invoke a model to decide whether work exists. “Zero idle cost” means
zero model requests, tool attempts and provider POST/GET calls on idle ticks;
bounded database polling and process resources still have a cost.

## Current boundaries and required decisions

| Existing source | Actual behavior to preserve |
| --- | --- |
| `brain/native_fact_reader.py`, `native_fact_emitter.py` | Current authenticated owner, actual locked CompanyControl, native selector/state, complete contributor/resource/freshness qualification, then final clock. Decision/block/cap/digest fallback is callable; no timer is running. |
| `notifications/receipt_event_publisher.py` | Actual failed M1 receipt appends an ID-only wake in the receipt transaction. Recording an already issued outcome does not require renewed source execution permission. |
| `management/acceptance_store.py`, `acceptance_recovery.py` | Actual protected acceptance appends `verification_recorded`; a raw pass candidate is not completion. |
| `notifications/qualified_consumer.py`, `qualified_store.py` | At most32 events in30s; native drafts, coalesced links, licensed obsolete dispositions and cursor commit together, with final source/owner/recipient dates after cursor flush. Actionable privacy/config/expiry failure rolls back the entire batch. |
| `notifications/managed_preparation.py`, `managed_admission.py` | Disabled by default. Existing current approved sender child only; caller AND registered sender actor must equal actual company owner. Prepares/replays one pending action, no task, hold, grant or lease. Charter must cover every draft input resource. |
| `notifications/managed_effects.py`, `managed_dispatch.py`, `dispatch_store.py` | Actual M1 intent/attempt and permanent native dispatch slot, current managed admission before and after commit, one non-retrying POST. Transport is independently disabled by default. Actual billing is `None`, not zero. |
| `notifications/dispatch_windows.py`, `dispatch_slots.py` | Routine daily cap1..10; daily/weekly consume one permanent company/kind/due-bucket slot. Rejection, uncertainty and provider idempotency retention expiry do not restore a slot. |
| `notifications/status_store.py` | Explicit current-owner status/reconciliation; GET requires an actual known receipt/provider UUID. Missing/unknown provider ID cannot be converted into a POST or a fabricated success. |
| `execution/native_report_worker.py`, `native_report_context.py`, `runtime_recovery.py` | Existing durable pattern: exact SegmentDispatch/command, configured actor, same segment, stable executor ID, fresh execute admission only for unissued work; issued work recovers in reconcile mode. Notification execution is not implemented by this report worker. |

Current `SchedulerIdentities.actor(binding)` is a trusted dependency interface,
not a production credential issuer. `VerifiedIdentity` retains UUID subject and
workspace only; token verification/expiry must precede it. HTTP authentication
currently checks HS256 signature and required integer `exp`/`iat` plus UUID
`sub`/`workspace_id` (`api/company_auth.py`), then actual directory membership.
Do not reuse disposable `PilotConfig.identity()`, construct an identity from
CompanyControl.owner_id, or treat registration JSON as authentication.

The smallest compatible owner-only release needs either a real authenticated
owner request per explicit tick or an explicitly configured real owner credential
provider with finite validity and renewal policy. An expired/missing credential
stops fresh work; the worker does not mint or silently renew owner tokens. No such
production provider is established here. A non-owner service principal is a
separate admission package: owner-approved delegation, actual service membership,
registered actor/work, complete service AND current-owner READ intersection,
recipient pins and revocation. Existing owner-only methods must not be called
using a fabricated owner identity or a new bypass flag. Start with the existing
owner-only boundary; defer non-owner unattended operation until that package is
specified and proven.

## Phase1 — configuration, identity and independent zero-model admission

Add small new `notifications/worker_contracts.py`, `worker_config.py` and
`worker_services.py`. A proposed strict `NotificationWorkerRegistration` selects
one company/workspace, registration/recipe, exact existing sender RunBinding and
PlanRevisionRef, configured subject resources, and up to32 registered digest or
fallback selectors. It contains no body, address, endpoint, credential, approval,
clock, role or portable permit. Store it as bounded immutable0600 operator
configuration; reload and compare exact pins after restart. Pin policy/template,
resource map and catalog through actual configured services, not caller hashes.
Keep draft/preparation/dispatch enablement separate and false by default.

Proposed process-only identity ABI:
`NotificationWorkerIdentities.current(expected_binding) -> AuthenticatedWorkerIdentity`.
The trusted adapter verifies an actual credential and retains its expiry as a
server-only time witness; every current transaction still reads membership,
current owner and work binding. Its synchronous final authentication-time check
runs after the last await and immediately before a provider call. It must also
support owner-authenticated read ticks before any sender execution exists. Tokens
and trusted objects never enter DBOS payloads or persisted action parameters.

A distinct closed `notification.native.v1` profile is recommended before an
independent empty-model-catalog release. Existing fixtures use zero model quota
but an ordinary evaluated profile; `managed_sources.profile_deadlines` still
requires current model health/evaluations. Zero quota alone does not remove that
admission dependency. Merely wiring the existing fixture can demonstrate zero
model calls, but cannot demonstrate independent model-free notification admission.

Use a new notification profile type/helper, not an extension of the just-shipped
engineering/verification native pair. Proposed fixed identity is workflow
`internal.owner-notification`/`v1`, zero model requests, exact
`company.owner-notification.send.v1`/`v1`, registered target symbol/ResourceRef and
exact original registry revision/SHA. Declare a separate default-empty catalog
field, excluded when empty. Validate the whole tuple before selection, narrow only
notification work/tool effects, and enforce actual zero-model immutable ancestry.
Do not admit model tools or arbitrary internal workflows. Ordinary model gates and
the closed two-child engineering pair retain their predicates. Selected-model
catalog views must not carry full-registry native pins after original validation;
retain the coexistence regression from the gateway review.

Owner must approve the actual goal, mandate, charter and finite native plan before
worker configuration. A dedicated notification goal/root/child avoids inheriting
unrelated report/LLM sibling clocks; its purpose is submission, not work acceptance.
PlanPayload already permits a single child and no verification edge, but current
charter/department/member/resource rules still apply. Current lifetime quota is at
most20 tool attempts per registered root, not20 per day. Exhaustion, permanent
cancellation or unknown charges stop new issuance; no automatic new goal, child,
run, revision or grant refills it. New owner intent remains explicit.

Necessary narrow Root deltas: notification profile admission in `plan_support.py`,
`model_profile_checks.py`, actual ancestry/effect narrowing, and
`notifications/managed_sources.profile_deadlines` so only this proven native
identity bypasses irrelevant model evidence. Other children retain current ANY
model evidence and complete exact grant/source deadlines. No schema is assumed
necessary for these Name-based bindings; verify that with existing normal015 DTO
and native-row fixtures rather than modifying frozen registrations.

## Phase2 — bounded read/preparation tick and exact approval consumption

Proposed `NotificationWorkerServices` composes actual factory/directory,
identity provider, NativeFactEmitter, QualifiedNotificationConsumer,
ManagedNotificationPreparation/DispatchStore, guarded ExecutionStore,
ManagementScheduler, status reader and fixed registration. It contains no model
client. New `notifications/worker_tick.py` exposes `tick(event=None) -> TickResult`
with safe counts/dispositions, no private bodies or call permits. It performs at
most one preparation OR one exact sender enqueue after one bounded draft batch.

For actual brain events, use the persistent recipe cursor already implemented by
QualifiedNotificationConsumer; receipt/acceptance wakes require no invented event
or status. Draft acknowledgement is not dispatch acknowledgement. Following
consumer commit, reload at most8 selected draft metadata rows and requalify every
visited row/lookahead before selection. Reuse `get_current_locked` and visited
barriers; licensed obsolete can disappear, private/unavailable/expired cannot be
silently acknowledged or skipped. A blocked actionable cursor produces a constant
safe diagnostic and bounded backoff, not a new recipe or an unlicensed cursor jump.

A minute fallback handles decision, membership, grant/TTL, block and cap changes
without native transaction hooks. Inspect only the registered subjects, at most32
per minute, with max100 exact registered tasks per subject where existing scheduler
bounds apply. Emit via actual NativeFactEmitter selectors and its unchanged-state
dedup recipe. Daily after Bangkok09:00 and weekly current Monday09:00 use
`native_fact_digest.digest_window`, not the exact-instant legacy pure helper.
Registered finite policy/report/resource pins are mandatory. Catch up only the
current bucket; no historical email backlog after a restart. A changed saved report
projection is obsolete/unavailable until explicit owner-saved replacement
registration; the timer cannot invent a fresh report ID or source snapshot.

There is no notification opportunity planner in this slice. A15-minute safety scan
may examine the same finite configuration only. Do not call the general report
loop or LLM to propose new notification work. Canonical current/previous-minute
DueWake and scheduler scan receipts remain descriptive. Bound scheduling to the
one registered sender task; avoid idle scheduler writes/scans when no draft or
approved action exists.

Use existing deterministic `notification_action_id(plan,task,draft)` and the exact
three action parameters: draft_id, payload_sha256, recipient_policy_sha256. Pending
actions have no hold/counter. Real HTTP owner approval currently records a decision
without scheduling; the worker must consume that existing exact approval under the
actual actor using public `authorize_registered_pending_locked`, wrapped in
current managed draft/action/resource admission before AND after hold/flush.
Capture exact approval/source/grant/profile/credential dates and compare at final
DB clock. Then ManagementScheduler may enqueue the registered task. Never approve
itself. `standing_contracts._INTERNAL_TOOLS` currently admits only two fake internal
tools: notification send is external and stays exact-approval-only. No standing
allowlist expansion belongs in this runtime integration.

## Phase3 — durable non-retrying dispatch and truthful recovery

New `execution/notification_worker.py`, `notification_services.py` and
`notification_context.py` use existing portable SegmentCommand, native
reserve_dispatch and the registered scheduler queue interface. Proposed fixed
application `nexus-owner-notifications`, queue `nexus.notifications.v1`, workflow
`internal.owner-notification`/`v1`; keep them distinct from the offline M1 worker
and strict report worker. A separate process avoids reconfiguring DBOS's existing
global application. Stable executor ID must be unique per logical host and stable
across restart; worker UUID may vary. Business connections remain restricted and
cannot bypass company RLS.

One DBOS effect step has `retries_allowed=False`; fresh context resolves actual
SegmentDispatch, native binding, configured credential/actor and exact journal
action, then `recover_dispatched`. Queue payload supplies IDs only. Do not cache
EffectStart.permit_external_call across steps. Recovery uses the same run/segment,
current fence/mode and actual issued facts. Bound old-lease waiting to310s (M1
maximum lease300s plus margin), with sensible0.5..1s checks instead of copying the
report fixture's50ms loop. Use global/worker queue concurrency1, business pool<=4,
finite tick concurrency1/company, and queue polling>=1s; return to the minute
fallback when idle rather than busy-rescanning a company.

Fresh execute mode delegates to actual ManagedNotificationDispatchStore. Preserve
permanent draft slot and provider key `nexus-owner-{companyhex}-{drafthex}` across
time, tasks and revisions. If any intent exists, no further POST is allowed. After
committed-intent failure, release capacity through native runtime so unresolved
issuance becomes outcome_unknown; consumed attempt, daily/bucket slot and hold
remain. Source/recipient expiry, pause, revocation and cancellation forbid fresh
issuance, while actual receipts/cost history remain auditable. Current owner and
membership rules are not weakened to force recording after identity revocation.

Known receipt recovery is read-only/local first. A known provider UUID may support
an explicit bounded `NotificationStatusStore.reconcile_known` GET under current
owner/source/recipient qualification; this is not an idle poll. Unknown/no UUID
stays unknown, with no GET search, POST replay or refund. Provider acceptance,
delivery observation, actual cost and WorkAcceptance remain distinct. Current send
records `actual_usd=None`; successful submission can therefore leave unknown held
billing and block subsequent scheduler issuance. Explicit cost reconciliation is a
release dependency for repeated operation, not permission to substitute zero.

No new durable timer table is needed initially: registered immutable configuration,
native wake dedup, consumer cursor, pending journal identity and permanent
SegmentDispatch make replay safe. Persist a timer occurrence only when it emits or
prepares actionable work; do not create a new workflow per idle minute. If multiple
supervisors are required later, add a bounded native timer lease/dedup schema as a
separate normal migration rather than relying on process memory.

## Phase4 — coherent offline proof and supervised release gate

Use a new exclusively assigned normal015 restricted PostgreSQL fixture, actual
public owner goal/charter/plan, signed credential adapter and .invalid recipient
file. Mock transport only. Retain unchanged probes through corrections; freeze
each coherent phase and review once, not after each edit. Required proof groups:

- Empty native registry admits only fixed notification zero-model work; wrong
  profile/tool/resource/company/ancestry denies. Old default catalog/action codecs,
  engineering pair and ordinary observed model calls remain exact/current.
- Event plus repeated minute wake coalesces into one actual draft/link and pending
  action. Disabled, idle, unchanged and minor/raw-candidate completion produce zero
  model/tool/POST/GET/hold/dispatch; late cursor expiry rolls back the whole batch.
- Actual owner HTTP approval -> actor authorization -> exact enqueue -> one mock
  POST/native receipt. Approval alone is insufficient; standing-send attempt denies.
  Natural expiry during actual hold/queue/intent/precall awaits rolls back unissued
  state or preserves committed unknown state, respectively.
- Current owner/member/source ancestor/recipient-file/target/plan/pause/cancellation
  loss denies fresh work without exposing private body. Source loss on obsolete,
  lookahead and cursor anchor retains full-page/batch privacy gates.
- Real OS kill/restart at intent, provider-response-before-receipt, receipt and
  provider-observation boundaries keeps the same dispatch/run/segment and consumed
  counters. Unknown response has at mostone POST; known ID reconciliation performs
  no POST. Changed command bytes, unstable executor ID, reconcile mode and old
  fence deny new effects. Positive billing remains unknown unless actually proven.
- Restart after daily/weekly09:00 produces only the current registered bucket;
  quota remains consumed after rejection/unknown or provider-key expiry. Config
  reload/two concurrent wakes cannot create a second action/slot or refill lifetime
  budget. Digest acceptance uses actual saved dates/unknown-cost text, never a
  metric or report claim of completed business work.

Planning estimate: phase1 about1..2 engineering days; phase2 about1 day; durable
dispatch/recovery about1..2 days; combined adversarial/process proof about1..2 days.
Rough total4..7 days with current stores reused, excluding real credentials,
sender/domain/provider qualification and operator release. A separate delegated
non-owner worker adds roughly2..4 days plus any normal delegation schema gate.
These are estimates, not executed evidence or an activation schedule.

Release remains blocked until actual authentication provider, owner decision
reachability, finite approved sender resources/quota/budget, recipient/sender
configuration, exact runtime pins, cost-unknown policy and coherent process proof
exist. Root can integrate optional composition disabled by default first. One
concrete reviewed launch packet and explicit supervised activation follows those
proofs; no per-edit human permission or synthetic owner identity is required.
