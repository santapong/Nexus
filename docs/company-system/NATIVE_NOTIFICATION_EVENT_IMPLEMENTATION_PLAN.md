# Native notification wakes — normal015

Task scope accepted by Root on 2026-10-14: event DTO/ORM/store, bounded native fact
reader/emitter and focused tests. Root owns static015 migration, shared native
unique-target metadata, profile registration and independent schema qualification.
Notification handlers/native draft/projection packages remain D-owned. The frozen
native operating loop is unchanged. No timer, notification send, provider or
device action is activated by this work.

## Physical and compatibility ABI

OutboxEvent extends the existing six kinds with decision_required, work_blocked,
cap_exhausted and digest_due. Seven nullable fields are task_id, report_id,
budget_day (date), native_snapshot_sha256, due_bucket, scheduled_for and
notification_policy_sha256. Old kinds retain their existing source/ACL/action
binding semantics with all seven new fields NULL. New kinds require source and
resource-generation fields NULL. Decision binds action+task+stateSHA; blocked
binds task+stateSHA; cap binds stateSHA plus exactly one task or actual company/day
budget; digest binds report+stateSHA+bucket+schedule+policySHA. Every event resource
is an actual existing owner-provisioned ResourceRef, never a fake source head.

Task/report/day FKs target actual RegisteredWork, ManagementReportSnapshot and
DailyBudget. Decision action/task equality uses the additional scoped
JournalAction(company,id,task) unique target and matching composite FK. Each FK
has its full leading child index; hashes/kinds/per-kind SQL NULL shapes remain
explicit. No older migration is rewritten.

The old BrainEvent mapper/old-column SQL must remain usable on normal008 and014.
Qualified read_event/select-event APIs use actual native capability before any
new field is selected. The old writer uses explicit old-column Core INSERT;
new kinds require a qualified015 full projection and deny partial/absent native
capability. The accepted separate NativeBrainEvent mapper shares the full Table
without instrumenting any new column on the original BrainEvent mapper, proven
with pinned SQLAlchemy2.0.51. No schema version, parsed DTO or stored hash is a
permit. Core mapping/schema checkpoint is 1338684; the original Core10 freeze is
retained independently from this emitter package.

## Canonical actual state ABI

New strict selectors contain only action/task/schedule identifiers. They contain
no caller owner, resource/path/recipient, status/body, state/hash, amount, budget
day, due instant or event UUID. NativeFactReader resolves/rederives state under
actual supplied CompanyControl, signed current owner/registered caller and
qualified resource/source services. Canonical state snapshots are shared with D:

- Decision: actual ActionRecord, exact native work/registration hash/current plan
  and actual control policy/prices. An actual pending missing decision is required.
- Blocked: actual registered work/execution/current or historical plan and native
  eligibility/explicit cancellation facts; inactive is not inferred cancellation.
- Company cap: actual current Bangkok-day DailyBudget held/spent and actual control
  cap. Work cap: actual own permanent WorkBudget held/spent/delegated slice.
  billing_unknown comes from actual unknown CostHold state, distinct from known
  zero/unissued holds; no ancestor/root totals are added. LedgerUSD preserves
  observed over-cap amounts. The SQL date has an explicit exact ISO serializer
  in the canonical native cap state; no shared canonical recipe was changed.
- Failure: canonical actual failed ActionReceipt plus exact stored failed intent /
  registered-work binding, preserving existing receipt stateSHA semantics.
- Digest: actual SavedOperatingReport envelope, original observedAt and snapshot
  hash, explicit registered daily/weekly NotificationPolicy/version/hash and exact
  09:00Bangkok due bucket (Monday for weekly). No metric/receipt completion shortcut.

The reader requires the actual session-owned locked CompanyControl, freshly
checks the signed current owner, and returns strict native state plus complete required resource IDs,
artifact references and actual grant/source/policy deadlines separately. StateSHA
is canonical actual state; privacy/authority remain current independent gates.
Uncheckable or missing input denies rather than fabricating a meaningful signal.
The derived source_event property retains actual SourceTime precision: receipt /
report original recorded observation is instant; actual Bangkok budget day is
day; work/action rows without an immutable occurrence timestamp remain unknown.
source_recorded_at on those undated rows is only the fresh DB observation time,
never a fabricated created/blocked/exhausted occurrence instant.
Work inputs retain exact immutable native historical charter scope even after
revocation; current READ/head/origin qualification still applies. Unsupported
unmanaged/root work input scope is denied rather than substituted with a public
or empty scope. Company/day cap is a company ledger fact with its explicitly
configured subject resource. No artifact raw_text is selected while resolving
native artifact references; protected bytes/current contributor closures are
qualified by the public artifact reader and RegisteredSourceFreshness.

## Public read/emitter ABI

NativeFactServices is server constructor configuration: exact PlanAdmissionCatalog,
BoundedArtifactReader, RegisteredSourceFreshness, matching SchedulerServices,
actual subject ResourceRef, and at most32 unique RegisteredDigestPolicy entries.
Digest event selectors must stay unambiguous after restart. Configured verified
actors are consumed only for descriptive current plan/admission reads.

NativeFactReader.load_locked(session, control, owner BrainReadScope,
VerifiedIdentity, NativeEventSelector) returns NativeFactProjection or None.
load_event_locked uses the same signature with OutboxEvent, re-reads the actual
persisted event and requires exact equality before deriving a selector. Native
state/policy/bucket/resource pins are recomputed; stale events return None.
Invalid scope, unavailable private inputs, unqualified policies, ambiguous or
counterfeit records deny explicitly. BrainReadScope is owner-global (no task
binding); it never creates a worker, owner identity or allowance.

NativeFactEmitter(factory, reader).emit(scope, identity, selector) acquires the
actual company mutex; emit_locked is the same-session variant. Selectors have
only company/action/task/schedule identifiers, never body/status/amount/hash/
clock/eventID/audience. Both methods return the actual ID-only OutboxEvent or
None and grant no dispatch, recipient or delivery permission.

## Publication and replay

NativeFactEmitter.emit/emit_locked resolves actual native selectors and calls
append_event in the same company transaction. It rederives current native state
and complete resource/source authorization before/after awaited publication and
checks all captured deadlines against fresh final DB time. New-kind keys are
native.{kind}.v1:{canonical actual stateSHA}; the actual typed state includes
company/subject and digest policy/report/bucket. Unchanged facts coalesce.
Event ID and sequence come only from actual
append_event; later draft delivery must rederive the same native state rather
than trust event.native_snapshot_sha256. Completion keeps the existing current
protected WorkAcceptance gate; raw verifier candidate/pass does not qualify.

Root owns the separate production NativeReceiptEventPublisher hook, installed
as optional EffectStore dependency by native composition. It uses the actual
stored action resource symbol -> exact catalog ResourceRef -> actual registered
BrainResource, and native.receipt.failed.v1:{actionID}:{canonical ActionReceiptSHA}.
Receipt-recorded is an old kind; all seven native fields remain NULL. Already
issued failure recording/reconciliation must survive pause, inactive actors and
source revocation without demanding fresh source READ or admission. Our public
FailedReceiptSelector/fallback emitter does not replace that hook. Current owner
and complete source/resource READ qualification is required for notification
content load. Receipt/cost/attempt histories remain immutable; unknown issued
facts are never refunded or promoted by event publication.

## Tests and freeze

Tests first: strict alternate/missing/SQL NULL shapes; old008/014 append/replay /
consume/direct scheduler-audit get with old-column SQL, plus real014 ingestion.
Full008 ingestion is explicitly not claimed: pre-existing012 artifact mapping
reads an absent008 classification column, outside the event mapper proof. Normal015 actual
native FK/RLS/immutable/index behavior after Root handshake; actual public native
pending/blocked/cap/digest/failed receipt sources; source/resource/owner/member /
pause/deadline changes, unchanged state/bucket coalescing, replay conflict, raw
candidate rejection and no effects/counter/cost mutation. Source/schema/proof
hashes, fixture truth and exact loaded migration head remain scoped in the freeze.

New emitter matrix:32 checks (21 restricted normal015 PG +11 unit) passed in
107.63s on the exclusive native_events DB. Four natural final-outbox deadline
crossings cover owner READ, actual actor READ, model profile health and digest
policy. Actual failed-receipt tests use public M1 intent/record operations and
fixture outcomes; they do not claim a real external tool failure or send. Company
cap uses five actual signed registered M1 holds. No model, notification transport,
timer, recipient provisioning, worker dispatch or activation is tested/claimed.
The assigned fixture truncates only disposable event rows before normal base
downgrade because normal015 deliberately refuses dropping surviving native
history; production downgrade refusal is preserved.
