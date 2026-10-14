# Disabled owner notifications — implementation plan

Selected 2026-10-14 from SDD v0.2 §13 and NOTIFY-01/M5. This package is
contracts, deterministic rules and optional offline HTTP conformance. It does
not send email, install a scheduler, issue an M1 permit or prove live delivery.
Root owns integration, the additive schema and shared worker/API changes.

## Native trust boundary

The configured server resolver must load current owner membership, registered
recipient/sender policy, exact native subject state and complete source/artifact
reader intersection. It renders bounded plain text from those actual facts.
Raw recipient/body/status/count or decoded draft/receipt/acceptance values cannot
authorize a notification. Owner financial audit is not source READ. Completion
means current independently accepted exact work, with its receipt, protected
proofs, criteria and lineage; candidate pass, successful receipt or metric target
satisfaction alone is insufficient. Unsupported or unavailable facts are blocked.

`NotificationPolicy` is disabled by default. Optional registered digest schedules
select daily 09:00 Asia/Bangkok and Monday 09:00 buckets; no timer is activated.
Meaningful signals are pending owner decisions, changed blockers/failures, cap
exhaustion and major current independent work acceptance. Stable subject/state
identity coalesces repeat events; idle and unchanged observations create no new
email. Dashboard alerts survive missing configuration or quota/delivery blocks.
Routine issuance is limited to ten intents per Bangkok day; daily/weekly digest
buckets are separately deduplicated. Unknown attempts retain the consumed slot.
Routine projections deduplicate exact M1 action IDs and reject inconsistent or
second-action/same-draft records; repeated events do not consume another slot.
Only an explicitly registered major-work selection admits completion alerts.

Native issuance must use the actual signed identity and execute lease. Under the
CompanyControl-first transaction it rechecks current recipient policy, approval,
exact draft/action/resource/provenance, pause/ancestry/cancellation, lifetime
allowance and notification slot, then persists M1 intent plus the permanent
draft-to-intent binding atomically. A final fresh clock after awaited reads/flush
rechecks every prepared recipient/grant/source deadline. Only actual
`EffectStore.begin` issuance permits one adapter POST. Existing intent, lost
receipt, another worker, replay or provider-key expiry never creates a new send.
Protected byte/provider I/O stays outside the mutex. The configured native hook
is server code, never a caller-supplied authorization dictionary or callable.

## Declared interfaces

Strict immutable declarations in `nexus.company.notifications.contracts` include
owner recipient policy, native signal facts, draft/provenance, exact M1 attempt
binding, provider submission and delivery observation. Pure rules take declared
server snapshots; their output is an eligibility description, never a permit.
`NotificationSourceResolver` declares preparation and same-session current
validation. `NotificationDispatch` declares signed lease/action/draft dispatch;
its actual trusted publisher is intentionally absent until schema integration.

`ResendTransport(configuration, *, enabled=False, transport=None)` has bounded
`submit(payload, idempotency_key)` and `retrieve(payload, provider_id)` methods.
It is an infrastructure adapter, not an authorization service: only the later
trusted one-permit dispatcher may call submit. No company route, model tool or
worker calls it in this package. Fixed HTTPS host, one owner address, no redirect,
retry, batch, scheduling, CC/BCC, attachments, public email links or webhooks.
Transport test configuration uses `httpx.MockTransport` only. Tokens and provider
raw messages/bodies never enter returned errors or evidence logs.

## Required additive schema, deferred to Root

1. Immutable drafts: company/draft identity, meaningful trigger identity,
   template/policy/recipient bindings, canonical bounded payload/hash, provenance,
   native operation/audit IDs and recorded time. Permanent trigger uniqueness.
2. Immutable event links: exact native event identity/sequence linked to the
   coalesced draft; repeated input event cannot produce another draft.
3. Immutable dispatch bindings: one draft to one exact M1 action/intent/run/fence,
   payload/idempotency key, recipient policy and Bangkok issuance day. Query issued
   routine bindings under CompanyControl for cap enforcement; no midnight refund,
   counter reset or second intent after uncertainty.
4. Immutable delivery observations: exact dispatch/provider identity, safe
   last-event/error category, observed time and bounded-response hash. Provider
   acceptance and delivery are distinct; billing remains the M1 ledger's concern.

All need company-scoped native FKs, explicit null/enum/hash/length checks,
append-only guards, forced RLS and covering scoped indexes. Draft/event/intent
publication and native cursor acknowledgement must be one transaction. Delivery
polls append observations only after current recipient/source qualification.
The notifications DB must be explicitly created and handed over before tests;
normal company Alembic only, no `create_all` or `stamp`.

## Resend primary-source research, checked 2026-10-14

- [Idempotency keys](https://resend.com/docs/dashboard/emails/idempotency-keys):
  POST keys are 1–256 characters and retained 24 hours. Same key/payload returns
  the previous result within that window. Changed payload conflicts; concurrent
  use can report an in-progress conflict. Permanent local dedup is mandatory.
- [Send email](https://resend.com/docs/api-reference/emails/send-email): a send
  response identifies the accepted email. It does not independently establish
  delivery. This adapter uses only sender, one recipient, subject and plain text.
- [Retrieve email](https://resend.com/docs/api-reference/emails/retrieve-email):
  lookup requires a known email ID and reports `last_event` plus message fields.
  No idempotency-key-to-ID recovery API is assumed. Unknown without an ID remains
  unresolved; lookup never sends another email.
- [Email events](https://resend.com/docs/dashboard/emails/manage-emails): delivered
  means accepted by the recipient's mail server, not human reading/inbox placement.
  Delayed delivery is retried by Resend (documented up to 14 hours); Nexus must not
  duplicate that message. Suppressed, bounced, failed and complained remain
  distinct. Open/click tracking alone is not used as independent delivery proof.
- [API errors](https://resend.com/docs/api-reference/errors): a send-only restricted
  key cannot perform retrieval. Credentials/domain permissions and quota failures
  are configuration/provider blocks. Timeout, 5xx, malformed success or concurrent
  idempotent conflict are conservative unknown send outcomes with no auto-retry.

The implementation will not copy provider recommendations to retry ambiguous
POSTs into Nexus's one-call policy. Later explicitly authorized configured live
tests must prove acceptance and delivery/reconciliation separately.

## Planned offline qualification

Tests first: immutable exact-company/hash/provenance shape; meaningful/idle/change
coalescing; registered optional digest due buckets and Bangkok quota; current owner,
recipient/source authorization and final expiry declarations; one mock HTTP request,
exact key/body, no redirects/retry; accepted versus delivered/delayed/bounced/suppressed;
timeout/concurrent/5xx/malformed response unknown; exact known-ID content binding;
missing configuration disabled; permanent replay semantics beyond provider retention.
No result here claims a native outbox, M1 issuance or live M5 operating cycle.
