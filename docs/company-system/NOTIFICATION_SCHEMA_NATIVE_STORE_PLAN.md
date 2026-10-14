# Notification ledger schema and native store plan

Draft 2026-10-14, after the separate offline contract/HTTP freeze. These new ORM
declarations are unregistered; Root owns normal014, shared native unique keys,
event contracts/emitters and profile qualification. No migration, notification
DB write, send, timer or worker is active.

## Four immutable tables

| Table | Permanent identity and content | Native references |
| --- | --- | --- |
| `company_notification_drafts` | `(company,draft)`; unique `(company,owner class,triggerSHA)`; kind routine/daily/weekly; exact native subject/state, policy/template, recipient policy snapshot/hash, payload bytes/hash, full bounded draft JSON/hash, signed owner operation/audit IDs | Actual company, recipient owner and recorder membership. Subject is polymorphic and must be loaded through its actual native service; no invented FK. |
| `company_notification_event_links` | One `(company,event)` maps to one draft; preserve original event sequence and recorded time | Exact BrainEvent `(company,event,sequence)` and draft. Root adds BrainEvent triple unique key. |
| `company_notification_dispatches` | One `(company,draft)` binds one unique `(company,action)`; exact task/trace/run/fence/proposal, fixed tool attempt, payload/policy/kind, permanent provider key, actual Bangkok intent day | Exact draft five-tuple, ExecutionWork task/run, DirectoryMembership issuer, deferred exact EffectIntent eight-tuple. |
| `company_notification_observations` | `(company,observation)`; immutable submission/delivery/reconciliation envelope, response/record hashes, provider identity, safe event/outcome/reason and native operation/audit IDs | Exact dispatch `(company,draft,action,payloadSHA)` and recorder membership. Serialized M1 receipts have no independent native receipt table: exact receipt ID/hash/provider linkage is validated by actual M1 lookup, not a fake FK. |

The deferred dispatch target is EffectIntent
`(company_id,action_id,task_id,trace_id,run_id,intent_fence,attempt_kind,proposal_hash)`.
Root adds its matching nondeferrable unique target constraint. Dispatch
`attempt_kind` is exactly `tool_attempts`; attempt number is exactly integer1.
Actual before_intent validation may insert this binding in the existing M1
transaction before EffectIntent exists. The native intent is then inserted and
the deferred FK resolves at commit. A later failure rolls both back. Existing
intent never calls that hook or permits another POST. No separate binding commit
and no caller-provided permit/receipt boolean are valid alternatives.

Every FK has an explicit full leading-prefix child index, including company,
membership, draft content, event triple and full intent eight-tuple. Draft list
index is `(company,recipient_owner,recorded_at,draft)`; routine usage index is
`(company,kind,bangkok_day,draft)`. Observation list index binds company/draft/time/ID.
Initial submission has a partial unique `(company,draft)`; later explicit
reconciliation appends history without changing the initial observation or
creating another dispatch. Unknown billing is never zero or refunded by this ledger.

## Canonical and NULL contract

Store exact strict model `model_dump_json(by_alias=True)` in `record_json` and
`canonical_sha256(decoded_model)` in `record_sha256`. Payload JSON is the exact
bounded sorted wire UTF8 object from `NotificationPayload.wire_bytes()`; its SHA
covers those bytes independently. Recipient policy JSON is its exact immutable
strict model dump and its canonical policy SHA. These hashes are integrity pins,
not authorization. Native store validates all redundant columns against JSON.

Draft JSON is at most4MiB UTF8, payload at most128KiB and recipient snapshot at
most16KiB. Subject/policy/template/schedule symbols are bounded; all hashes match
64lowercase hexadecimal. Source dates retain actual SourceTime precision. Routine
drafts have NULL duebucket/scheduled_for; daily/weekly drafts require both and an
actual registered due policy plus actual saved report subject. Digest contracts
and emitter qualification are an additive native package, not a fake routine
signal with a fabricated event ID.

Observation JSON is at most32KiB; only safe status and provider-response SHA are
stored, never API key/error body/raw message content. Submission/reconciliation
accepted requires provider UUID and response SHA; rejected/unknown/blocked has
NULL provider UUID. Delivery requires a known provider UUID; observed requires
known provider event and response SHA. Unavailable/blocked delivery has NULL
event and unknown delivery state. These branches use explicit IS NULL/IS NOT NULL
guards so SQL UNKNOWN cannot satisfy a required binding. Provider acceptance
does not fill a delivered state. Recorded time/currentness and bill outcome are
separate. Forced company RLS and append-only triggers remain Root installation.

## Actual source coverage and missing shared wakes

- `decision_required`: exact pending JournalAction/proposal hash/current decision
  state; new Root native event is required.
- `blocked`: exact registered ExecutionWork/current plan/eligibility reason and
  immutable captured state hash; new event required, with fresh current rederivation.
- `failed`: actual receipt_recorded plus exact failed M1 receipt; independent
  verifier reject may also resolve a meaningful failure with exact protected proof.
- `cap_exhausted`: actual DailyBudget `(company,Bangkok day)` or WorkBudget
  `(company,task)` and actual control cap; new event required. Daily subject is the
  actual company ID plus explicit budget date, not an invented entity UUID.
- `work_accepted`: actual verification_recorded followed by current native
  `current_accepted_work` pass/proof/source qualification of the exact registered
  major work; candidate, metric satisfaction and receipt alone remain excluded.
- digests: optional registered due policy, canonical duebucket and actual saved
  report ID/hash; actual Root digest_due publication is required.

Root's additive event extension preserves existing six Brain kinds. New kinds
need exact nullable task/report/budget-day/state-SHA native references and explicit
per-kind binding guards. Every event ID and sequence is returned by actual
append_event under CompanyControl. Deterministic fallback may append the same
real deduplicated event; it cannot pass an arbitrary UUID as event provenance.
Use a real owner-provisioned notification/subject resource, not a fake source head.

Proposed new shared OutboxEvent fields (Root review/implementation only):
`task_id: UUID|None`, `report_id: UUID|None`, `budget_day: date|None`,
`native_snapshot_sha256: SHA256|None`, `due_bucket: Symbol|None`,
`scheduled_for: AwareDatetime|None`, `notification_policy_sha256: SHA256|None`.
All existing six kinds retain their current bindings. Decision requires actual
action/task plus native-state SHA; blocked requires actual task/state SHA; cap
requires state SHA and exactly one of actual work task or actual company/day
budget; digest requires actual report, canonical bucket/due instant and registered
policy SHA. New task/report/day references point to actual RegisteredWork,
saved OperatingReport and DailyBudget respectively; decision task/action equality
and current canonical native state are revalidated by the service. No generic
unverified state text or caller `meaningful` flag belongs in the event.

## Native service sequence after schema handshake

`RegisteredOwnerRecipients.current(company_id,actual_owner_id,now)` is a mandatory
trusted server store/file interface. Actual current configuration is loaded and
hash-pinned independently of PrincipalAccess. It is never obtained from JWT
claims, caller body/address or legacy users. Missing current policy is a visible
configuration block. No new identity is synthesized to read owner source content.

`NotificationDraftStore.consume` resolves actual bounded native events and
current owner/source intersection, persists/coalesces draft+event links and
acknowledges cursor in one CC transaction, with all final deadlines. Protected
byte work is prepared outside the mutex. Unsupported/private facts remain
blocked and existing owner native alerts remain visible. An actual event handler
can use BrainEventStore only for its existing same-session apply/ack contract.

Owner `get/current/page` reads use fresh signed owner and source qualification,
bounded records/pages and dated history versus current availability. No raw
record JSON is returned after lookup without the final source/recipient gate.
Dispatch's before_intent hook rederives current state, exact persisted draft and
action, current recipient policy, READ intersection and unique daily slots,
then inserts the exact deferred binding. FinalIntentTimeCheck covers all awaited
reads/flushes and recipient/source/grant/lease deadlines before M1 commit.
It also rejects a Bangkok-day rollover after binding preparation, so quota/day
identity cannot drift between before_intent insertion and actual issuance.
Root integrates the real one-permit worker; transport cannot be reached from
routes, decoded projections or a model tool alone. Provider status publication
requires actual known native receipt/provider identity and fresh current reader
authorization before and after bounded lookup. Native PG tests follow normal014
on the exclusively assigned notifications DB only.
