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
