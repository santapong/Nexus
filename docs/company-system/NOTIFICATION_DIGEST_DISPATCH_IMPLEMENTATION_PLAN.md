# Native daily and weekly digest dispatch

Approved bounded package, 2026-10-14. Default transport stays disabled. This slice
uses actual owner-approved registered sender work and the existing M1 lease,
approval, budget, attempt and one-call permit. It adds no task, allowance, approval,
grant, timer, worker or caller-selected clock. Tests use synthetic protected local
data and mock HTTP only, on the exclusive notifications database with normal015.

Existing models suffice. The immutable draft stores kind, due_bucket and
scheduled_for, and the dispatch foreign key binds exact draft content including
kind. NativeDigestBinding retains the saved report hash, registered schedule and
notification policy hashes. Qualified native publication/rederivation proves the
current registered policy, source closure and original saved report facts.

New dispatch_windows.require_dispatch_window(draft, policy, now) is a pure final
time check, not authority. Routine behavior remains unchanged. For daily/weekly it
requires the explicit policy flag and exact canonical policy hash, native kind,
bucket and scheduled instant. It compares these with the current canonical native
digest_window from an actual DB clock: today's Bangkok09 daily bucket or the
current Monday09 weekly bucket. Before-due, changed or expired bucket fails.

New dispatch_slots.reserve_notification_slot(session, work, action, draft, policy,
identity, now) inserts the existing immutable native dispatch row and returns its
actual Bangkok issuance day. Routine admission counts routine slots on that day
against routine_per_day. Daily/weekly admission joins actual dispatch and draft
rows for company, kind and exact due_bucket; any existing slot consumes the bucket
permanently, including rejection, unknown outcome or provider retention expiry.
Different policies/reports cannot reset a company/kind bucket. Daily, weekly and
routine slots remain separate. Same-company mutex and deferred exact intent FK
make the slot and real M1 intent atomic; no additional schema is proposed.

Only the approved narrow shared amendment changes NotificationIntentCheck._slot
to delegate and validate_time to retain the digest window check. Constructors,
managed specialization, fixed tool/resource and the three draft action parameters
stay unchanged. Existing final-flush and pre-HTTP checks call the same guard, with
current owner/recipient/source/target/plan/charter/model/approval/lease and day
qualification. A committed denial retains its permanent slot/unknown hold and
cannot resend. Recorded provider acceptance remains distinct from delivery and
work acceptance; no billing zero or completed business state is invented.

Tests first: canonical clock/policy/kind negatives; actual qualified daily/weekly
public wakes and owner-saved reports; actual managed approval/claim/intent with one
mock POST and exact replay; per-bucket denial across distinct native drafts;
separate routine quota; current owner/source/recipient/target/plan and final-await
expiry denial. Any multi-attempt test declares its bounded sender quota in the
initial public approved fixture plan, never tops it up after issuance. Freeze
source and dependency hashes, retain failures and actual teardown, and review this
package separately from timer/worker/live-provider NOTIFY-01 release requirements.
