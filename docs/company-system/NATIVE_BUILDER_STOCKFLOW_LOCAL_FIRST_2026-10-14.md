# First nominated StockFlow local native run

The one reviewed amd64 run produced a real failed native receipt. Offline
dependency resolution and typecheck passed. Vitest stopped at startup because
the isolated environment could not resolve `localhost`; no test assertions,
build or post commands ran. This proves useful bounded execution and identifies
a loopback-hostname preparation gap. It does not prove engineering acceptance,
current StockFlow business readiness or ARM64 qualification.

The packet was the exact frozen `node-runtime-freeze-v1.json` and prelaunch v2
SHA256 `320a09aa1c897de63188787b71615430b5d83e6f4b1c27c1dbd5f9df18ce025e`.
Native M1 claimed the same registered task and issued one intent for the persisted
approved action `d721a60e-1db1-4d95-a3be-1620a9c402b1`. Its historical source is
commit `bb7cc00848bb650069543e843f826703d468058c`, dated2026-09-01T13:56:41+07:00.
No checkout edits or engineering patch occurred.

| Phase/command | Actual result | Time |
| --- | --- | --- |
| Baseline offline frozen install | exit0 | 5.684s |
| Baseline web typecheck | exit0 | 15.707s |
| Baseline web test | exit1; `getaddrinfo EAI_AGAIN localhost` at startup | 1.034s |
| Build and all post commands | skipped after baseline failure | unexecuted |

Actual kernel values were memory.max4294967296, cpu.max200000/100000,
pids.max256. The native lifetime counters show model0/tool1/rework0/revision0,
and there is one actual attempt row. The intent/receipt state is failed.
The two$0.01 reservations remain: unused generic setup held, issued Node action
billing unknown. Actual USD is null for both; no refund/counter/history rewrite.

The protected current result summary is artifact revision
`83d90e0d-3e8a-5667-bae9-54462bf827b9`, SHA256
`5ada3dae7b153bc4c735e4dff0b558d49c99eec94ead10e0cf8ea79a15327f87`,4069bytes.
Its exact protected bytes/native receipt/input READ and freshness were checked
through current public services. The full saved result SHA256 is
`861ae1b8ba91a935619c8bc76bdbdc72f9dd70c80733dc976be0d6f6bf764195`.
The exact owned container `nexus-builder-d0c19bb7f57e51b7a8bb6c08cdcb9cb9`
is absent (`container exists` exit1); no shared prune or extra project process.

The test-only collector initially used a two-part CostHold key, but that legacy
table's primary key is action_id alone. This happened after the actual runner
saved/published/recorded/cleaned its result. The original frozen code and failure
log remain. The one-line collector correction and a separate read-only collector
passed strict types; no project command/action was reissued to recover evidence.
The prepared source manifest remains historical; an explicit amendment records
this collector correction and the new read-only helper/doc.

The prospective hostname correction is a Node-only task-owned read-only hosts
file with solely127.0.0.1/::1 localhost, still network none and no host-machine
data. It must change the exact Node recipe/action pins and be qualified before
any new reviewed native run/budget slice. The consumed action/task remains
immutable; this first failure must not disappear behind another result.

Evidence under `/mnt/data/nexus-implementation-evidence-2026-10-14/native-builder`:
`stockflow-native-first-run.log` (original collector failure),
`stockflow-native-readonly-collection-first.log`, `node-runtime-freeze-v1.json`.
Private task files under `/tmp/nexus-builder-stockflow-native-20261014-v1`:
`first-run-receipt.json`, `baseline-test-diagnostic.json`, original saved result,
prepared state and both prelaunch versions. Worker/provider/Pi/deployment/email
activation and independent acceptance remain absent.
