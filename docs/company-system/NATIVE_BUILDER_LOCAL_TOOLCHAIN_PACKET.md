# Local native builder Node/pnpm stage packet

Prepared2026-10-14. Await Root's review before pull/download/install/build.
This is local reversible public tool/dependency preparation. It grants no Pi
installation, boot/cgroup edit, reboot, production deployment or provider call.

## Exact public pins

Official Docker Node source currently declares Node22.23.3 for Bookworm and
amd64/arm64v8 among its platforms; source commit
`81f419144a1251854c6d9afb09eaa39928e724e8`.
[Official images source](https://raw.githubusercontent.com/docker-library/official-images/master/library/node).
Docker Hub's exact22.23.3-bookworm metadata was read without pulling layers:

- Index digest: `sha256:0e5f906573693feaa1e21057ebdcfdb5bd5021f050b2dc7c9deceb629c7da2a8`.
- Linux/amd64: `sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d`, compressed410,533,676bytes.
- Linux/arm64: `sha256:80503c2cadca910dfe16f1516025a2133cdfb0e839f02e79191f83548f2ec729`, compressed401,699,727bytes. Declaration only; no ARM64 execution.

Only amd64 is selected for this local stage. pnpm is exactly9.12.0, matching
StockFlow's committed packageManager. Its public npm metadata/dist integrity is
retained in `native-builder/pnpm-official-metadata.json`; installation verifies
that retained SHA512 integrity and does not use Corepack's mutable selection.
[Exact public npm metadata](https://registry.npmjs.org/pnpm/9.12.0).

## Operations proposed for review

1. Create a task-owned0700 stage directory and empty registry auth file. Use an
   explicitly empty auth file and cleared engine environment, never existing
   Docker/Podman credentials. Resolve/read only the selected public digest.
2. Load/pull only `docker.io/library/node@sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d`
   for linux/amd64 with600MiB total compressed-download cap and600s timeout.
   Verify actual manifest/layer hashes/platform. Stop before loading if download
   exceeds that cap; retain partial failed receipt. Expanded image/operator
   storage reservation is3GiB and measured separately from job scratch. This
   reservation is not a claimed native filesystem project-quota proof.
3. Download only the public pnpm9.12.0 tarball from registry.npmjs.org, maximum
  32MiB/120s, verify its retained integrity, then install into a task-local tool
   prefix using `npm install --ignore-scripts --no-audit --no-fund --prefix /tools
   /downloads/pnpm-9.12.0.tgz`. The source registry credentials/environment are
   empty. No private repository, customer data, env file, token or model/database
   credential is present in this stage.
4. Prepare an exact public dependency cache for the nominated StockFlow lock
   (`bb7cc00848bb650069543e843f826703d468058c`, lock SHA256
   `57846422cd13346efdaf12bcde91d4d9e42c18eee21d7aafd5fa69b4a49877b3`).
   The reviewed input set is package manifests/workspace layout plus the lock,
   with no application source or private/env/configuration files. Use explicit
   registry.npmjs.org and `pnpm fetch --frozen-lockfile --ignore-scripts
   --store-dir /cache/store`. Public lock-declared tarball hosts/redirects must
   pass a frozen allowlist before fetching; no unrestricted project script
   network. Stage max2CPU/4GiB/256PIDs/900s; total dependency downloads512MiB,
   cache2GiB. Reject unsupported/private registries rather than using credentials.
5. Freeze tool/cache manifests: Node/pnpm versions, image ID/platform/digests,
   lock/input hashes, every downloaded package integrity, bytes/time and any
   missing tooling. After staging, project commands run with networknone,
   readonly source/cache and only bounded scratch/output mounts. No mutable
   tag, automatic pull, install hook or unqualified cache is admitted by runner.

The current native runner has actual read-only source, hard tmpfs scratch,
explicit memory/CPU/PID/time/output caps and current M1 intent/fence checks.
Writable build caches (for example `.next`) need separately bounded declared
scratch mounts; source remains readonly. Keep install networking separate from
the job. A network namespace alone cannot enforce registry hostname allowlists.

## Representative local StockFlow checks

From the exact committed source, produce baseline receipts for:

1. `pnpm --filter @stockflow/web typecheck`
2. `pnpm --filter @stockflow/web test`
3. `pnpm --filter @stockflow/web build` if required public build prerequisites
   fit; missing env/database/dependencies remain failed/inconclusive.

Then apply only an exact protected/approved patch under the allowed source
paths and run the same frozen relevant post commands, with a distinct verifier
against unchanged acceptance criteria. No engineering change is fabricated by
this stage packet. Maximum individual command300s and job1200s,2CPU/4GiB,
scratch2GiB/output64MiB/log1MiB; exceeding bounds stays a measured failure.
Browser packages/Playwright and database-dependent integration require their
own explicit cached prerequisites; no silent download or production DB access.

Existing cached Debian probe already proved actual local64MiB/2CPU/32PID kernel
configuration and1MiB tmpfs ENOSPC with no host mounts/network. It has no known
Node/pnpm toolchain and is not a StockFlow build pass. Local Node preparation and
checks cannot establish ARM64 compatibility, business readiness or M4 exit.

Evidence: `native-builder/node-official-tag-metadata.json`,
`pnpm-official-metadata.json`, `local-qualification-first.log` in the dated
implementation evidence directory. Exact shell/manifest downloader and task
cleanup remain to be implemented/reviewed before this packet is executed.
