# Actual contained collector-stop and outer timeout

Checked 2026-10-15. Exactly one separately reviewed synthetic amd64 fault operation
completed in49.867 seconds. Its external60s GNU timeout did not fire. The four owned
controller commands and external monitor were reaped; no observation/write tasks
were pending at terminal export.

The original policy selected `node timeout.cjs`, a fixed714-byte Node parent/child
workload, under unchanged methodv6 and image. The parent scope allowed45s plus1s
stop,4GiB/2CPU/256PIDs; child limits stayed256MiB/1CPU/32PIDs,10s command/25s job.
Fixed30s aging preceded actual bootstrap/admission. Actual pre-spawn timing proved
the outer deadline preceded both inner deadlines by the required margin.

One complete native host sample captured seven actual processes, including the
Node parent/child, collector/runtime/conmon/payload, current caps and owned identity.
The collector then stopped only itself after exact PID/start/cgroup checks. The
outside observer saw collector stateT and the complete live subtree before deadline.
At deadline+0.2s, six recorded survivors remained; by deadline+1.5s the complete
subtree was absent and all seven recorded PID/start identities were absent.
That terminal absence was1.347634s before the earliest inner command timer and
16.347634s before the inner job timer, so those timers do not explain this boundary.

Actual systemd queries reported failed/timeout for the original invocation
`7d9916a6ad994b8098153fdd13c920a1`. Missing-unit state alone was not accepted.
These observations support outer timeout and descendant termination, including
post-TERM survivors; no individual process's final signal is inferred from absence.
The original Started.parent wire is retained:2460bytes, SHA256
`d5f4562b3c0738cfa8492c144545b13a6a81d8b77c81174fd89a1586db502e5e`.

The native action remains issued with one original intent/attempt/tool use and no
result receipt. Root's fresh SQL at04:13:11Z found author running/fence1 with its
original lease expired at04:13:08.416518Z, model0, hold0.01USD/null actual billing,
and zero application backends. Root and verifier remain unissued/fence0.
The controller never released/claimed/reconciled the lease or removed the container.
Expired-lease recovery and retained container metadata/disposal require a separately
reviewed operation. Process absence does not establish a native result or refund.

Subsequent [ledger-only recovery](CONTAINED_OUTER_LEDGER_RECOVERY_CHECKPOINT_2026-10-15.md)
now classifies the original intent/cost as unknown and clears its reconciliation
lease, preserving the original attempt and amount. Retained object handling remains.

Evidence under `/home/santapong/.codex/nexus-contained-outer-fault-qualification-20261015`:

- Source freeze63912df1e8b3095e8e0349b31a4d722e7460445df784a0b8681892e5a0e3b9ee;
  dynamic packet39cd4a27c5f618510c21389bbb88afcd9f4e7c39094aad6c37c0dd3dc8e5f7a0.
- `m1/fault.json`7f654e26c3c145fb871e885fbda7f7f33a613ca00e480d9f36cd0dbcf1e2f77e;
  `m1/before.json`83aaa6d1577f4baa0d1817b237063ebd3150226498916e9a55316f28ab1461e6.
- `m1/after_term.json`a531770047fe19b8445ed8764df5829954ec8552d57e56cedf07420cff9d48d6;
  `m1/terminal.json`bd829189df42e259a9c48bc698365cf22a14765d9e61fbc42923e08b9807a876.
- Root terminal receipt7cfa65b3bbc2e898448a4a455ecb3d70626b0f8273277ab588da0a208e6aa0c8.

Independent terminal file auditcf69a8c6f8f020391b9923b8c27fcd449d79b281d95f1b70d8bb0e0861caea12
matches57 unique pins, all1491 baseline files, actual timing/identity/termination and
the retained unknown ledger. No result, sidecar or diagnostics were found; a
zero-byte result-slot lock is infrastructure, not output. Original normal M1 and all earlier
failed cases are unchanged. This proves this synthetic outer termination boundary;
ARM64, nominated StockFlow work, full recovery, kernel hard-death guarantees and
operational release remain separate.
