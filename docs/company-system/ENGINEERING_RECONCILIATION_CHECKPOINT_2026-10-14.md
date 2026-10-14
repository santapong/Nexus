# Protected engineering reconciliation

Checked 2026-10-14. This slice adds a separate recovery path for already issued,
succeeded author and verifier actions. It does not complete the durable worker
or the release.

`EngineeringAcceptanceRecovery` requires the current reconcile lease, unpaused
active actor, approved author/verifier edge, actual succeeded receipts, exact saved
specifications and protected result/witness. It counts all succeeded author
identities before selecting the unique builder action; missing journals and
ambiguous or incompatible identities deny. It recomputes the mechanical checks
and publishes immutable proof/acceptance under CompanyControl, rechecking current
source permission and final deadlines after the last awaited work lookup.

Exact replay matches the original protected acceptance. Recovery creates no new
effect, attempt or cost reservation, and does not refund unknown billing. The
existing execute-only publisher, generic builder runner and M1 states are unchanged.
The typed worker result describes resolved receipt/proof/verdict identities; it
cannot authorize an effect or turn caller status into acceptance.

Actual restricted normal015 PostgreSQL checks passed in three separate calls:
same-dispatch reconciliation/replay and stale-fence denial (1/12.90s), current
pause/member/source/fence denial (4/30.51s), and proof READ expiry after the final
await with rollback (1/17.32s, nominated delay count1). These use two real tiny
Podman builder actions and preserve their counters and positive unknown holds.
The optional fixture dispatch reservation invokes the actual public permanent
dispatch helper; it does not establish DBOS enqueue or process recovery.

Root hash-verified the nine-file snapshot and ran the combined committed unit
suite: 1,680 passed/18.10s, 19 existing warnings; strict mypy, Ruff and format on
all nine files passed. Two subsequent test-only comments explain cohesive scenario
size exceptions; behavior is unchanged. The original source manifest is
[engineering-recovery-scope-1.json](/mnt/data/nexus-implementation-evidence-2026-10-14/native-builder/engineering-recovery-scope-1.json).
Root's final file manifest and logs live alongside it.

Actual durable worker execution, five process-kill barriers and real unknown/
failed/ambiguous issued-basis integration cases remain open. A separate drafted
worker test found and corrected a lease leak after source resolver failure; that
worker is outside this committed qualification. Full StockFlow, ARM64, live models,
owner/email UAT, independent disaster recovery and release gates remain required.
