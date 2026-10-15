# Native startup diagnostic checkpoint — 2026-10-15

Latest actual V4 fails before readiness after1.60s. Its passive observer records
the controller at the original root, two direct processes and no subtree
controllers, then a generic ValueError without an exact read-step witness.
The owned CLI is killed/reaped for failed-run cleanup; the container remains
created and removal is unresolved. Later checks find the scope and controller/
runtime PIDs absent, with21 inventory rows: the original20 plus that retained
container. No ready marker, barrier, PID tree, payload or timeout is qualified.

V4 source passes110 focused checks, strict/Ruff8 and independent review. It
adds descriptor/proc-only readiness before any postspawn query and cleanup-only
identity sealing after the owned CLI is terminal. All16 actual queries are
retained; the first postspawn query occurs after CLI termination. The next source
investigation concerns canonical default payload limits before runtime setup;
that is a supported candidate, not the uniquely established actual failure cause.
All failed sources, namespaces and the retained container remain unchanged.

| Later V4 evidence | SHA256 |
| --- | --- |
| Frozen source | `3fe9d4e92c66bc4c306f04f3f064188defd42ddf31990d79102a57ff80d5bd22` |
| Independent source review | `c5f53b404524c2f5e16568b4dd9ae578b06f11f4348fde6463a00679cf2724c1` |
| Actual terminal | `21f484fe921d994683434b52ddace500ce4c872b825eea07751542a8df1653eb` |
| Independent actual file audit | `55e224e4ae543b0de3d2c20d03be832521927cc38b7d73e51a1bddb79a43ef7b` |
| Later read-only state | `818d6d75cc66556f6af75cfb477b5ecf4c1a60bf43207f37a720e51cc85c7544` |

The earlier V3 observations below remain historical evidence.

The fresh diagnostic captures an actual **container startup failure** before
readiness or payload execution. runc reports a missing `pids.max` in the new
payload cgroup. This identifies the immediate failing operation; the underlying
controller setup or race remains under investigation. No runtime limit or frozen
timeout expectation has been relaxed.

## Source and actual execution

The first source review found that an initial fallible stderr mark could throw
after capture tasks were scheduled but before the caller retained them. A fresh
V2 moves that mark before task creation; its78 mock tests and independent review
pass. Its actual0.93s startup failure records CLI127 but misses the early stderr
and extended state. The original source and failed namespace remain intact.

Fresh V3 eagerly owns one bounded stderr collector alongside wait/export tasks.
It snapshots completed early-failure facts and attempts the fixed sealed-ID state
projection before freezing diagnostics and cleaning up. Four early-failure cases
bring the focused regression to82 passes; strict typing and Ruff check/format
pass across six files. Independent source review is favorable. The1,585-file
closure preserves all backend and kernel-observer bytes from its original base.

Actual V3 runs0.99s at12:55:56UTC and fails in seal with FileNotFoundError. It
retains actual CLI127,451 stderr bytes, empty stdout/export and a915-byte fixed
state projection before the original20s capture deadline. State is created,
running=false, payload/conmon PIDs0, timestamps unset and exit_code0. The error
explicitly names runc's cgroup configuration operation and missing payload
pids.max; created-state exit_code0 does not indicate successful execution.

No ready marker, original runtime start stamp or live process tree was captured.
The state projection's failed live-terminal validation is recorded separately
without replacing the first failure. Exact sealed-ID removal and runtime reaping
succeed without cleanup errors. Later read-only checks find the unit, cgroup,
controller and runtime PID absent and the same20-container inventory. These
corroborate cleanup, not timer enforcement or original process identity.

| Evidence | SHA256 |
| --- | --- |
| V3 frozen source manifest | `a5ce74419c00f9d13fd1739402332076d0e0c50a7f210874e2f55cdb54b9cab0` |
| V3 independent source review | `3fb4d8b519189ad39e6f51ccf86369fcd9f4960aaab152ca73900ea601ea3b4a` |
| V3 actual terminal report | `128cde24fbe8e40842abfe1a9db64e9bfa83eb74ac1a9ba0209ff606f76c5a3c` |
| V3 independent actual file audit | `444875b8e5bd245f1457de24ea839e415bbb5dba0674cdf6edb9addca77e57d0` |
| V3 later cleanup corroboration | `211279a19c51443d82248e2c814eea49d7cf78444dbb11a0515d73f9a8dc5964` |
| Read-only current OCI/controller facts | `69c17aed2507ef5d041844c6d88878fca3a2a861b1c251777d196dd3811e3c8f` |

Private raw records are under the dated stockflow evidence directory. Read-only
OCI info identifies configured runc1.5.1; actual stderr independently names runc.
Current user/app ancestors expose and enable cpu, memory and pids, with empty
direct process lists. Those later observations cannot reconstruct the removed
parent's subtree controls. No host configuration was changed or failed run retried.

## Pending qualification

The earlier [normal tiny bootstrap](HOST_BOOTSTRAP_262_CHECKPOINT_2026-10-15.md)
passed, while its separate timeout failed with inspect-1 versus frozen137 and
missing CLI/stderr evidence. The new startup failure neither explains that older
timeout uniquely nor qualifies it. Preserve all failed sources, original clocks,
namespaces and expectations. Next is a source-supported startup remedy, fresh
bounded normal/negative-recovery evidence and a separate full dependency import.

Full517 CAS preparation has a file-only input plan; actual import remains held.
Current full V7, opaque Company-issued execution, actual StockFlow E/EV, P/C
acceptance and the supervised release remain pending. Unit tests and diagnostic
observability do not establish those outcomes.

Read-only Pi readiness separately confirms ARM64/systemd257, disabled memory
control, absent rootless runtime and a256MiB tmpfs /var/tmp. Persistent storage,
complete package transaction/rollback and an approved reboot window must precede
Pi changes. Its boot/package candidate is a plan only; no Pi mutation occurred.
