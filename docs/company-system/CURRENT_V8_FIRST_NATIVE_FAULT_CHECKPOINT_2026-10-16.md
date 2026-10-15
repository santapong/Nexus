# First current-V8 native fault attempt

Checked 2026-10-16 (Asia/Bangkok). The first actual parent-expiry attempt fails
before a usable fault witness. The five-case wave is stopped; cancellation,
pause, READ revocation and stale-fence cases remain unissued. This attempt does
not qualify parent expiry, native containment or the supervised release.

The preceding [all-five setup](CURRENT_V8_NEGATIVE_FIVE_CASE_SETUP_CHECKPOINT_2026-10-16.md)
and its metadata-only first packet remain valid historical observations.
Source4, namespace3, its original approvals/windows and all earlier failed
namespaces are preserved. No issued action is retried or refunded.

Root releases the exact pinned E3 entry and packet after fresh read-only checks
of the same 21-container inventory, image, manager, runtime binaries and target
absence. Controller 60s, parent 45s, stop 1s, pre-bootstrap age 30s, command 10s and
job 25s remain unchanged. The external termination limits are 65s/70s.

Actual E3 execution runs from 21:59:04.184832 to 21:59:43.245135 UTC on
2026-10-15, taking 39.060138 seconds and exiting 1. The outer capture wrapper
exits 0 because its recording work succeeds; that is not the case result.
The report records first `ValueError`, no observer or saved case ledgers, and
one reaped scope child with exit 0. All recorded owned tasks settle.

Private control directory:
`/home/santapong/.codex/nexus-n-parent-expiry-actual-release-20261016-3`.
Release freeze2 SHA-256:
`6751edc91a486d729347ce8f6a4f77638eb7bde2728ad36cbc7c81b9b933487c`.
Actual case terminal SHA-256:
`aa12eb396a920979e71373cc09cd9abe6bcab8f2773e4d1196ee7e1c203567ec`.
Complete case stdout, 423B, SHA-256:
`ec8652d0ca1efc9e049fc8c2237ad4a6913d536ec69fa2917cc6fbe3cde016c5`.
Complete case stderr, 95B, SHA-256:
`5fb264a6b798ffc2f29fbb9d7b5006ff4c85b9be5d9b959e99e2ead5e76da4d4`.

The retained native result proves issuance and an unknown outcome. Raw same-call
diagnostics reach sealed-container discovery: one complete fixed inspect observes
the actual running container and records its identity. Sampling then fails with
`ValidationError`; no sample is retained. Finalization reports `unproven` and
`no_samples`. The saved result has no commands, artifacts or logs and retains
`business_readiness_unproven` and `host_containment_unproven` limitations.

Retained result SHA-256:
`0256e60da7b788695c307b9abb0afe455acd3b1b5baddcf7f57d090f03edd8ff`.
Raw diagnostic SHA-256:
`8e87417e5e8a3f69751b2b1bd4d65177ed0de938819e982fc358c5941456b8c4`.
Final diagnostic SHA-256:
`8e55bdf37d3d4e58973dd092092583a0ec917e4e01467c685fb2011c7dfe2ec2`.
They are under namespace3's `parent-expiry/results` and
`parent-expiry/sidecars-diagnostics` directories. Original validation fields,
parent wire and collector command capture are not present in these retained
records; the exact original failing validator cannot be reconstructed from an
error class alone.

The independent read-only repeatable-read database audit observes 477 rows, one tool attempt and one
`outcome_unknown` intent, tool usage 1/model usage 0, the author's work at fence 2
with no worker or lease, and its USD0.010000 reservation `UNKNOWN` with null
actual billing. No completion receipt or verification exists. The other four
reservations remain held and their actions unissued. All 74 table projections
for each of the other four companies and all other 14 work rows match the original
setup exactly. Only four tables change for the licensed footprint. The bounded
audit completes in 1.170297s and rolls back its read-only transaction; no second
snapshot is taken. The database-clock read bracket is 0.237102s.

Actual audit:
`stockflow/n-negative-parent-expiry-first-case-actual-file-audit-1.json`, SHA-256
`7ab0103baf18e909bd6bf3877a09161338f761ed65489375d0d335899dfd6f4d`.
Its pin manifest has SHA-256
`ce6c0a15877b0c2f82c34bc6e253f3de433f421fd1af05a4a6166cbaf704b871`.

A later read-only host check finds the exact container stopped with PID 0 and
exit 0, the scope not loaded, and the recorded collector/runtime PIDs absent.
That later state cannot supply the missing original process tree or retirement
clocks. The stopped container is retained. Post-check receipt SHA-256:
`0a309ac3c7ca04071ce8242469f080e2418af5e9ab4760c2ed974f8b683716ad`.

There is no physical fault/before/after/terminal witness or issued/post-stop
ledger. The existing recovery entry's required witness inputs are absent;
no synthetic inputs, metadata reconciliation, allowance reset or execution retry
is performed.

The corrected source-only diagnosis has SHA-256
`50a245815b904d30058d00fa75cd7ab2d813236e02e777d13f90cddaddfec6a1`.
It distinguishes the observed shared observation end from an unretained original
parent deadline; the timing hypothesis remains conditional. An earlier draft's
unsupported deadline attribution is explicitly retracted and preserved as
superseded, not promoted into evidence.

Root's prospective timing/observation plan has SHA-256
`953e8da2ea4961af8695edea5d4092a6bb9be24228440d45c0ef591f0a4e2199`
at `stockflow/current-v8-negative-fresh-timing-observation-plan-2026-10-16.md`.
It permits source-only work: retain first safe failure metadata and the actual
owned collector capture; add timing admission before a future claim/effect; and
use a fixed 36s pre-bootstrap age only in an independent fresh namespace.
Original timer/oracle thresholds stay unchanged. Source implementation, fresh
setup and a separately frozen actual qualification remain distinct next gates.
