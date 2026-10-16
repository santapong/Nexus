# Original-owned container stop and current V9 source

Checked 2026-10-16 (Asia/Bangkok). The coherent production source passes 4,307 unit
tests, configured nonsilent strict typing and Ruff lint/format on 11 files. Native V9 qualification
and the supervised release remain open. The default candidate stays unconfigured
and `execution_ready=false`.

The [Source5 wave](CURRENT_V8_NEGATIVE_ADMISSION_CHECKPOINT_2026-10-16.md) proves
parent expiry and metadata recovery, then fails cancellation retirement despite
native detection in 228 ms. Killing the runtime client leaves five container
processes alive at the original bound. Preserve that stopped wave, its three
unissued cases, original windows, unknown amounts and all retained containers.
This source repair neither reclassifies nor resumes it.

## Changed behavior

`ContainedOwnedStop` selects only the original opaque context's sealed full
container ID, with exact original process, binding, company, action, name and image.
The context retains its construction-time seal. Its synchronous one-shot latch
prevents repeated or concurrent stop transactions, including a replacement service.
Portable data, another seal and historical records do not confer this control.

Fixed local Podman commands inspect, signal KILL only if running, wait and inspect
again. One cap of 5 seconds is shortened by the original operation/parent/owner ends, with a
100 ms reserve; complete stdout/stderr caps are 65,536/4,096 bytes. No removal, new
execution permit, allowance reset or renewed deadline is introduced. Missing or
expired ownership and incomplete replies remain unknown. Engine metadata cannot
replace the original full PID/start retirement oracle.

The process owns a shielded finalizer before closing its context. Known native
denial stops before client drainage. First cancellation during initially normal
drainage signals that same finalizer promptly while the actual drain stays owned.
Repeated cancellation preserves the first error and actual tasks/child handles.

An already-issued control CLI may settle after the bounded reply becomes unknown.
A retained resource-only continuation adopts that actual child and drains/reaps
or aborts its handle. It issues no new container command or positive result.
Typed resource settlement checks actual futures, child/reap/readers and original
root/leaf descriptor closure. A failed descriptor close is not inferred complete
from the earlier closed flag. Semantic uncertainty remains separate from pending
resource ownership.

Current V9 wraps the exact preserved V8 expression and binds these stop semantics.
Named V6/V7/V8 identities and explicit old result/sidecar reads remain intact.
Old method pins cannot construct fresh services or pass current protected
interpretation. Metadata-only recovery stays distinct from runner republication
of old results, which remains current-gated. No public wire, schema or dependency
changes accompany the production package. [ADR-130](../DECISIONS.md#adr-130--stop-the-original-owned-container-before-releasing-run-ownership)
records the boundary.

## Verification and retained review

Held candidate1 passes 125 focused checks but independent finite counterexamples
reject it: replacing the seal before first stop redirects the ID, and cancellation
during normal drainage can consume the stop budget. Its nine source files remain
preserved. Candidate2 fixes both and retains actual late-child ownership.

Candidate2's author checks pass 130 finite/compatibility cases in 2.24s, configured
nonsilent strict typing and Ruff lint/format on nine files. The independent narrow
forward review passes the original counterexamples plus late-child/descriptor
cases: seven tests in 1.36s, with no remaining finding in that scope.

Evidence under `/mnt/data/nexus-implementation-evidence-2026-10-14/stockflow`:

- `native-owned-stop-independent-file-review-1.json`, SHA-256
  `e034a156412f62538512e265ac0b3714936e04f90419301a0a985d7a1d7a4931`.
- `native-owned-stop-v2-forward-file-review-1.json`, SHA-256
  `d877142b8f0fa5d643daa85b40175d7bdb5a43c34b30679a5cb12293e7d8c1d4`.

Candidate2 hold is
`/home/santapong/.codex/nexus-native-owned-stop-component-20261016-2/WORKER_OWNED_STOP_V2_SOURCE_1.json`,
SHA-256 `90843bfff650d236a30b51b2aa724974d63570dfab2cc03784f3fa39ba602a92`.
The coherent production candidate has 1,627 exact backend files, including the V9
identity/history unit. Its source manifest SHA-256 is
`b5f96e7bfcecf950b0647fe63dabe52eb0ede5a6d5ee0eba2f560772df947398` under
`/home/santapong/.codex/nexus-v9-production-check-20261016-1`.
Unrelated original untracked PG helpers are excluded from that declared source.
Root's full backend regression passes 4,307 tests with 19 existing deprecation
warnings in 78.41s. Configured nonsilent strict typing and Ruff lint/format pass on
all 11 changed backend files. Each check verifies the 1,627 declared source rows
unchanged afterward. Byte-exact forwarding verifies all 1,627 repository rows match
that tested source, excluding the unrelated original untracked PG helpers.

Receipts under that source directory's `checks/`:

- `unit-receipt.json`, SHA-256
  `75dc4feec4e6d957903a6d7becfddab57d51de82b6f660f8be281bef8c88b559`.
- `strict-receipt.json`, SHA-256
  `6fd3ad7a7e18e74a853cba35ed8860fe49140c11debea1c4ce83f042df0823a3`.
- `ruff-receipt.json`, SHA-256
  `a01562d9ca99d37877eef1a946b120deb600500dc3abd7839d60930d5144af82`.

The clean source import confirms the current V9 method SHA-256 is
`479c771861bd14cf10808819c4a9412e862e9c710621ed5808cce646a0be1c65`,
while named V8 remains
`90aa8a81de487509b88d251c953a7273aa07c27449235c72ce7adedc005aad28`.
The candidate remains false/unconfigured. Source tests do not establish physical
containment, actual selected execution or business acceptance.

## Remaining qualification

Private collector/operator ownership bridging and complete control-channel
composition remain separate source work. The earlier collector ignores the new
ownership surfaces; live asyncio Tasks alone cannot account for every completed
unresolved result or unreaped child. Bind actual typed resources before teardown,
retaining existing report bounds, first cause and physical predicates.

After production source checks and commit, create a fresh exact tracked production
BASE. New source/namespace/action/profile pins must qualify all five original
native fault cases before selected StockFlow E/EV. Do not use old successful cases
as new-method permission or renew a stopped wave. Full business/model/budget/email,
ARM64, owner UAT, private deployment and recovery/soak gates remain open.
