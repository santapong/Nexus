# Disabled native notification dispatch — bounded plan

Root approved this next package2026-10-14 after the separate native draft freeze.
It uses actual existing registered current-owner work and approved M1 actions.
It creates no task/approval, sends no real email and activates no worker/timer.
Non-owner notification-worker admission remains unsupported until the actual
actor/recipient intersection loader is independently reviewed.

Exact proposal tool `company.owner-notification.send.v1`, version `v1`, fixed
configured resource; parameters contain only draft_id, payload_sha256 and
recipient_policy_sha256. Existing NotificationProposal checks that shape.
Actual native action/work/run/trace/actor/registration/catalog/policy/prices,
approval/hold and source checks remain mandatory. Decoded drafts, EffectStart,
receipts, approval flags or provider IDs never supply a call permit.

The new server before_intent hook, inside the caller's actual EffectStore.begin
transaction, loads the immutable draft and genuine event, rederives current
source/proof/recipient facts, verifies the exact approved action and existing
current-owner execute lease, and checks permanent draft/action identity and
Bangkok routine quota. It inserts the deferred exact dispatch binding atomically
with M1 intent. All prepared source/grant/recipient/lease/policy deadlines and
the actual issuance day are checked again after awaited writes at the final DB
clock. The private recipient file is rechecked as actual server configuration,
not inferred from membership. Source/provider byte I/O stays outside the mutex.

Only actual new EffectStore.begin permission reaches one bounded adapter POST.
An existing draft/intent returns reconciliation state; provider24h retention,
new operation/run/fence/day or another worker never permits resending. Disabled
or missing configuration blocks before intent. POST uncertainty has no providerID
and retains M1 hold/attempt; it never calls GET or POST automatically again.
Acceptance is an actual provider submission response, not delivery or work acceptance.

Known provider responses bind exact stored payload, recipient policy and permanent
idempotency key through actual M1 receipt/action identity. Submission, delivery
and explicit reconciliation append immutable safe observations with response/
record hashes. Polling requires actual known native receipt/provider identity and
current signed owner/source/recipient qualification before and after bounded GET.
Returned provider content must match the stored message exactly. Status has no
approval, spend, cost-refund or goal-completion effect; unknown bill remains unknown.
An owner-supplied verdict/providerUUID alone cannot reconcile an uncertain send.

Tests first on exclusively assigned notifications DB through normal014: disabled/
wrong owner/missing actual action; exact approved lease/intent/slot; full same-txn
rollback on trace/fence/hash/kind/day/cap/source/recipient mismatch; final expiry
after real flush; one offline HTTP POST and no second POST on replay beyond24h;
unknown/known receipt conservation; wrong provider ID/content; accepted versus
delivered/bounce/delay/suppression; source/member/recipient revoke and post-lookup
expiry; immutable observation/reconciliation replay. HTTP uses explicit mocks only.

Source10-file draft freeze and its historical failure receipts remain unchanged.
Root owns genuine failed receipt emission and normal015; checker owns strict
native state/read_event/emitter contracts. Atomic cursor acknowledgement, other
meaningful events/digests and configured live/private operational gates remain
separate mandatory NOTIFY-01 requirements. No complete M5/release claim follows
from this plan or the current partial store checks.
