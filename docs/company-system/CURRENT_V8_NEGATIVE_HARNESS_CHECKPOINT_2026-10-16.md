# Current-V8 fault harness and first setup attempt

Checked 2026-10-16 (Asia/Bangkok). This checkpoint records source checks and a
stopped setup attempt. No current-V8 fault case, Company action, Node process or
selected StockFlow execution was issued.

The five separate planned cases remain parent expiry, cancellation, company
pause, source READ revocation and stale-fence release. Each preserves one attempt,
unknown native history and its original timing limits. The first failed or
inconclusive case stops the wave; reconciliation cannot repeat an effect.

## Frozen source checks

Private source: `/home/santapong/.codex/nexus-current-v8-negative-source-20261016-2`.
Its 1,653-file backend retains all 1,620 baseline files from `be18432` unchanged.
`SOURCE_MANIFEST.json` is 349,073 bytes, SHA-256
`3b96eeeab6254596fd9d93ef48d271cc143b401bf150c7a35a23bbaddaaa2066`.

Root checks pass 273 focused tests in 7.61 seconds, configured nonsilent strict
typing across 38 files, and configured Ruff check/format across the same files.
A cold source check from `/var/tmp` reports no database or scope opened.
These checks do not establish actual fixture or native execution compatibility.

Independent boundary findings and finite forward checks corrected:

- Retention of the actual pending worker through cancellation and expiry.
- Final named-file observation after descriptor closure and root metadata reads.
- Complete migration catalog/security-set comparison without importing installers.
- Preservation of completed setup/native prefixes and the first causal error.
- Original deadline checks after final serialization and output flushing.
- Authority-report rejection when the collector exits with an error or has
  nonempty/incomplete stderr. Parent-expiry expectations remain separate.

All failed components, original counterexamples and intermediate source packages
remain preserved. Root source receipt: `ROOT_FINAL_SOURCE_CHECK_RECEIPT_3.json`,
SHA-256 `e8808e1fb366c5b7ee208c3ea04c22aa4afa4fbc7ab023857c2e2db53c95c17c`.

The static-check investigation also reproduced a narrower import-coverage result
with `PYTHONPATH=.` under mypy 1.20.2. Final checks explicitly unset `PYTHONPATH`
and use `MYPYPATH=..:.`; no silent imports or ignored migration diagnostics were
used. Runtime and pytest import flags have separate purposes.

## Actual preparation and stopped setup

Evidence directory:
`/home/santapong/.codex/nexus-n-preparation-command-20261016-1`.
The reviewed preparation recipe stages only fresh local public repositories and
inputs and creates one empty test database. No image pull or runtime starts.

Actual preparation completes with exit 0 in 0.855 seconds. All 38 commands have
their expected status, including five exact unit-not-loaded responses. Five
fresh fixture roots and their input hashes are retained. The original 21-container
inventory is unchanged; no existing container is removed.

Preparation terminal SHA-256:
`f61d01aee9f9c1a7aea4265334be3506af252eb5951346993f912e5a462c3891`.

The separately frozen setup runs from 20:37:24.502554 to 20:37:27.535200 UTC on
2026-10-15, then exits 1. Normal company migrations 001 through 016 complete.
The actual schema receipt records restricted application role privileges and
schema hash `07d2a0e827325385b82c3bdb1710a13f20785aa56b02c7c42ff2a1b87da3b455`.

The first company bootstrap and member registrations return, followed by the
first Brain source registration. A subsequent `ValueError` stops setup. The
retained output includes those five returned-call hashes, the schema receipt
hash, zero prepared/finalized setup results and zero pending tasks. The original
exception message/traceback is unavailable; the exact failure branch therefore
requires a controlled reproduction alongside the preserved database endpoint.

Setup stdout SHA-256:
`b0ceb8ed1afe2feece0f6359d568f1a8a43cc0f044377303ec87ff5573af5cce`.
Setup stderr SHA-256:
`caad43696a7db53d68f15175ba98b90ddb62975817526cddd5ff4c6778c262fc`.

An independent 1.118-second endpoint audit uses one bounded read-only repeatable
read transaction and rolls it back. It confirms the same normal016 schema hash,
restricted application role and enabled durability settings. All 74 tables are
counted: eight contain 14 rows from the first company/source registration. Work,
attempts, intents, holds, action journal and live execute leases are all zero.
The file audit verifies 1,653 source files, three operator pins, 76 command streams,
41 created roots, ten staged inputs and all five checkout/archive joins. No
launch packet or completed setup receipt exists. This confirms the stopped
attempt's scope; it does not turn failed setup into a qualification pass.
Audit: `stockflow/n-negative-setup-first-attempt-actual-file-audit-1.json`, SHA-256
`72812cdf91d289aba279c6d9f7dc9718655f660ef4808ffb36ed3d746290d7eb`, under the
dated implementation evidence directory. Its earlier local auditor syntax and
catalog-shape failures are retained; the final read-only transaction has its own
original finite bound and does not retry the setup operation.

The fixture reader compares an actual `SourceRecord` with its base registration
model and unpacks record-only fields into a snapshot. A pure regression and
fresh component repair are in progress. This is a fixture-adapter investigation;
the Brain's production validation and authorization requirements remain intact.

Preserve database `nexus_company_test_current_v8_negative_v1`, run namespace
`current-v8-negative-run-20261016-1`, frozen Source2, staged inputs and all release
records. Do not retry, reset or reuse them. A corrected attempt needs a separately
planned fresh source, database, roots, identities, units and operator pins.

## Remaining release proof

Finish the fixture correction and independent actual endpoint audit, then qualify
the five actual current-V8 fault/recovery cases. Fresh real runtime/Strategy pins
precede selected E/EV, independent acceptance and P/C publication. Genuine model
usage and US$5/day controls, owner email/UAT, ARM64, private deployment, recovery
and soak remain separate supervised-release requirements.
