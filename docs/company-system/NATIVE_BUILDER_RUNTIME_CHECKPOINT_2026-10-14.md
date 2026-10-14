# Native builder local runtime checkpoint

The bounded native runner now uses actual M1 leases, approved actions, immutable
intent, lifetime attempts and unknown-cost holds. One new call permit launches
one rootless Podman process. Current approved-plan, membership, cancellation,
repository/patch/output READ and qualified source freshness are checked before
intent and during execution. Renewal uses the existing M1 lease store; it does
not change fences or reset counters. Old or unobserved intents never run commands
again. Known saved output can supply the same receipt under current native scope.

The exact proposal contains the complete job, policy SHA, runtime recipe,
protected patch reference and protected output target. The target must match the
current named catalog before intent. Private committed snapshots exclude working
tree changes and credential paths. Ordinary UTF8 text modify/create/delete
patches are hash-bound, checked against committed context and constrained to
declared paths. Both inventories remain bounded; the baseline stays unchanged.
Binary, rename, mode-change and unsupported patch syntax fail explicitly.

The container has no external network, proxy inheritance, owner home, Docker
socket, privileges or inherited host DNS/hosts/hostname. Root and snapshots are
readonly. Explicit scratch/output/tmp tmpfs sizes partition the writable job
envelope. Process time, memory, CPU, PID, output, aggregate log and ordinary
artifact bounds are checked. Known log/export failures retain actual command
exit facts and cannot become success. Missing or interrupted observations stay
unknown. Cleanup removes only the exact stopped labeled container after durable
result and receipt; unknown containers are not blindly removed or rerun.

Protected summaries carry all repository and patch input edges, strongest input
classification and current readership. Final input/output/recipient deadlines
are checked after awaited publication. Independent native verification requires
the actual distinct current plan binding, exact M1 succeeded receipts, complete
protected bytes and fresh full permissions. Its mechanical candidate grants no
work acceptance, delivery or spend authority. File-only history is unqualified
for this verifier; the engineering acceptance publisher remains unconfigured.

Validation on the restricted dedicated builder database used normal company014
upgrade/downgrade. The coherent matrix passed72 tests in43.41s (62unit/10PG).
Final missing-output-target plus positive tests passed2PG in7.50s, with zero
intent/attempt for the missing target; strict38/lint/format pass. Overlapping
counts must not be added. Original startup failure8PG is preserved: installed
Podman5.8.6 rejects DNS options with networknone. An exact private empty resolver
readonly mount replaced that incompatible flag; no host DNS was copied.

Actual local probes prove64MiB/2CPU/32PID limits and bounded tmpfs ENOSPC. The
current native mount probe proves the exact4MiB writable fixture envelope; these
are small x86 qualification cases, not a4GiB memory stress or ARM64 run. Public
Node22.23.3-bookworm amd64 manifest/layers and pnpm9.12 tar were integrity-checked
under an observed4GiB/2CPU/256PID transient scope. Offline image load succeeded;
no pnpm installation or dependency cache networking has run. Scope timeout
qualification killed a separate-session TERM-ignoring child using finite cgroup
SIGKILL; the original immediate-child-state observation failure is retained.

Exact source/receipt pointers are in the dated `native-builder` evidence directory.
The accepted preparation freeze and public-stage freezes remain unchanged.
Representative committed StockFlow checks still need the reviewed bounded public
dependency cache. Current Pi readiness still lacks Podman and the memory
controller (`cgroup_disable=memory`). No Pi installation, boot change, reboot,
service or provider activation occurred. ARM64 qualification, engineering/business
acceptance and full M4/release remain pending.
