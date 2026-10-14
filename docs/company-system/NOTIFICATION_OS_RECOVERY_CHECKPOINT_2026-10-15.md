# Notification OS crash and immediate recovery

Checked 2026-10-15 against local `ae7d9b5` plus the test-only source2 package.
This checkpoint qualifies mechanical local recovery with a synthetic sender.
It does not establish real email delivery, billing reconciliation or release readiness.

The frozen source2 package delegates actual intent, submission, receipt and
observation operations before pausing at the nominated barrier. Each case has a
new normal015 database and one real durable workflow. The controller kills its
recorded original PID, waits for it, then immediately starts the same command in
a second OS process. It does not wait manually for the old lease to expire.

| Barrier | Actual recovery result | Requests across both workers | Live observations / waits |
| --- | --- | --- | --- |
| Committed intent, before submission | Unknown; no receipt or observation | 0 | 24 / 24 |
| Accepted mock response, before receipt | Unknown; no receipt or observation | 1 original, 0 restart | 23 / 23 |
| Committed receipt, before observation | Submitted; original receipt, explicit missing-observation limitation | 1 original, 0 restart | 24 / 24 |
| Committed observation | Submitted; original receipt and observation | 1 original, 0 restart | 23 / 23 |

All four actual cases passed. Every case keeps the original command, action, segment, intent fence1,
source heads, approval and dispatch slot. One attempt/tool1/model0 and a positive
USD0.01 hold remain; actual cost is null and billing unknown. Current fence1→3
is released. A response diagnostic never becomes a fabricated native receipt.
An absent observation remains absent. Each restarted helper itself observes the
live prior lease using the actual database clock, then delegates the normal one-
second acquisition wait. The same original180-second synthetic credential is
passed through a transient inherited pipe; it is never renewed or persisted.

Restart evidence records zero HTTP, blob, draft getter and private draft-body SQL
reads. Owned SDK threads stop, the caller-owned engine is disposed, and a separate
read verifies zero app backends. Both owned child exits are retained. All case
databases, private trees, first failures and source snapshots remain preserved.

## Source and verification

Source freeze `473982f0` binds1,365 files,12 owned test files,14 unchanged
notification production/compatibility pins and6 logs. Root and independent review
verified the complete inventory. Source1 remains unlaunched. Source2 fixes strong
Popen ownership before start-identity reads, attempts cleanup for every child and
retains metadata errors without signalling a mismatched identity (ERROR-101).

The original coherent test run failed2 pure location assumptions with2,514 passes.
A unit-test-only amendment nominates the actually imported test tree/runtime for
mocked launches and adds explicit mismatched-source/runtime denial cases. The
actual source2 used by OS workers is unchanged. Root's corrected coherent suite
passes2,518 tests/24.36s with19 existing warnings; strict, Ruff and formatting12
pass. The source2 focused package separately passes42 pure compatibility checks.

Evidence is under `/mnt/data/nexus-implementation-evidence-2026-10-14/notifications/`:

- `phase5-notification-os-source-freeze-2.json` and the preserved source1 freeze.
- `phase5-controller-unit-location-amendment.json` retains the original failed log.
- `phase5-intent-root-terminal-receipt.json` binds actual intent proof `3d234c48`.
- `phase5-all-os-root-terminal-receipt.json` (`7026a083`) binds all four terminal
  handles, actual postconditions, complete artifact inventories and source preservation.
- Response proof `21b01ed0`, receipt proof `0c8c3c31` and observation proof
  `8bba63bc` remain in their exact private case trees.

Root handles51992/45975/49391/74468 all exited0. Separate post-run reads confirm
normal015, one SDK SUCCESS and zero app backends in each retained database. All
eight original/restarted child PIDs are absent after their recorded waits.
Independent artifact review recomputed canonical receipt hashes, matched the final
observation hash and original provider UUIDs, and verified raw live/wait markers.
The first live observation preceded expiry by26.318/25.685/25.490/25.346 seconds
across the four cases. This review performed no DB mutation or additional run.

Private roots are `notification-process-{intent,response,receipt,observation}-20261015-1`
under `/home/santapong/.codex/nexus-local-release-fixtures-20261014-continued/`.
Their exact databases use prefix `nexus_company_test_notification_process_`.
Never reset these cases or substitute an old accepted fixture for a new run.

Daily-positive digest, registration retention, real sender/recipient credentials,
owner browser acceptance and delivery remain separate gates. Full StockFlow,
contained builder/ARM64, live models, private deployment, disaster restore and
bounded soak are still required for the supervised release.
