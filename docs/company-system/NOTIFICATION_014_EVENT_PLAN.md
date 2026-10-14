# Additive014 notification ledger and native event coverage

Root owns the static normal014 migration, shared event/native unique targets,
complete metadata registration and actual schema qualification. Worker owns the
separately frozen disabled notification contracts/HTTP adapter and proposed four
table models. No notification database is migrated before the model freeze and
Root schema handshake. Old company001–013 migrations remain unchanged.

## Required actual event coverage

Preserve existing source/ACL/claim/derivation/receipt/verification events. Extend
the current ID-only BrainEvent contract/store with four native kinds:

- decision_required: actual pending JournalAction and its canonical proposal/state.
- work_blocked: actual registered ExecutionWork/current plan/eligibility state.
- cap_exhausted: actual company Bangkok-day DailyBudget or actual WorkBudget/task.
- digest_due: actual owner SavedOperatingReport and explicitly registered due bucket.

Add nullable native task_id, report_id, budget_day and native_snapshot_sha256
fields, with company-scoped FK targets and explicit per-kind NOT NULL guards.
Budget day is an actual date; a company daily-cap subject is company_id plus that
date. The snapshot SHA binds current native facts which must be rederived before
draft/publication/issuance. Every event uses an actual existing owner-provisioned
resource. Event IDs/sequence/dedup come only from append_event under CompanyControl.
New event IDs cannot be fabricated from a minute tick. Same native state/due bucket
coalesces; changed/current state is explicit. Existing six kinds remain readable.

Event DTO/record projection/append/replay comparison and native emitter all need
the new fields. The emitter takes selectors and trusted services, not caller
status/text/hash/owner flags. It loads the actual current journal/work/budget/
report and validates actual scope/resources before/after awaited writes. Old
profiles must remain usable for old event kinds when notifications are disabled;
qualification must cover version compatibility rather than assuming ORM columns
exist on pre014 installations.

## Ledger/native references

Install drafts, event links, dispatch bindings and safe provider observations.
Add scoped BrainEvent(company,event,sequence) unique target and exact EffectIntent
(company,action,task,trace,run,fence,attempt_kind,proposal_hash) unique target.
The dispatch FK is deferred until commit, so a trusted before-intent check can
insert its binding in the same transaction as the actual M1 intent. No separate
commit, receipt echo or caller permit flag is permitted. Only tool_attempts binds
an email attempt. Preserve one draft/one action/one intent forever; provider key
retention or midnight cannot create another send after uncertainty.

Four-table model checks include explicit SQL NULL branches, UTF8 payload/record
limits, exact provider acceptance versus delivery shapes, owner/issuer membership,
Bangkok intent day and full leading FK index prefixes. Force company RLS and
append-only histories. Content redundancies are checked against decoded exact
canonical JSON by native stores; these hashes confer no authority.

## Tests-first and handoff

Unregistered metadata tests must pass full FK indexes/native target shapes and
NULL-safe checks. Then Root fresh/repeat/metadata/downgrade against an exclusive
notification_schema DB, preserving unrelated legacy data/history. Restricted
tests cover event scope/sequence/kind binding, cross-company FKs, known/unknown
observation SQL NULLs, append-only/RLS, deferred exact intent rollback/commit,
model-request/trace/fence/proposal mismatch and actual query index use. Existing
Brain event behavior, old-profile compatibility and M1 tests remain unchanged.
Only after this gate does the worker receive normal014 on notifications DB for
actual draft/event coalescing/source/recipient/expiry/unknown tests.

Emitters and M1 one-permit transport integration follow the qualified schema.
Actual provider acceptance and delivery, source-safe owner UI, configured sender/
recipient, default-disabled schedules and authorized live delivery remain release
gates. Schema, pure mocks or a saved draft do not establish live notification.
