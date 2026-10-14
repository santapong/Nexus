# Qualified native notification drafts and atomic cursor

Local implementation 2026-10-14; Root approved the bounded shared changes. This package
uses the frozen native fact reader/emitter (33 unique checks) and leaves the
committed old native loader/renderer behavior intact. No transport, timer, live
sender/recipient configuration, owner impersonation or provider is activated.

## Contract compatibility

NotificationDraft gains routine/daily/weekly kind and due_bucket/scheduled_for.
Default routine and None values are excluded from both Python and JSON model
serialization, preserving the exact prior canonical payload and SHA. The signal
gains digest_due plus optional native digest binding and actual company budget
date. Non-digest and old signals exclude new None metadata. Golden prior JSON,
canonical JSON, trigger SHA and record SHA are captured before the shared edit.

NativeDigestBinding keeps actual report ID/full saved-report SHA, registration /
policy SHA, daily/weekly kind, canonical Bangkok09 bucket and scheduled instant.
It contains no owner/recipient/permission. NativeDate remains exact. Native fact
reader must rederive actual saved report/registration/full source scope; the
binding is not an acceptance or send permit. Signal/draft kind, subject, policy,
bucket and schedule must agree. Existing major completion and actual protected
WorkAcceptance proof gate remain unchanged; metric/candidate/receipt is not goal
completion.

## New adapter/store ABI

QualifiedNotificationFactAdapter extends the existing loader interface, delegates
old receipt/accepted facts unchanged, and routes four native kinds through the
frozen NativeFactReader. It returns actual current source state and complete
provenance, never a model/caller hash/text/status claim. Rendering remains pure;
new digest content uses the actual saved projection, original observed dates and
explicit unknown billing. Old rendering remains byte-identical.

QualifiedNotificationDraftStore uses the existing loader/recipient/policy shape
for subsequent dispatch compatibility. publish_locked(session, actualCC, scope,
identity, actualEvent, pinnedRecipient) resolves, renders, persists/links/coalesces,
then rederives current sources and final recipient/owner/deadline gates in the
same transaction. Async recipient preparation occurs outside the company mutex;
the exact configuration pin is checked inside. Public persistence is shared with
old store delegation so native histories cannot fork into a duplicated writer.

`get_current_locked(session, actualCC, scope, identity, draft_id)` returns a current
NotificationDraft or None for missing/licensed obsolete records. Proven obsolete
state is body-free only after the saved artifact/resource/source-head provenance,
current signed owner, exact registered recipient and old/current deadlines have
been qualified. Private, expired, changed policy, unsupported or unavailable
configuration remains an error; no generic exception becomes absence.

`qualify_current_batch_locked(..., drafts)` rederives every visible body and checks
exact equality. `qualify_visited_batch_locked(..., draft_ids)` licenses all bounded
queried IDs, including skipped obsolete rows and pagination lookahead, and returns
deduplicated captured source/grant/recipient deadlines. These dates are descriptive
time witnesses, never cached authority. Inbox callers recheck the actual immutable
recipient pins for all visited rows and compare those deadlines synchronously at
their final fresh DB clock after every awaited observation/metadata read. Native
current owner/source and FileOwnerRecipients errors propagate: both
NotificationUnavailableError and RecipientConfigurationError are safe unavailability.

## Atomic consume and safe disposition

BrainEventStore.consume owns the single company transaction. A new handler calls
publish_locked and links/coalesces each draft before cursor acknowledgement. A
narrow optional finalizer runs after the final cursor flush, defaultNone retaining
old behavior, and checks current owner/recipient and every captured protection
deadline against fresh DB time. A late failure rolls back drafts, links and cursor
together, including earlier successful items in the same bounded batch.

Disabled/unconfigured/private actionable facts block with only safe event ID and
reason; they do not acknowledge the event. Unrelated nonnotification kinds are
explicitly ignored and reported. A rederived obsolete native state can be explicitly
acknowledged as obsolete with no body; it is never mistaken for published work.
Even when no draft was previously published, this acknowledgement qualifies the
actual historical work charter/source/receipt inputs or registered saved report.
The finalizer requalifies obsolete subjects after cursor flush and checks every
captured deadline. Unsupported digest configuration cannot masquerade as obsolete.
No broad ValueError catch may convert private/missing/expired actionable inputs
into silent acknowledgement. A returned batch receipt distinguishes committed
dispositions from rolled-back attempts.

Dispatch currently remains routine-only. A later explicitly owned amendment must
use actual draft kind and registered digest bucket/quota while preserving the
permanent one-draft/one-intent slot, clocks and no resend after uncertainty.

## Tests and scope

Tests first: exact old wire/canonical hashes; strict new digest/day/NULL shapes;
actual pending/block/cap/digest facts and current owner/source intersection;
actual old loader delegation; replay/changed policy/obsolete/disabled behavior;
two-item rollback and interrupted link/cursor; natural source/recipient expiry
during final cursor flush; no M1 counter, hold, receipt, dispatch or model mutation.
Only exclusive native_events DB normal015, restricted role, normal teardown;
no schema edit/create_all/stamp. Old014 loader proof remains separately frozen.

## Local evidence and integration limit

Final focused matrix: 28 checks (17 restricted PostgreSQL cases and 11 unit
checks), 185.07 seconds. Strict types, Ruff and format checks pass for 26 scoped
Python files. Exact earlier routine Python/JSON/canonical SHA goldens remain equal.
Separate old008 event-only / old014 real-ingestion compatibility and current
company-cap receipt: three checks, 10.45 seconds. Full old008 ingestion remains
excluded because of its pre-existing012 artifact-mapper incompatibility.

Evidence and exact source hashes are in
`/mnt/data/nexus-implementation-evidence-2026-10-14/qualified-notifications/`.
These receipts qualify local draft/link/cursor and body-visibility behavior.
They do not qualify live delivery, daily/weekly dispatch admission, transport
exactly-once execution, a production timer or goal completion. Root owns coherent
integration and independent shared-boundary review; inbox API evidence belongs
to its separately owned package.
