# Current-host bootstrap qualification — 2026-10-15

The corrected fresh normal probe passes in **1.20 seconds**. It captures actual
systemd262 parent/kernel limits, two owned live process trees, a29-byte stream,
runtime reaping and removal of only its sealed container ID. All28 query replies
complete and are reaped; original parent identity/deadline and numeric caps remain
unchanged. Later read-only checks find the unit/cgroup and all original PIDs absent,
with the same20-container inventory.

The separate fresh timeout probe **fails qualification** after16.57 seconds. Three
stopped inspections report exit_code=-1/non-OOM, conflicting with the frozen137
expectation. The validator rejects this. Output is empty; exact-ID cleanup and
runtime reaping succeed, and later absence/inventory checks corroborate cleanup.
The runtime CLI exit, stderr, launch/read-end measurements were not retained by
this operator, so the complete failure cause is unknown. It is not a timeout pass
or proof of parent timer kill.

| Probe | Outcome | Preserved evidence |
| --- | --- | --- |
| Original261-only normal | Failed before parent/container | Historical source and namespace retained |
| First fresh262 normal | Parent checks pass; image template fails before spawn | Actual Podman Go field .ID differs from .Id |
| Corrected fresh262 normal | Pass;1.20s |29-byte output, owned process/cleanup records |
| Corrected fresh262 timeout | Failed;16.57s | Three stopped -1 inspections; cleanup succeeds |

The image template correction has an exact-argv semantic red based on a saved
actual read-only image query, then54 mock tests/static checks. Its fresh frozen
source has1,583 files and independent source review. Earlier sources, failed
namespaces and unused old timeout packets remain preserved; no original retry.

| Receipt | SHA256 |
| --- | --- |
| Fresh source | `c3a17917abc3b03dfab8a9187ca2520dcfab65ca2032b6ae4cd7e6393728269e` |
| Actual normal report | `3843095f49dd0fbdbaae937e1debf10c97458c056a01b2eb50167a3ae13fc24b` |
| Independent normal audit | `d2210cc9efa6d98e64c654c78f8c0dfd8fbc68f2d4c4ce322f978c52c48877d1` |
| Actual timeout report | `26eb358aafb9877d8994fec43132f647aebc8dc87bb541bff16ef562d5a415e5` |
| Independent timeout audit | `b96ffc89b8b20999c6f4566f39dda23ec3dcbb9508817b2bba73567e7838b495` |

Next is a concrete source/diagnostic plan for this engine's timeout metadata,
retaining the missing bounded measurements before validation/cleanup. No frozen
expectation is relaxed and -1 never becomes completed work. Full517 dependency
bootstrap, opaque Company-issued context/current full V7, actual StockFlow E/EV
and supervised release remain unqualified by these tiny probes.
