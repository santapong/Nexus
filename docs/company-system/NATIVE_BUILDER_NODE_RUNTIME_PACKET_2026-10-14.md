# Native Node runner and nominated-source local qualification

This is a local amd64 preparation and runtime checkpoint. It does not close ARM64,
engineering work acceptance, current StockFlow business readiness, or release.
The owner's signup page remains handed to the human.

## Implemented boundary

`NodeNativeBuilderRunner` extends the existing actual M1 runner. Its server-only
configuration resolves named public tool/cache inputs to fixed paths; proposals
carry exact image/tool/archive/manifest/lock/command-recipe pins, without portable
host paths. The complete policy hash and exact native proposal include those pins.
When Node inputs are absent, historical JSON bytes and canonical hashes remain
unchanged. Only `policy.py` and `execution_contracts.py` amend runtime-freeze-v2;
the other 38 hashes are unchanged. All 13 public-cache-v2 hashes are unchanged.

Preparation checks bounded ordinary input bytes, SHA256/SHA512 integrity,
manifest lock identity, complete extracted files/modes, and both committed/post
lockfiles. The job requires the complete ordered baseline/post recipe: offline
frozen install, web typecheck, web test, web build. Install disables package and
pnpmfile hooks; implicit pre/post scripts are disabled. Explicit approved scripts
remain intentional sandboxed code. The pinned [pnpm 9.12 install source](https://raw.githubusercontent.com/pnpm/pnpm/v9.12.0/pkg-manager/plugin-commands-installation/src/install.ts)
defines `--ignore-pnpmfile` separately from `--ignore-scripts`.

Node jobs copy read-only source snapshots into a bounded executable scratch
tmpfs for native dependencies. Generic scratch remains noexec. Both retain
read-only root/source/tool/cache/command mounts, network none, pull never,
nodev/nosuid, no new privileges, dropped capabilities, private namespaces, and
hard CPU/memory/process/time/workspace/output limits. `/tmp` and `/outputs`
remain noexec. Source/patch/output permissions and freshness, exact caller/guard
binding, actual intent/fence, lease renewal and unknown-outcome recovery remain
the shared native M1 boundaries. A known replay executes no commands.

## Executed evidence

- 32 focused units passed in 1.16s, including the 12 existing policy checks and
  original byte/hash fixtures. The new fields cannot claim ARM64 from amd64 pins.
- Three restricted PostgreSQL/native-container cases passed in 27.11s: one
  process/eight commands/protected result/known replay; baseline exit7 with a
  native failed receipt and no post; changed cache denied before intent/process.
  Successful fixture output proves scratch execution, neighboring noexec mounts,
  read-only source/cache/tools/commands, and absent home/socket host mounts.
  Hostile pnpmfile/install/pretypecheck hooks did not execute.
- Strict16 and lint/format passed. Six new production modules are under 300 lines,
  all functions under 50. Synthetic no-dependency/empty-CAS fixtures prove the
  runtime boundary, not completeness of StockFlow dependencies.
- The actual 517-package public cache has a 725,964,800-byte GNU archive,
  SHA256 `0a2e63c465bf19598d7814646219b492ae870fe91e87eddcc5dd13e69d32c239`.
  Download/import scope limits and SRI receipts are retained. The separate
  post-extraction read-only probe passed in 3.613s: actual pnpm9.12 store status,
  preserved executable modes, denied write, and exact container cleanup.

Early static-fixture architecture mismatch and mypy import-export failures are
retained with their corrected checks; neither is counted as successful execution.
The earlier actual two-case Node receipts remain historical. Tests use normal
profile head dynamically; the later concrete prepare observed company015.

## Concrete prepared packet — project execution pending review

`/tmp/nexus-builder-stockflow-native-20261014-v1/prelaunch.json` has SHA256
`320a09aa1c897de63188787b71615430b5d83e6f4b1c27c1dbd5f9df18ce025e`.
It contains a persisted approved/authorized action on a current native registered
plan, exact output resource, complete spec/policy, and derived engine argv. The
lease was released for review. There are zero intents or project processes.
Native authorization reserved two $0.01 holds: the generic setup action and
exact Node action. Both actual USD values are null. No hold/counter/history was
rewritten to conceal the unused setup action. The earlier mistaken no-hold
annotation remains in the historical v1 packet.
Identities and plan/catalog evaluation basis are explicitly disposable fixtures.
The dedicated `nexus_company_test_builder` database is held in that prepared state.

The source is the historical nominated StockFlow commit
`bb7cc00848bb650069543e843f826703d468058c`, tree
`e0ed0e5618d3dda4d0cde0fd2cdc5642a99c8ac2`, archive
`4e9d4164d29905837055a38ec42ab7c53b9796bc0df474ece61172ae5a10a507`.
Its original lock is pinned to `57846422cd13346efdaf12bcde91d4d9e42c18eee21d7aafd5fa69b4a49877b3`.
No engineering patch is nominated: baseline and post are unchanged-source
toolchain qualification. Baseline failure stops post and remains a failed receipt.

The prepared action is `d721a60e-1db1-4d95-a3be-1620a9c402b1`, proposal SHA256
`092e609b0016730879cae28c1e6f6726990d5342a429344e0d2a14c049b424e1`, policy
SHA256 `473576ccea49ff36819c971903c1bd8c31f5aae0286edb222685b2d3fc4cd0a7`.
The cached Node image is the actual localhost qualified digest from the reviewed
public stage; exact image ID and all public input hashes are in the packet.
Limits are CPU2, memory4GiB, process256, workspace2GiB total, output64MiB,
aggregate logs1MiB, each command300s, whole job1200s. Tools/cache remain read-only.

The manual test-only run module validates the entire packet/state hashes,
reclaims the same actual task under current native authority, and uses the same
action/spec. It validates the exact derived argv before the one Podman process.
Known/unknown recovery follows the existing runner; no new action/counter reset
or repeated commands are introduced. Actual local USD remains unknown; a receipt
must preserve the native hold and null billing fact rather than assert zero.
Production workers do not import these manual fixture drivers.

No private project call, provider, worker activation, Pi mutation, deployment or
email is part of this prepared checkpoint. Actual Pi qualification remains blocked
by missing tools and the live absence of its memory controller; a disk cmdline
already lacking the active disable flag is not permission to edit or reboot it.
