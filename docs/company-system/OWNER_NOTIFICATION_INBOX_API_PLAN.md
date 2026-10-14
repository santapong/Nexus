# Optional owner notification inbox API

Scoped plan2026-10-14. Read-only owner list/detail; no email, provider polling,
worker, timer, cursor acknowledgement, decision, budget or UAT process changes.
Root owns optional company_app mounting; omission leaves these routes unmounted.

New ABI: NotificationApiServices(directory,inbox=None), and
NotificationInboxStore(factory,QualifiedNotificationDraftStore). Explicit configured
store only. GET /api/v2/companies/{company_id}/notifications accepts after_id UUID
and limit default4/max8. GET /{draft_id} reads one native draft. Existing signed
UUID identity/current directory owner scope and one CompanyControl transaction
protect every request; owner paused audit is allowed. No nested get_current calls.

The store selects only native IDs/recorded timestamps under exact company/current
recipient owner. Ordering is recorded_at descending then UUID descending; cursor
must resolve an actual scoped owner row. It calls stable get_current_locked in the
same session, reads up to one latest stored provider observation per submission,
delivery and reconciliation kind, then qualify_current_batch_locked before return.
The final awaited DB clock is followed by current recipient-file checks and every
saved source/freshness deadline. Any stale/private/expired/recipient loss hides the
entire page/detail; no partial bodies, per-source reasons or raw exceptions.

Response derives directly from NotificationDraft and recorded
NotificationProviderObservation. Work acceptance remains draft.signal.acceptance;
provider submission acceptance and recorded delivery are separate typed observations.
Absent observation means no stored observation, never proof of no send. Unknown
submission/billing are not zero or delivered. The API performs no provider GET and
never constructs a permit, receipt, allowance or completion. Observation JSON/hash,
redundant native columns, dispatch/M1 receipt binding are checked before inclusion.

Server bounds: max8 returned entries, at most9 queried metadata identities and3 latest
observations per entry,30s total timeout,2MiB serialized page/detail. Oversize or
qualification failure produces a safe generic unavailable response; no truncation.
No source body is decoded into API DTOs before current locked qualification.

New owned modules: inbox_contracts, inbox_observations, inbox_store/read helpers,
api_services, api/company_notification_routes; focused tests/support only. No
checker-owned qualified store/contracts/event_store edits, shared migrations,
frontend or root documentation edits. Root integrates optional DI after public ABI.

Tests use exclusive notifications DB with normal015 restricted application role,
actual signed HTTP tokens/current directory and public native draft publication.
Meaningful cases: default unmounted/unconfigured, owner/member/expired JWT/wrong
company, exact native schema and current read, accepted versus delivered/unknown,
source and recipient revoke/expiry, identity loss after lookup, final-await clock
crossing hides all bodies, paused audit, UUID/cursor ownership/limit/order bounds,
unknown detail and safe errors. No raw operative pass/receipt seeds or live email.
Capture source snapshot while shared qualified store is stable and preserve failed
receipts. This slice does not complete NOTIFY-01/M5 or release acceptance.

Cursor amendment: the scoped anchor is one of the queried identities and must
pass the same current source, owner, recipient and final-clock barriers as every
candidate, even when the next page is empty. With a cursor, query at most8
candidates so anchor plus candidates stays within9. A cursor page of8 candidates
may return a conservative next_after_id that leads to an empty licensed page;
this field is a continuation token, not a claim that more notifications exist.
Keep skipped obsolete rows and the lookahead in the final licensing barrier.
