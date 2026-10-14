# Native builder implementation and qualification

Prepared2026-10-14 against `da013b5` plus active M3 packages. M4 remains open.
Sources: SDDv0.2§12/§16, IMPLEMENTATION_PLAN M4/BUILD-01/VERIFY-01/GOV-03/04,
ADR-097 and RELEASE_EXECUTION_PLAN. This is a native Nexus package; Accretion
and legacy E2B are not its engine. Owner UI is separately waiting for the human
password step and is untouched by this work.

## Current evidence

Read-only Pi checks used the established rpi-access health script and
`ssh -o BatchMode=yes -o ConnectTimeout=8 pi-tailscale`. The09:00ICT observation
is ARM64 Debian13/kernel6.18.50,4cores, Python3.13.5,12GiB available memory and
79GiB root free. Podman/crun/uidmap were absent; subordinate UID/GID ranges and
the delegated cgroupv2 user service exist. The available controllers exclude
memory; the boot arguments explicitly contain `cgroup_disable=memory`.
No container/namespace or memory-limit execution was attempted.

Docker/nginx/Tailscale and n8n/Redis/Postgres/Loki were healthy; no failed
systemd units. Prometheus/resume/ruview probes were unreachable. They were not
diagnosed or changed. Load was4.25/2.55/1.12 and temperature60.9°C. Storage under
the historical Seagate name still binds `/srv/service-data` on the root SD
filesystem; it is not an independent backup disk. Serve/Funnel outputs remained
tailnet-only. These are point observations, not capacity or soak qualification.

The absence of the memory controller prevents qualification of the4GiB hard
job cap. Controller availability and the `memory.max` interface are defined in
the [Linux cgroupv2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).
Do not substitute an unbounded container or per-process address-space limit.

Local x86 has Podman5.8.6; only its version/help was read. Its help confirms
`--pull=never`, `--network=none`, memory/CPU/PID flags and the default host proxy
inheritance that must be disabled. Debian's current ARM64 Trixie package is
Podman5.4.2+ds1-2+b2, an installation candidate requiring actual Pi package
resolution before approval. [Debian package](https://packages.debian.org/trixie/podman),
[versioned Podman5.4.2 run options](https://docs.podman.io/en/v5.4.2/markdown/podman-run.1.html).
The local5.8.6 versioned web manual was unavailable; installed help supplied
the local version evidence. No runtime compatibility is inferred from docs.

Nexus pins Python3.12, PydanticAI2.54.0, DBOS3.2.0, Pydantic2.13.4 and
Litestar2.24.0. Their actual ARM64 import/runtime remains a separate check;
the Pi's host Python3.13.5 is not that evidence. StockFlow's nominated commit is
`bb7cc00848bb650069543e843f826703d468058c`, tree
`e0ed0e5618d3dda4d0cde0fd2cdc5642a99c8ac2`:443files/2,769,972bytes,
no tracked symlinks, pnpm9.12.0, Next15.5.23 and Node>=20.10.0.
Working-tree changes are excluded. Source presence does not prove a build.
Actual local x86 preparation produced an exact3,194,880byte archive, SHA256
`4e9d4164d29905837055a38ec42ab7c53b9796bc0df474ece61172ae5a10a507`.
After an explicit private-mode check denied the evidence filesystem before
content write, the443files were extracted into an actual0700 task directory.
The earlier source-preparation receipt is historical and does not qualify
private workspace storage. No build or ARM64 execution occurred.

## Interfaces and implementation boundaries

`nexus/builder` initially provides strict immutable job/policy/capability/command
receipt descriptions, exact action/lease input matching, bounded committed Git
archive preparation, anchored ordinary-file reads and a fixed Podman argument
description. It starts no worker, invokes no sandbox, registers no tool and
changes no schema/API/runtime. Positive capability DTOs in tests are synthetic;
decoding or matching a DTO is never an execution permit.

The job binds company/task/trace/run/workspace/actor/action, exact repository
commit/tree/archive hash, optional patch hash, policy, architecture, finite
baseline/post command references, write/export paths and resource bounds.
Model/caller inputs cannot select engine flags, host directories, credentials,
remote engine URLs or raw commands. Process-owned policy supplies exact image
digest and command vectors. Runtime network is always none in this package.
Registry preparation is a distinct trusted stage; it cannot enable arbitrary
network access for project scripts. Default hard bounds are2CPUs/4GiB memory,
2GiB workspace,64MiB outputs,1MiB logs,256PIDs,300s per command/1200s per job.
The local source preparer additionally bounds archives32MiB, expanded source
16MiB and4096entries. Bounds may be narrowed; exceeding them denies admission.

Local preparation denies missing rootless/cgroup CPU-memory-PID/hard-disk/
network/image qualification. The fixed argv uses no pull/proxy inheritance,
read-only root/source, no new privileges and no added capabilities. It is not a
complete runnable builder: writable scratch/output collection, hard aggregate
disk proof, lifecycle cancellation and M1 integration are still required.

1. **M4-A preparation:** freeze these descriptions/helpers and the qualification
   inputs. A real local Git fixture proves exact committed bytes despite dirty
   files; unsafe tar/link/special-file/size cases deny. This is local x86 proof.
2. **M4-B runner:** add a single-slot native process service and typed trusted
   entrypoint. Original and patched source are separate immutable snapshots.
   Project commands receive read-only source and pinned read-only dependency
   caches; only declared bounded scratch/output areas are writable. Hard
   scratch/output quotas must be enforced before running, not merely monitored
   afterwards. Stop producers before collecting exports. Persist exact bounded
   logs, command outcomes, patch, source/input hashes and qualified tool identity.
3. **M4-C governance/recovery:** bind `company.builder.run.v1` to actual current
   managed work. Reuse the existing CompanyControl-first M1 lease/effect/hold/
   permanent-counter path and DBOS3.2 global concurrency1. Any filesystem patch
   or sandbox launch occurs only after fresh authority and committed intent.
   Keep begin→single launch→saved output→receipt in one I/O step; never checkpoint
   the one-time call permit. Approval waits release the slot before a container
   exists. Native stop, pause/revoke, expiry and stale fence terminate or deny
   issuance; issued facts/billing remain reconcilable. Existing intent or process
   loss never causes blind command re-execution. Reconcile a known manifest/CID
   or preserve unknown outcome. Shared runtime/schema edits remain Root-owned.
4. **M4-D independent checks:** use the actual distinct verifier/current approved
   binding and complete current source/output permission/freshness. Baseline
   failures, missing tooling, limits and unknowns are visible. Receipt success
   only says a command ran; it cannot publish accepted work. New trusted builder
   checker recipe/artifact support must be implemented before acceptance.
5. **ARM64 qualification:** after separately authorized setup, run the frozen
   pack and one nominated approved StockFlow engineering change, with baseline
   before change, exact patch and relevant post checks. Capture actual usage and
   failures within the envelope. If the representative job does not fit, report
   the measured constraint and revise hosting; do not increase caps or weaken
   criteria to pass. Push/PR/deploy/customer communication are separate actions.

No approved StockFlow change or tool image digest is fabricated here. Root must
freeze the concrete task, exact source/patch, commands and qualified multi-arch
tool image before a live run. Full source/patch/log/outputs inherit complete
resource/source provenance; private fields cannot become public review exports.
The existing report-only artifact publisher/checker cannot silently represent
a native engineering verifier. Propose needed interfaces/schema explicitly.

## Bounded qualification pack

Each receipt records source/tool/policy versions, architecture, command/exit
status, actual timings/limits, hashes, scope and remaining uncertainty. Local
unit/static checks and real ARM64 checks are separate columns in the manifest.

| Case | Required actual proof |
| --- | --- |
| Exact source | Nominated commit/tree/archive; dirty files absent; changed pin denies |
| Path boundary | Absolute/traversal/symlink/hardlink/FIFO/device escape attempts deny |
| Image/tool | Digest and ARM64 image/platform/tool versions; missing tool remains failed/inconclusive |
| Network | Runtime DNS/TCP/UDP/host/service access denied; install stage separately constrained |
| Credentials/mounts | Synthetic host markers unavailable; no real secret inspection; no production write mount/socket |
| CPU/memory/PIDs | Actual cgroup CPU quota/memory.max/pids.max and bounded limit behavior |
| Disk/log/output | Actual hard write failure/termination at configured bounds; no post-hoc cap claim |
| Single slot | Two contenders admit one; approval waiting releases capacity |
| Stop/fence | Real cancellation/pause/revoke/stale lease blocks/terminates; facts preserved |
| Crash/replay | Process kill before/after intent/output; same action never launches twice; unknown stays unknown |
| Baseline/post | Independent unchanged criteria; baseline failure/timeout cannot become acceptance |
| StockFlow | Actual approved bounded patch, relevant checks, reviewable diff/artifacts on ARM64 |

M6's24-hour soak, independent encrypted restore/private deployment and owner
notification remain separate release requirements. Rootless Podman reduces
privilege; this pilot does not claim a hardened hostile multi-tenant sandbox.

## Future Pi approval packet

No Pi mutation is requested or authorized by this document. Before the final
explicit approval, provide exact package/tool/image versions and hashes,
dedicated workspace/storage limits, scoped files to change, rollback, named
test cases/maximum runtime, expected impact and unchanged-service checks.
The concrete known prerequisite is removal of `cgroup_disable=memory` from the
selected boot configuration followed by a maintenance reboot; Root must verify
the exact file/current contents and prepare a reviewable diff before asking.
Install rootless Podman/runtime/UID-map prerequisites only after that approval,
then prove actual delegated resource limits. No broad service stop/prune,
network exposure, credential changes or implicit production deploy belongs in
the packet. Existing Pi workloads make the reboot a separate material action.

Evidence directory: `/mnt/data/nexus-implementation-evidence-2026-10-14/native-builder/`.
