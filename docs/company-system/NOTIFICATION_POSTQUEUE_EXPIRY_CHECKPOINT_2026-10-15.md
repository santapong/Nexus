# Actual postqueue expiry rollback

Checked2026-10-15 against the frozen NEW3 fixture/test package117b9d8d29e94cfd
313b91bfcebb29722c78fffd661421d3bd61b7d05080dec4. Production enqueue/scheduler/
identity/approval source is unchanged. A staged public source/sender/draft/pending
action receives one genuine original deadline after setup: public target OWNER
READ10s, verified signed credential10s, or original public near-expiry approval
(issued actualnow-24h+10s using the existing fixture technique, never updated).

Actual3restricted-PG cases passed3/49.78s with no correction/retry. The wrapper
awaits the unchanged public enqueue, then observes authorized consumption,
positiveHELDUSD0.010000/nullactual, permanent exact dispatch and canonical ENQUEUED
DBOSinput in the same uncommitted transaction. Only after those observations it
reads the real before clock, waits<=15s across the original deadline and reads
the real after clock. Native checks deny with exact source/credential/approval
errors. Each hook runs1 and actualbefore<expiry<=actualafter is exported.

Before/after native ledger equality proves original immutable approvalSHA/dates
remain unconsumed, draft/source identities unchanged, hold/dispatch/queue counts0,
effects/attempts0 and all five work counters0. Safe credential issue/expiry dates
are exported without tokens. Root independently verified all3 unique proof
exports and clocks; pytest current-directory aliases are not additional cases.
Root strict3 passes. No worker/transport/provider call occurred.

The public cancellation and positive enqueue proofs remain separate receipts.
Queue-input/ambiguous-action conflict cases and actual durable notification
dispatch/process recovery are next gates; recurring sender lifecycle/cost/billing,
production credentials/email and full supervised release remain open.
