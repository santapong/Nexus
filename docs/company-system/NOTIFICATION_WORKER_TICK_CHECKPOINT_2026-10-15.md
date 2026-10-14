# Bounded notification worker tick

Checked 2026-10-15 Asia/Bangkok against base65c3a8f. Default-disabled read and
preparation composition is implemented and independently source-reviewed. Actual
PostgreSQL first-tick and sequential replay passed in the exclusively assigned
disposable DB (1case/8.08s); remaining composition gates are separate.

The tick uses a genuine sealed credential and exact immutable configuration,
qualifies the current native sender, emits configured facts, consumes one bounded
event batch and prepares at most one existing draft per tick. It does not approve,
authorize, dispatch, allocate new work or refresh attempts. Per-operation sender
windows join final source/recipient/credential clocks, including empty/ignored
consumer finalization. Scan progress is process-local and grants no permission.

Independent review found that dynamically resolved decision/failed-receipt facts
were not compared with the configured expected resource. A retained typed probe
failed2/1.55s by reaching the emitter; exact comparison now denies before emission
and the unchanged cases pass2/1.23s. Native READ remains required. Current non-digest
registration supports the configured single facts.resource; a different mapped
resource denies. This is a configuration fix, not proof of a disclosure bypass.

Frozen14 source files: worker-tick-static-review-freeze-2.json,
SHA5a8c914276cb4f5000be411e851b4c9a953c278caf7c6cea652318761e3b0da4
in the dated notifications evidence directory. Independent reviewer verified all
source and retained log hashes. Author72focused/2.02s and Root21/1.27s pass. Root
strict14, Ruff14 and coherent1,950unit/21.75s/19existing warnings pass on the exact
private snapshot. These are static/unit checks, not actual company operation.

Root authorized the agent to run only the existing first actual PG
positive/sequential-replay case:
distinct native engineering source and owner sender, no models, pending/unapproved
actions, exact persisted draft/payload/recipient pins and zero holds/intents/dispatch
/counters. The frozen test passed1/8.08s on the qualified local runtime; actual
normal015 restricted-role setup and owned teardown are included. Concurrent replay, final-await expiry rollback, recursive self-wake
cursor denial, page/restart fairness and protected digest composition remain open.
No owner UAT, live email, daemon, queue or release activation accompanies this code.


## Actual next matrix — 2026-10-15

Frozen NEW6 tests/support on committedbe252d6, SHA141d00688f5705ecc1ea54b9f47b10cec
3bcb15b8002ac4b5f323ef66a3967ee, independently source/hash-reviewed. Root strict6
passes; author strict/Ruff/format6 and exact5-case collection pass. Actual normal015
restricted-app batch passed5/59.21s with no source correction or retry:

- Two simultaneous worker objects aggregate one actual wake/draft/pending action.
- Empty and ignored consumer batches capture a real public sender-only10s READ
  deadline, cross it at the delegated final SQL clock and roll back unchanged
  native cursor/publication/journal/effect/counter state; each nominated hook runs1.
- A public fully qualified sender decision wake denies after native admission with
  unchanged cursor and no recursive draft/action.
- Three public source wakes/drafts with max_candidates1 prepare all exact pending
  actions through one new-worker restart and bounded page cycles. Actual visited
  licensing includes anchor/lookahead; later cycles stay quiet.

The initial14 source hashes and first-PG receipt stay unchanged. These are public
synthetic read/preparation proofs only. Digest composition, repeated-restart
fairness, licensed obsolete combinations, durable dispatch/process recovery,
production credential/timer/email and operational release remain separate.


## Actual protected digest composition — 2026-10-15

Frozen NEW3 tests/support SHAeed40358ba422f909c7f029b8a637765f2ec04bda4cbe7ab
28a2fbca3134a525 qualify an actual owner-saved operating snapshot with a real
registered engineering author/verifier edge and nonempty protected baseline source
references. Empty models and unapproved actions remain; the snapshot does not
assert accepted engineering work, receipts or business completion.

Both actual normal015 restricted-PG cases passed2/12.55s, no correction/retry. At
2026-10-14T19:17:07Z the weekly bucket weekly:2026-10-12 was due: one native digest
wake/draft/link/pending sender action, exact report/registration/policy/source/
recipient pins, then unchanged immediate replay and new-worker restart. At
19:17:15Z (02:17 Bangkok) daily was not due: quiet/no occurrence/draft/action.
That daily case is honest no-due proof; positive daily remains pending until a
real eligible clock. Root strict3/statichash checks pass; all earlier sources
unchanged. Digest expiry/stale report/old-registration retention/rollover and
transport/durable operation remain separate gates.
